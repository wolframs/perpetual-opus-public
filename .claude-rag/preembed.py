#!/usr/bin/env python3
"""
Pre-embed priority folders for faster semantic search.
Run after hybrid_indexer.py to pre-compute embeddings for important directories.
"""

import sqlite3
import requests
import json
import time
import sys
from pathlib import Path

# Load configuration
CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)

DB_PATH = Path(CONFIG["common"]["database_path"])
OLLAMA_URL = CONFIG["embedding"]["ollama_url"]
EMBEDDING_MODEL = CONFIG["embedding"]["embedding_model"]
BATCH_SIZE = CONFIG["preembed"]["batch_size"]
PRIORITY_FOLDERS = CONFIG["preembed"]["priority_folders"]


def get_embeddings_batch(texts: list[str]) -> list[list[float]] | None:
    """Get embeddings for a batch of texts from Ollama."""
    try:
        truncated = [t[:8000] for t in texts]
        response = requests.post(
            OLLAMA_URL,
            json={"input": truncated, "model": EMBEDDING_MODEL},
            timeout=300,
        )
        response.raise_for_status()
        return response.json()["embeddings"]
    except Exception as e:
        print(f"\nEmbedding error: {e}")
        return None


def preembed_folder(conn: sqlite3.Connection, folder_pattern: str) -> tuple[int, int]:
    """Pre-embed all chunks matching a folder pattern. Returns (success, errors)."""
    c = conn.cursor()

    # Get chunks without embeddings for this folder
    c.execute("""
        SELECT id, content FROM chunks
        WHERE file_path LIKE ? AND embedding IS NULL
        ORDER BY file_path, chunk_index
    """, (f"%{folder_pattern}%",))

    chunks = c.fetchall()
    total = len(chunks)

    if total == 0:
        return 0, 0

    print(f"\n  Found {total} chunks to embed for '{folder_pattern}'")

    success = 0
    errors = 0
    start_time = time.time()

    for batch_start in range(0, total, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, total)
        batch = chunks[batch_start:batch_end]

        # Progress
        elapsed = time.time() - start_time
        rate = success / elapsed if elapsed > 0 else 0
        eta = (total - batch_start) / rate if rate > 0 else 0
        print(f"\r  [{batch_start}/{total}] {rate:.1f} chunks/sec, ETA: {eta/60:.1f}min", end="", flush=True)

        # Get embeddings
        ids = [row[0] for row in batch]
        texts = [row[1] for row in batch]
        embeddings = get_embeddings_batch(texts)

        if embeddings is None:
            errors += len(batch)
            continue

        # Store embeddings
        now = time.time()
        for chunk_id, embedding in zip(ids, embeddings):
            c.execute(
                "UPDATE chunks SET embedding = ?, updated_at = ? WHERE id = ?",
                (json.dumps(embedding), now, chunk_id)
            )

        conn.commit()
        success += len(batch)

    print()
    return success, errors


def main():
    # Parse command line arguments for additional folders
    folders = PRIORITY_FOLDERS.copy()
    if len(sys.argv) > 1:
        folders = sys.argv[1:]

    print("=" * 60)
    print("Pre-embedding Priority Folders")
    print("=" * 60)
    print(f"\nFolders to pre-embed:")
    for f in folders:
        print(f"  - {f}")
    print(f"\nBatch size: {BATCH_SIZE}")
    print()

    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Show current stats
    c.execute("SELECT COUNT(*) FROM chunks")
    total_chunks = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL")
    embedded_chunks = c.fetchone()[0]
    print(f"Current embedding coverage: {embedded_chunks}/{total_chunks} ({embedded_chunks/total_chunks*100:.1f}%)")

    # Test Ollama
    print("\nTesting Ollama...")
    test = get_embeddings_batch(["test"])
    if test is None:
        print("Error: Cannot connect to Ollama. Make sure it's running.")
        sys.exit(1)
    print(f"Connected. Embedding dimension: {len(test[0])}")

    # Pre-embed each folder
    total_success = 0
    total_errors = 0
    start_time = time.time()

    for folder in folders:
        print(f"\nProcessing: {folder}")

        # Count chunks for this folder
        c.execute("SELECT COUNT(*) FROM chunks WHERE file_path LIKE ?", (f"%{folder}%",))
        folder_total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM chunks WHERE file_path LIKE ? AND embedding IS NOT NULL", (f"%{folder}%",))
        folder_embedded = c.fetchone()[0]

        print(f"  Total chunks: {folder_total}, Already embedded: {folder_embedded}")

        if folder_total == folder_embedded:
            print(f"  Already fully embedded!")
            continue

        success, errors = preembed_folder(conn, folder)
        total_success += success
        total_errors += errors

    # Final stats
    elapsed = time.time() - start_time
    c.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL")
    final_embedded = c.fetchone()[0]

    print("\n")
    print("=" * 60)
    print("Pre-embedding Complete!")
    print("=" * 60)
    print(f"Chunks embedded: {total_success}")
    print(f"Errors: {total_errors}")
    print(f"Time: {elapsed/60:.1f} minutes")
    print(f"\nTotal embedding coverage: {final_embedded}/{total_chunks} ({final_embedded/total_chunks*100:.1f}%)")

    conn.close()


if __name__ == "__main__":
    main()
