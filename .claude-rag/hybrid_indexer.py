#!/usr/bin/env python3
"""
Hybrid Codebase Indexer for Claude Code RAG
- Fast BM25 indexing (minutes, not hours)
- Lazy embedding generation (only when needed)
- SQLite storage for speed and simplicity
"""

import os
import sys
import hashlib
import sqlite3
import json
import time
from pathlib import Path
from typing import Generator

# Load configuration
CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)

DIRECTORIES = CONFIG["indexing"]["directories"]
DB_PATH = Path(CONFIG["common"]["database_path"])
INDEXABLE_EXTENSIONS = set(CONFIG["indexing"]["indexable_extensions"])
SKIP_DIRS = set(CONFIG["indexing"]["skip_dirs"])
MAX_FILE_SIZE = CONFIG["indexing"]["max_file_size"]
CHUNK_SIZE = CONFIG["indexing"]["chunk_size"]
CHUNK_OVERLAP = CONFIG["indexing"]["chunk_overlap"]


def init_db():
    """Initialize SQLite database with FTS5 for fast text search."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Main chunks table
    c.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            embedding BLOB,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
    """)

    # FTS5 virtual table for fast full-text search (BM25)
    c.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            id,
            file_path,
            file_name,
            content,
            content='chunks',
            content_rowid='rowid'
        )
    """)

    # Triggers to keep FTS in sync
    c.execute("""
        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, id, file_path, file_name, content)
            VALUES (new.rowid, new.id, new.file_path, new.file_name, new.content);
        END
    """)

    c.execute("""
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, id, file_path, file_name, content)
            VALUES('delete', old.rowid, old.id, old.file_path, old.file_name, old.content);
        END
    """)

    c.execute("""
        CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, id, file_path, file_name, content)
            VALUES('delete', old.rowid, old.id, old.file_path, old.file_name, old.content);
            INSERT INTO chunks_fts(rowid, id, file_path, file_name, content)
            VALUES (new.rowid, new.id, new.file_path, new.file_name, new.content);
        END
    """)

    # Index for faster lookups
    c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_path)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash)")

    # File tracking for incremental updates
    c.execute("""
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            size INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL
        )
    """)

    # Failed files tracking for retry logic
    c.execute("""
        CREATE TABLE IF NOT EXISTS failed_files (
            path TEXT PRIMARY KEY,
            error TEXT NOT NULL,
            retry_count INTEGER DEFAULT 0,
            last_attempt REAL NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_failed_files_retry ON failed_files(retry_count, last_attempt)")

    conn.commit()
    return conn


def get_files(directories: list[str]) -> Generator[Path, None, None]:
    """Recursively get all indexable files from directories."""
    for directory in directories:
        dir_path = Path(directory)
        if not dir_path.exists():
            print(f"Warning: Directory not found: {directory}")
            continue

        for file_path in dir_path.rglob("*"):
            if any(skip_dir in file_path.parts for skip_dir in SKIP_DIRS):
                continue
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in INDEXABLE_EXTENSIONS:
                continue
            try:
                if file_path.stat().st_size > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue
            yield file_path


def read_file_safe(file_path: Path) -> str | None:
    """Safely read a file, trying multiple encodings."""
    encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
    for encoding in encodings:
        try:
            return file_path.read_text(encoding=encoding)
        except (UnicodeDecodeError, OSError):
            continue
    return None


def chunk_text(text: str, file_path: str) -> list[dict]:
    """Split text into chunks with metadata."""
    chunks = []
    if len(text) < 50:
        return chunks

    start = 0
    chunk_idx = 0

    while start < len(text):
        end = start + CHUNK_SIZE
        chunk_content = text[start:end]

        if end < len(text):
            last_newline = chunk_content.rfind("\n")
            if last_newline > CHUNK_SIZE // 2:
                chunk_content = chunk_content[:last_newline + 1]
                end = start + last_newline + 1

        content_hash = hashlib.md5(chunk_content.encode()).hexdigest()
        chunk_id = hashlib.md5(f"{file_path}:{chunk_idx}".encode()).hexdigest()

        chunks.append({
            "id": chunk_id,
            "file_path": file_path,
            "file_name": Path(file_path).name,
            "chunk_index": chunk_idx,
            "content": chunk_content,
            "content_hash": content_hash,
        })

        chunk_idx += 1
        start = end - CHUNK_OVERLAP
        if start >= len(text) - 10:
            break

    return chunks


def file_needs_update(conn: sqlite3.Connection, file_path: Path) -> bool:
    """Check if file needs to be re-indexed."""
    c = conn.cursor()
    c.execute("SELECT mtime, size FROM files WHERE path = ?", (str(file_path),))
    row = c.fetchone()

    if row is None:
        return True

    try:
        stat = file_path.stat()
        return stat.st_mtime != row[0] or stat.st_size != row[1]
    except OSError:
        return True


def index_file(conn: sqlite3.Connection, file_path: Path) -> int:
    """Index a single file, returns number of chunks created."""
    content = read_file_safe(file_path)
    if content is None:
        return 0

    chunks = chunk_text(content, str(file_path))
    if not chunks:
        return 0

    c = conn.cursor()
    now = time.time()

    # Delete old chunks for this file
    c.execute("DELETE FROM chunks WHERE file_path = ?", (str(file_path),))

    # Insert new chunks
    for chunk in chunks:
        c.execute("""
            INSERT INTO chunks (id, file_path, file_name, chunk_index, content, content_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chunk["id"],
            chunk["file_path"],
            chunk["file_name"],
            chunk["chunk_index"],
            chunk["content"],
            chunk["content_hash"],
            now, now
        ))

    # Update file tracking
    stat = file_path.stat()
    c.execute("""
        INSERT OR REPLACE INTO files (path, mtime, size, chunk_count)
        VALUES (?, ?, ?, ?)
    """, (str(file_path), stat.st_mtime, stat.st_size, len(chunks)))

    return len(chunks)


def main():
    print("=" * 60)
    print("Hybrid Codebase Indexer (BM25 + Lazy Embeddings)")
    print("=" * 60)
    print(f"\nDirectories to index:")
    for d in DIRECTORIES:
        print(f"  - {d}")
    print(f"\nDatabase: {DB_PATH}")
    print()

    # Initialize database
    print("Initializing database...")
    conn = init_db()

    # Get existing stats
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM chunks")
    existing_chunks = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM files")
    existing_files = c.fetchone()[0]
    print(f"Existing index: {existing_files} files, {existing_chunks} chunks")

    # Scan for files
    print("\nScanning for files...")
    files = list(get_files(DIRECTORIES))
    print(f"Found {len(files)} indexable files")

    if not files:
        print("No files to index!")
        conn.close()
        return

    # Check which files need updating
    print("\nChecking for changes...")
    files_to_update = []
    for f in files:
        if file_needs_update(conn, f):
            files_to_update.append(f)

    print(f"Files needing update: {len(files_to_update)}")

    if not files_to_update:
        print("\nIndex is up to date!")
        conn.close()
        return

    # Index files
    print(f"\nIndexing {len(files_to_update)} files...")
    start_time = time.time()
    total_chunks = 0
    errors = 0

    for i, file_path in enumerate(files_to_update):
        if i % 100 == 0 or i == len(files_to_update) - 1:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(files_to_update) - i - 1) / rate if rate > 0 else 0
            print(f"\r  [{i+1}/{len(files_to_update)}] {rate:.1f} files/sec, ETA: {eta:.0f}s", end="", flush=True)

        try:
            chunks = index_file(conn, file_path)
            total_chunks += chunks

            # Commit every 500 files for safety
            if i % 500 == 0:
                conn.commit()
        except Exception as e:
            errors += 1
            if errors < 10:
                print(f"\nError indexing {file_path}: {e}")

    conn.commit()

    # Clean up deleted files
    print("\n\nCleaning up deleted files...")
    c = conn.cursor()
    c.execute("SELECT path FROM files")
    indexed_paths = {row[0] for row in c.fetchall()}
    current_paths = {str(f) for f in files}
    deleted_paths = indexed_paths - current_paths

    for path in deleted_paths:
        c.execute("DELETE FROM chunks WHERE file_path = ?", (path,))
        c.execute("DELETE FROM files WHERE path = ?", (path,))

    if deleted_paths:
        print(f"Removed {len(deleted_paths)} deleted files from index")

    conn.commit()

    # Final stats
    c.execute("SELECT COUNT(*) FROM chunks")
    final_chunks = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM files")
    final_files = c.fetchone()[0]

    elapsed = time.time() - start_time
    print("\n")
    print("=" * 60)
    print("Indexing Complete!")
    print("=" * 60)
    print(f"Files indexed: {len(files_to_update)}")
    print(f"Chunks created: {total_chunks}")
    print(f"Errors: {errors}")
    print(f"Time: {elapsed:.1f} seconds ({len(files_to_update)/elapsed:.1f} files/sec)")
    print(f"\nTotal index: {final_files} files, {final_chunks} chunks")
    print(f"Database size: {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB")

    conn.close()


if __name__ == "__main__":
    main()
