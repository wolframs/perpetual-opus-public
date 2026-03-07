#!/usr/bin/env python3
"""
Single-repo re-indexer for Claude Code RAG
Called by git post-checkout hook to re-index a specific repo after branch switch.
Includes debouncing to prevent multiple instances from running simultaneously.
"""

import os
import sys
import sqlite3
import hashlib
import time
import json
import logging
from pathlib import Path

# Load configuration
CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)

DB_PATH = Path(CONFIG["common"]["database_path"])
LOG_PATH = Path(CONFIG["scheduled_reindex"]["log_path"])
DEBOUNCE_DIR = Path(__file__).parent / ".debounce"
DEBOUNCE_SECONDS = 30  # Skip if another reindex started within this window
MAX_RETRY_COUNT = CONFIG["scheduled_reindex"].get("max_retry_count", 5)
FAILED_FILE_RETRY_HOURS = CONFIG["scheduled_reindex"].get("failed_file_retry_hours", [1, 2, 4, 8, 16])
INDEXABLE_EXTENSIONS = set(CONFIG["indexing"]["indexable_extensions"])
SKIP_DIRS = set(CONFIG["indexing"]["skip_dirs"])
MAX_FILE_SIZE = CONFIG["indexing"]["max_file_size"]
CHUNK_SIZE = CONFIG["indexing"]["chunk_size"]
CHUNK_OVERLAP = CONFIG["indexing"]["chunk_overlap"]

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH, encoding='utf-8'),
    ]
)
log = logging.getLogger(__name__)


def get_repo_files(repo_path: Path):
    """Get all indexable files in a repo."""
    for file_path in repo_path.rglob("*"):
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
    """Safely read a file."""
    for encoding in ["utf-8", "utf-8-sig", "latin-1", "cp1252"]:
        try:
            return file_path.read_text(encoding=encoding)
        except (UnicodeDecodeError, OSError):
            continue
    return None


def chunk_text(text: str, file_path: str) -> list[dict]:
    """Split text into chunks."""
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


def index_file(conn: sqlite3.Connection, file_path: Path) -> int:
    """Index a single file."""
    content = read_file_safe(file_path)
    if content is None:
        # Can't read file - don't track it (might be binary or locked)
        return 0

    c = conn.cursor()
    now = time.time()
    stat = file_path.stat()

    chunks = chunk_text(content, str(file_path))

    # Delete old chunks (if any)
    c.execute("DELETE FROM chunks WHERE file_path = ?", (str(file_path),))

    # Insert new chunks (if any)
    for chunk in chunks:
        c.execute("""
            INSERT INTO chunks (id, file_path, file_name, chunk_index, content, content_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chunk["id"], chunk["file_path"], chunk["file_name"], chunk["chunk_index"],
            chunk["content"], chunk["content_hash"], now, now
        ))

    # Always track the file (even with 0 chunks) to prevent re-processing
    c.execute("""
        INSERT OR REPLACE INTO files (path, mtime, size, chunk_count)
        VALUES (?, ?, ?, ?)
    """, (str(file_path), stat.st_mtime, stat.st_size, len(chunks)))

    return len(chunks)


def track_failed_file(conn: sqlite3.Connection, file_path: Path, error: str):
    """Record a file that failed to index."""
    c = conn.cursor()
    now = time.time()
    
    # Check if already exists
    c.execute("SELECT retry_count, created_at FROM failed_files WHERE path = ?", (str(file_path),))
    row = c.fetchone()
    
    if row:
        # Increment retry count
        retry_count = row[0] + 1
        created_at = row[1]
        c.execute("""
            UPDATE failed_files 
            SET error = ?, retry_count = ?, last_attempt = ?
            WHERE path = ?
        """, (error, retry_count, now, str(file_path)))
    else:
        # New failure
        c.execute("""
            INSERT INTO failed_files (path, error, retry_count, last_attempt, created_at)
            VALUES (?, ?, 0, ?, ?)
        """, (str(file_path), error, now, now))
    
    conn.commit()


def remove_failed_file(conn: sqlite3.Connection, file_path: Path):
    """Remove a file from failed_files table (successfully indexed)."""
    c = conn.cursor()
    c.execute("DELETE FROM failed_files WHERE path = ?", (str(file_path),))
    conn.commit()


def index_file_with_retry(conn: sqlite3.Connection, file_path: Path, failed_queue: list, max_retries: int = 3) -> int:
    """Index file with retry logic for database locks.
    
    Args:
        conn: Database connection
        file_path: Path to file to index
        failed_queue: List to append failures to (in-memory queue, written later)
        max_retries: Maximum retry attempts
        
    Returns:
        Number of chunks indexed, or 0 if failed
    """
    for attempt in range(max_retries):
        try:
            chunks = index_file(conn, file_path)
            # Success - remove from failed_files if present
            remove_failed_file(conn, file_path)
            return chunks
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower():
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    log.debug(f"Database locked for {file_path}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                # Max retries exceeded, queue for later tracking
                failed_queue.append((file_path, f"Database locked after {max_retries} retries"))
                return 0
            raise  # Re-raise non-lock errors
        except Exception as e:
            # Other errors - track immediately if possible
            try:
                track_failed_file(conn, file_path, str(e))
            except:
                # If tracking fails, add to queue
                failed_queue.append((file_path, str(e)))
            return 0
    return 0


def flush_failed_queue(conn: sqlite3.Connection, failed_queue: list):
    """Write queued failures to database after locks clear."""
    for file_path, error in failed_queue:
        try:
            track_failed_file(conn, file_path, error)
        except sqlite3.OperationalError:
            log.warning(f"Could not track failure for {file_path}, will retry next run")
    failed_queue.clear()


def get_debounce_file(repo_path: Path) -> Path:
    """Get the debounce lock file path for a repo."""
    # Use hash of repo path to create unique filename
    repo_hash = hashlib.md5(str(repo_path).lower().encode()).hexdigest()[:12]
    return DEBOUNCE_DIR / f"reindex_{repo_hash}.lock"


def check_debounce(repo_path: Path) -> bool:
    """
    Check if we should skip this reindex due to debouncing.

    Returns:
        True if we should proceed, False if we should skip (debounced)
    """
    DEBOUNCE_DIR.mkdir(exist_ok=True)
    debounce_file = get_debounce_file(repo_path)

    now = time.time()

    if debounce_file.exists():
        try:
            # Read last reindex time and PID
            content = debounce_file.read_text().strip().split('\n')
            last_time = float(content[0])
            last_pid = int(content[1]) if len(content) > 1 else 0

            age = now - last_time

            # If recent reindex is still running or just finished, skip
            if age < DEBOUNCE_SECONDS:
                # Check if the process is still running
                try:
                    import psutil
                    if psutil.pid_exists(last_pid):
                        log.info(f"Debounced: reindex for {repo_path.name} already running (PID {last_pid}, started {age:.0f}s ago)")
                        return False
                except ImportError:
                    pass

                log.info(f"Debounced: reindex for {repo_path.name} completed {age:.0f}s ago (< {DEBOUNCE_SECONDS}s)")
                return False
        except (ValueError, OSError):
            pass  # Corrupted file, proceed anyway

    # Write our timestamp and PID
    try:
        debounce_file.write_text(f"{now}\n{os.getpid()}")
    except OSError:
        pass  # Best effort

    return True


def clear_debounce(repo_path: Path):
    """Update debounce file to mark completion (keeps timestamp for debouncing)."""
    debounce_file = get_debounce_file(repo_path)
    try:
        # Update timestamp to now (marks completion time for debouncing)
        debounce_file.write_text(f"{time.time()}\n0")
    except OSError:
        pass


def main():
    if len(sys.argv) < 2:
        print("Usage: reindex_repo.py <repo_path>")
        sys.exit(1)

    repo_path = Path(sys.argv[1]).resolve()

    if not repo_path.exists():
        log.error(f"Repo path does not exist: {repo_path}")
        sys.exit(1)

    # Check debouncing - skip if recent reindex already happened
    if not check_debounce(repo_path):
        sys.exit(0)  # Silent exit, already logged

    start_time = time.time()
    log.info("=" * 50)
    log.info(f"Git hook re-index: {repo_path}")

    if not DB_PATH.exists():
        log.error(f"Database not found: {DB_PATH}")
        sys.exit(1)

    # Use WAL mode and timeout for better concurrency
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")

    # Get files in repo
    files = list(get_repo_files(repo_path))
    log.info(f"Found {len(files)} indexable files in repo")

    # Helper function to track failed files (simple version for git hook)
    def track_failed_file_simple(conn, file_path, error):
        """Record a failed file indexing attempt."""
        try:
            c = conn.cursor()
            now = time.time()
            c.execute("""
                INSERT OR REPLACE INTO failed_files (path, error, retry_count, last_attempt, created_at)
                VALUES (?, ?, COALESCE((SELECT retry_count FROM failed_files WHERE path = ?), 0), ?, COALESCE((SELECT created_at FROM failed_files WHERE path = ?), ?))
            """, (str(file_path), str(error), str(file_path), now, str(file_path), now))
            conn.commit()
        except Exception:
            pass  # Best effort - don't fail the whole process
    
    def remove_failed_file_simple(conn, file_path):
        """Remove a file from failed_files table (on successful indexing)."""
        try:
            c = conn.cursor()
            c.execute("DELETE FROM failed_files WHERE path = ?", (str(file_path),))
            conn.commit()
        except Exception:
            pass  # Best effort

    # Re-index all files in repo (branch switch = assume all changed)
    processed = 0
    chunks_added = 0
    errors = 0

    for file_path in files:
        try:
            chunks = index_file(conn, file_path)
            if chunks > 0:
                chunks_added += chunks
                processed += 1
                # Remove from failed_files if it was there
                remove_failed_file_simple(conn, file_path)

            # Commit in batches
            if processed % 100 == 0:
                conn.commit()
        except Exception as e:
            errors += 1
            log.warning(f"Error indexing {file_path}: {e}")
            # Track the failure
            track_failed_file_simple(conn, file_path, str(e))

    conn.commit()
    conn.close()

    # Update debounce timestamp to mark completion
    clear_debounce(repo_path)

    elapsed = time.time() - start_time
    log.info(f"Completed in {elapsed:.1f}s: {processed} files, {chunks_added} chunks, {errors} errors")


if __name__ == "__main__":
    main()
