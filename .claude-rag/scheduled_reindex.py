#!/usr/bin/env python3
"""
Scheduled Re-indexer for Claude Code RAG
- Fault tolerant: safe interruption at any point
- Incremental: only processes new/changed files
- Lightweight: designed for quick runs between sleep cycles
- Logs progress for debugging
"""

import os
import sys
import sqlite3
import hashlib
import time
import json
import logging
import requests
from pathlib import Path
from datetime import datetime

import subprocess as _subprocess

# Load configuration
CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)

DIRECTORIES = CONFIG["indexing"]["directories"]
DB_PATH = Path(CONFIG["common"]["database_path"])
LOG_PATH = Path(CONFIG["scheduled_reindex"]["log_path"])
LOCK_PATH = Path(CONFIG["scheduled_reindex"]["lock_path"])
MAX_FILES_PER_RUN = CONFIG["scheduled_reindex"]["max_files_per_run"]
MAX_RUNTIME_SECONDS = CONFIG["scheduled_reindex"]["max_runtime_seconds"]
# Reserve minimum time for processing (20% of total time, or at least 10 seconds)
MIN_PROCESSING_TIME_SECONDS = max(10, int(MAX_RUNTIME_SECONDS * 0.2))
BATCH_CHECK_SIZE = CONFIG["scheduled_reindex"].get("batch_check_size", 100)
FAILED_FILE_RETRY_HOURS = CONFIG["scheduled_reindex"].get("failed_file_retry_hours", [1, 2, 4, 8, 16])
MAX_RETRY_COUNT = CONFIG["scheduled_reindex"].get("max_retry_count", 5)
CLEANUP_OLD_FAILURES_DAYS = CONFIG["scheduled_reindex"].get("cleanup_old_failures_days", 30)
INDEXABLE_EXTENSIONS = set(CONFIG["indexing"]["indexable_extensions"])
SKIP_DIRS = set(CONFIG["indexing"]["skip_dirs"])
MAX_FILE_SIZE = CONFIG["indexing"]["max_file_size"]
CHUNK_SIZE = CONFIG["indexing"]["chunk_size"]
CHUNK_OVERLAP = CONFIG["indexing"]["chunk_overlap"]

# Embedding settings
OLLAMA_URL = CONFIG["embedding"]["ollama_url"]
EMBEDDING_MODEL = CONFIG["embedding"]["embedding_model"]
EMBEDDING_BATCH_SIZE = CONFIG["preembed"]["batch_size"]

# Notification settings
NOTIFICATION_APP_ID = "Claude.RAG.Indexer"


def notify_error(title: str, message: str):
    """Show desktop notification for errors (best-effort)."""
    if sys.platform == "darwin":
        try:
            safe_title = title.replace('"', '\\"')
            safe_message = message.replace('"', '\\"')
            _subprocess.run(
                ["osascript", "-e",
                 f'display notification "{safe_message}" with title "{safe_title}"'],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
    # On other platforms, errors are already logged


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
        log.warning(f"Embedding error: {e}")
        return None


def embed_new_chunks(conn: sqlite3.Connection, start_time: float) -> dict:
    """Embed chunks that don't have embeddings yet.

    Returns dict with 'embedded' count and 'errors' count.
    """
    c = conn.cursor()

    # Get unembedded chunks
    c.execute("""
        SELECT id, content FROM chunks
        WHERE embedding IS NULL
        ORDER BY file_path, chunk_index
    """)
    chunks = c.fetchall()
    total = len(chunks)

    if total == 0:
        return {'embedded': 0, 'errors': 0}

    log.info(f"Embedding {total} new chunks...")

    embedded = 0
    errors = 0

    for batch_start in range(0, total, EMBEDDING_BATCH_SIZE):
        # Check time limit
        elapsed = time.time() - start_time
        if elapsed >= MAX_RUNTIME_SECONDS:
            log.info(f"Time limit reached during embedding ({elapsed:.0f}s), stopping")
            break

        batch_end = min(batch_start + EMBEDDING_BATCH_SIZE, total)
        batch = chunks[batch_start:batch_end]

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
        embedded += len(batch)

        if batch_start % (EMBEDDING_BATCH_SIZE * 4) == 0:
            log.info(f"Embedding progress: {batch_start}/{total}")

    return {'embedded': embedded, 'errors': errors}


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


def acquire_lock() -> bool:
    """Try to acquire lock file. Returns False if another instance is running."""
    if LOCK_PATH.exists():
        # Check if lock is stale (older than 10 minutes)
        try:
            lock_age = time.time() - LOCK_PATH.stat().st_mtime
            if lock_age > 600:  # 10 minutes
                log.warning(f"Removing stale lock file (age: {lock_age:.0f}s)")
                LOCK_PATH.unlink()
            else:
                # Check if the process is actually still running
                try:
                    lock_pid = int(LOCK_PATH.read_text().strip())
                    # Try to check if process exists (Windows-compatible)
                    try:
                        import psutil
                        if psutil.pid_exists(lock_pid):
                            log.info(f"Another instance is running (lock age: {lock_age:.0f}s, PID: {lock_pid})")
                            return False
                        else:
                            log.warning(f"Lock file exists but process {lock_pid} is not running, removing stale lock")
                            LOCK_PATH.unlink()
                    except ImportError:
                        # psutil not available, use fallback
                        if lock_age > 300:  # 5 minutes without psutil, be more aggressive
                            log.warning(f"Removing potentially stale lock file (age: {lock_age:.0f}s, PID: {lock_pid})")
                            LOCK_PATH.unlink()
                        else:
                            log.info(f"Another instance may be running (lock age: {lock_age:.0f}s)")
                            return False
                except (ValueError, OSError):
                    # If we can't read PID, assume it's stale if old enough
                    if lock_age > 300:  # 5 minutes
                        log.warning(f"Removing potentially stale lock file (age: {lock_age:.0f}s)")
                        LOCK_PATH.unlink()
                    else:
                        log.info(f"Another instance may be running (lock age: {lock_age:.0f}s)")
                        return False
        except OSError:
            pass

    try:
        LOCK_PATH.write_text(str(os.getpid()))
        return True
    except OSError as e:
        log.error(f"Failed to acquire lock: {e}")
        return False


def release_lock():
    """Release lock file."""
    try:
        if LOCK_PATH.exists():
            LOCK_PATH.unlink()
    except OSError:
        pass


def get_files(time_check_callback=None):
    """
    Get all indexable files.
    
    Args:
        time_check_callback: Optional callback function that returns True if we should
                             stop scanning early. Called periodically during scanning.
    """
    files_yielded = 0
    for directory in DIRECTORIES:
        dir_path = Path(directory)
        if not dir_path.exists():
            continue

        for file_path in dir_path.rglob("*"):
            # Check time limit periodically during scanning (every 100 files)
            if time_check_callback and files_yielded > 0 and files_yielded % 100 == 0:
                if time_check_callback():
                    log.info(f"Time limit approaching during scan, stopping early at {files_yielded} files")
                    return
            
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
            files_yielded += 1


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


def file_needs_update(conn: sqlite3.Connection, file_path: Path) -> bool:
    """Check if file needs re-indexing."""
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


def cleanup_deleted_files(conn: sqlite3.Connection, current_files: set[str]) -> int:
    """Remove entries for deleted files."""
    c = conn.cursor()
    c.execute("SELECT path FROM files")
    indexed_paths = {row[0] for row in c.fetchall()}

    deleted = indexed_paths - current_files
    for path in deleted:
        c.execute("DELETE FROM chunks WHERE file_path = ?", (path,))
        c.execute("DELETE FROM files WHERE path = ?", (path,))
        # Also remove from failed_files if present
        c.execute("DELETE FROM failed_files WHERE path = ?", (path,))

    return len(deleted)


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


def get_failed_files(conn: sqlite3.Connection, max_age_hours: int = 24) -> list[Path]:
    """Get files that failed to index and should be retried."""
    c = conn.cursor()
    
    # Get all failed files (filter by retry logic, not by age)
    c.execute("""
        SELECT path, retry_count, last_attempt 
        FROM failed_files 
        WHERE retry_count < ?
        ORDER BY retry_count ASC, last_attempt ASC
    """, (MAX_RETRY_COUNT,))
    
    failed_files = []
    now = time.time()
    
    for row in c.fetchall():
        path_str, retry_count, last_attempt = row
        
        # Check if enough time has passed for retry based on retry count
        wait_hours = FAILED_FILE_RETRY_HOURS[min(retry_count, len(FAILED_FILE_RETRY_HOURS) - 1)]
        hours_since_attempt = (now - last_attempt) / 3600
        
        if hours_since_attempt >= wait_hours:
            failed_files.append(Path(path_str))
    
    return failed_files


def cleanup_old_failures(conn: sqlite3.Connection, days: int = None):
    """Remove old failed file entries."""
    if days is None:
        days = CLEANUP_OLD_FAILURES_DAYS
    
    c = conn.cursor()
    cutoff_time = time.time() - (days * 24 * 3600)
    
    c.execute("DELETE FROM failed_files WHERE created_at < ?", (cutoff_time,))
    deleted = c.rowcount
    conn.commit()
    
    if deleted > 0:
        log.info(f"Cleaned up {deleted} old failed file entries (older than {days} days)")
    
    return deleted


def remove_failed_file(conn: sqlite3.Connection, file_path: Path):
    """Remove a file from failed_files table (successfully indexed)."""
    c = conn.cursor()
    c.execute("DELETE FROM failed_files WHERE path = ?", (str(file_path),))
    conn.commit()


def check_files_batch(conn: sqlite3.Connection, file_paths: list[Path], batch_size: int = None) -> list[Path]:
    """Check multiple files at once using batch queries."""
    if batch_size is None:
        batch_size = BATCH_CHECK_SIZE
    
    files_needing_update = []
    
    for i in range(0, len(file_paths), batch_size):
        batch = file_paths[i:i+batch_size]
        if not batch:
            break
        
        # Convert to strings for database query
        batch_strs = [str(fp) for fp in batch]
        placeholders = ','.join('?' * len(batch_strs))
        
        # Get database state for batch
        c = conn.cursor()
        c.execute(f"""
            SELECT path, mtime, size 
            FROM files 
            WHERE path IN ({placeholders})
        """, batch_strs)
        
        db_state = {row[0]: (row[1], row[2]) for row in c.fetchall()}
        
        # Compare with filesystem in memory
        for file_path in batch:
            path_str = str(file_path)
            if path_str not in db_state:
                # File not in database - needs indexing
                files_needing_update.append(file_path)
            else:
                try:
                    stat = file_path.stat()
                    db_mtime, db_size = db_state[path_str]
                    if stat.st_mtime != db_mtime or stat.st_size != db_size:
                        files_needing_update.append(file_path)
                except OSError:
                    # File doesn't exist or can't be accessed - skip (don't add to update list)
                    pass
    
    return files_needing_update


def index_file_with_retry(conn: sqlite3.Connection, file_path: Path, failed_queue: list, max_retries: int = 3) -> int:
    """Index file with retry logic for database locks.

    Args:
        conn: Database connection
        file_path: Path to file to index
        failed_queue: List to append failures to (in-memory queue, written later)
        max_retries: Maximum retry attempts

    Returns:
        Number of chunks indexed (0 if file was skipped due to size/content), or -1 if failed
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
                # Don't call track_failed_file here - connection may still be locked
                failed_queue.append((file_path, f"Database locked after {max_retries} retries"))
                return -1
            raise  # Re-raise non-lock errors
        except Exception as e:
            # Other errors - track immediately if possible
            try:
                track_failed_file(conn, file_path, str(e))
            except:
                # If tracking fails, add to queue
                failed_queue.append((file_path, str(e)))
            return -1
    return -1


def flush_failed_queue(conn: sqlite3.Connection, failed_queue: list):
    """Write queued failures to database after locks clear."""
    for file_path, error in failed_queue:
        try:
            track_failed_file(conn, file_path, error)
        except sqlite3.OperationalError:
            log.warning(f"Could not track failure for {file_path}, will retry next run")
    failed_queue.clear()


def prioritize_files(conn: sqlite3.Connection, all_files: list[Path], failed_files: list[Path]) -> list[Path]:
    """Organize files by priority, processing each level completely."""
    # Get set of indexed paths once (avoid repeated queries)
    c = conn.cursor()
    c.execute("SELECT path FROM files")
    indexed_paths = {row[0] for row in c.fetchall()}
    failed_paths = {str(f) for f in failed_files}
    
    # Filter failed files to only include those that actually exist
    # (files may have been deleted since failure)
    valid_failed_files = []
    for failed_file in failed_files:
        if failed_file.exists():
            valid_failed_files.append(failed_file)
        else:
            # File no longer exists, remove from failed_files table
            try:
                remove_failed_file(conn, failed_file)
            except:
                pass  # Ignore errors during cleanup
    
    priority_groups = {
        'failed': valid_failed_files,
        'new': [],
        'modified': []
    }

    # Batch check all files for updates
    files_needing_update = check_files_batch(conn, all_files)
    
    # Update failed_paths to only include valid files
    failed_paths = {str(f) for f in valid_failed_files}

    # Categorize - files_needing_update already passed the needs-update check
    for file_path in files_needing_update:
        path_str = str(file_path)
        if path_str in failed_paths:
            continue  # Already in failed priority group
        elif path_str not in indexed_paths:
            priority_groups['new'].append(file_path)
        else:
            # It's in the DB but changed (mtime/size mismatch)
            priority_groups['modified'].append(file_path)

    # Return as flat list: failed first, then new, then modified
    return (priority_groups['failed'] +
            priority_groups['new'] +
            priority_groups['modified'])


def run_reindex(conn: sqlite3.Connection, start_time: float) -> dict:
    """
    Run the re-indexing process.
    
    Args:
        conn: Database connection
        start_time: Start time of the re-indexing process
        
    Returns:
        Dictionary with stats: {
            'processed': int,
            'chunks_added': int,
            'errors': int,
            'deleted': int,
            'initial_files': int,
            'initial_chunks': int,
            'final_files': int,
            'final_chunks': int
        }
    """
    # Get current stats
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM files")
    initial_files = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM chunks")
    initial_chunks = c.fetchone()[0]

    log.info(f"Current index: {initial_files} files, {initial_chunks} chunks")

    # Cleanup old failures first
    cleanup_old_failures(conn)
    
    # Get failed files that should be retried
    failed_files = get_failed_files(conn)
    log.info(f"Found {len(failed_files)} failed files to retry")

    # Calculate maximum time we can spend on scanning
    # Reserve minimum processing time to ensure files actually get processed
    max_scan_time = MAX_RUNTIME_SECONDS - MIN_PROCESSING_TIME_SECONDS
    log.info(f"Time budget: {MAX_RUNTIME_SECONDS}s total, {MIN_PROCESSING_TIME_SECONDS}s reserved for processing")

    # Scan for files with time limit checking
    log.info("Scanning for files...")
    scan_start_time = time.time()
    scan_stopped_early = False
    
    def should_stop_scanning():
        """Check if we should stop scanning early to reserve time for processing."""
        elapsed = time.time() - scan_start_time
        if elapsed >= max_scan_time:
            nonlocal scan_stopped_early
            scan_stopped_early = True
            return True
        return False
    
    all_files = list(get_files(time_check_callback=should_stop_scanning))
    scan_time = time.time() - scan_start_time
    elapsed_total = time.time() - start_time
    current_paths = {str(f) for f in all_files}
    
    # Track if scan was complete (not stopped early)
    scan_complete = not scan_stopped_early
    
    log.info(f"Found {len(all_files)} indexable files (scan took {scan_time:.1f}s, {'complete' if scan_complete else 'stopped early'})")

    # Calculate deadline AFTER scanning completes
    # This fixes the bug where deadline was calculated before scanning, causing immediate stop
    # Deadline is relative time from start: when we must stop to reserve processing time
    file_check_deadline_relative = MAX_RUNTIME_SECONDS - MIN_PROCESSING_TIME_SECONDS
    time_remaining = MAX_RUNTIME_SECONDS - elapsed_total
    
    # Check if we've already exceeded the deadline
    if elapsed_total >= file_check_deadline_relative:
        log.warning(f"Time limit reached before file checking started ({elapsed_total:.1f}s elapsed, deadline {file_check_deadline_relative:.1f}s from start)")
        # Still try to check at least some files if we have any time left
        if time_remaining <= 0:
            log.warning("No time remaining for file checking or processing")
            return {
                'processed': 0,
                'chunks_added': 0,
                'errors': 0,
                'deleted': 0,
                'initial_files': initial_files,
                'initial_chunks': initial_chunks,
                'final_files': initial_files,
                'final_chunks': initial_chunks
            }

    # Prioritize files: failed first, then new, then modified
    log.info("Prioritizing files...")
    prioritized_files = prioritize_files(conn, all_files, failed_files)
    failed_paths_set = {str(ff) for ff in failed_files}
    failed_count = len([f for f in prioritized_files if str(f) in failed_paths_set])
    log.info(f"Prioritized: {failed_count} failed, {len(prioritized_files) - failed_count} other files needing update")

    # Limit to max_files_per_run
    files_to_update = prioritized_files[:MAX_FILES_PER_RUN]
    log.info(f"Files to process: {len(files_to_update)} (max {MAX_FILES_PER_RUN} per run)")

    # Process files with retry logic
    processed = 0
    chunks_added = 0
    skipped = 0
    errors = 0
    failed_queue = []  # Queue for failures that can't be tracked immediately (due to locks)

    for file_path in files_to_update:
        # Check time limit before processing each file
        elapsed = time.time() - start_time
        if elapsed >= MAX_RUNTIME_SECONDS:
            log.info(f"Time limit reached ({elapsed:.0f}s), stopping gracefully")
            break

        chunks = index_file_with_retry(conn, file_path, failed_queue)
        if chunks > 0:
            chunks_added += chunks
            processed += 1
        elif chunks == 0:
            skipped += 1  # File too small or no indexable content
        else:
            errors += 1  # Actual failure (chunks == -1)

        # Commit frequently for fault tolerance
        if processed > 0 and processed % 50 == 0:
            conn.commit()
            log.info(f"Progress: {processed}/{len(files_to_update)} files")
            # Flush failed queue periodically
            if failed_queue:
                flush_failed_queue(conn, failed_queue)

    conn.commit()
    
    # Flush any remaining failed queue items
    if failed_queue:
        flush_failed_queue(conn, failed_queue)

    # Cleanup deleted files (only if scan was complete and we have time)
    elapsed = time.time() - start_time
    deleted = 0
    if scan_complete and elapsed < MAX_RUNTIME_SECONDS - 10:
        deleted = cleanup_deleted_files(conn, current_paths)
        conn.commit()
        if deleted > 0:
            log.info(f"Cleaned up {deleted} deleted files")
    elif not scan_complete:
        log.info(f"Skipping cleanup - scan was incomplete ({len(all_files)} files scanned, may be more)")
    else:
        log.info(f"Skipping cleanup - insufficient time remaining ({elapsed:.1f}s elapsed, {MAX_RUNTIME_SECONDS - elapsed:.1f}s remaining)")

    # Final stats
    c.execute("SELECT COUNT(*) FROM files")
    final_files = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM chunks")
    final_chunks = c.fetchone()[0]

    return {
        'processed': processed,
        'chunks_added': chunks_added,
        'skipped': skipped,
        'errors': errors,
        'deleted': deleted,
        'initial_files': initial_files,
        'initial_chunks': initial_chunks,
        'final_files': final_files,
        'final_chunks': final_chunks
    }


def main():
    start_time = time.time()
    log.info("=" * 50)
    log.info("Scheduled re-index starting")

    # Check database exists
    if not DB_PATH.exists():
        log.error(f"Database not found: {DB_PATH}")
        log.error("Run hybrid_indexer.py first to create the initial index")
        sys.exit(1)

    # Acquire lock
    if not acquire_lock():
        log.info("Exiting - another instance is running")
        sys.exit(0)

    conn = None
    try:
        # Use WAL mode for better concurrency and add timeout
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        
        # Run the re-indexing process
        stats = run_reindex(conn, start_time)

        elapsed = time.time() - start_time
        log.info(f"Indexing completed in {elapsed:.1f}s")
        log.info(f"Processed: {stats['processed']} files, {stats['chunks_added']} chunks, {stats['skipped']} skipped, {stats['errors']} errors")
        log.info(f"Final index: {stats['final_files']} files, {stats['final_chunks']} chunks")

        # Embed any chunks without embeddings
        embed_stats = embed_new_chunks(conn, start_time)
        if embed_stats['embedded'] > 0 or embed_stats['errors'] > 0:
            log.info(f"Embedding: {embed_stats['embedded']} embedded, {embed_stats['errors']} errors")

        if conn:
            conn.close()

        # Notify if there were significant errors (>10 files failed)
        if stats['errors'] > 10:
            notify_error(
                "⚠️ Claude RAG - Reindex Warning",
                f"Re-indexing completed with {stats['errors']} errors.\nSome files may not be searchable."
            )

    except KeyboardInterrupt:
        log.warning("Re-index interrupted by user")
        if conn:
            conn.close()
    except Exception as e:
        log.error(f"Fatal error: {e}")
        import traceback
        log.error(traceback.format_exc())
        if conn:
            try:
                conn.close()
            except:
                pass
    finally:
        # Always release lock, even if process is killed
        try:
            release_lock()
        except Exception as e:
            log.error(f"Error releasing lock: {e}")

    log.info("Re-index complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error(f"Script failed: {e}")
        notify_error(
            "⛔ Claude RAG - Reindex Failed",
            f"Scheduled re-indexing failed: {str(e)[:100]}\nCheck reindex.log for details."
        )
