#!/usr/bin/env python3
"""
Tests for failed file tracking functionality.
"""

import pytest
import sqlite3
import tempfile
import time
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import after path setup
import scheduled_reindex


class TestFailedFileTracking:
    """Test failed file tracking functions."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database."""
        temp_dir = Path(tempfile.mkdtemp())
        db_path = temp_dir / "test.db"
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        
        # Create tables
        c.execute("""
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,
                size INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL
            )
        """)
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
        conn.close()
        
        yield db_path
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_track_failed_file(self, temp_db):
        """Test tracking a failed file."""
        conn = sqlite3.connect(str(temp_db))
        file_path = Path("/test/file.py")
        
        scheduled_reindex.track_failed_file(conn, file_path, "Test error")
        
        c = conn.cursor()
        c.execute("SELECT error, retry_count FROM failed_files WHERE path = ?", (str(file_path),))
        row = c.fetchone()
        
        assert row is not None
        assert row[0] == "Test error"
        assert row[1] == 0
        
        conn.close()

    def test_track_failed_file_increment_retry(self, temp_db):
        """Test that retry count increments on subsequent failures."""
        conn = sqlite3.connect(str(temp_db))
        file_path = Path("/test/file.py")
        
        scheduled_reindex.track_failed_file(conn, file_path, "Error 1")
        scheduled_reindex.track_failed_file(conn, file_path, "Error 2")
        scheduled_reindex.track_failed_file(conn, file_path, "Error 3")
        
        c = conn.cursor()
        c.execute("SELECT retry_count FROM failed_files WHERE path = ?", (str(file_path),))
        row = c.fetchone()
        
        assert row[0] == 2  # Started at 0, incremented twice
        
        conn.close()

    def test_get_failed_files(self, temp_db):
        """Test retrieving failed files."""
        conn = sqlite3.connect(str(temp_db))
        
        # Add some failed files
        now = time.time()
        file1 = Path("/test/file1.py")
        file2 = Path("/test/file2.py")
        
        scheduled_reindex.track_failed_file(conn, file1, "Error 1")
        scheduled_reindex.track_failed_file(conn, file2, "Error 2")
        
        # Get failed files
        failed = scheduled_reindex.get_failed_files(conn)
        
        assert len(failed) == 2
        assert file1 in failed
        assert file2 in failed
        
        conn.close()

    def test_remove_failed_file(self, temp_db):
        """Test removing a file from failed_files."""
        conn = sqlite3.connect(str(temp_db))
        file_path = Path("/test/file.py")
        
        scheduled_reindex.track_failed_file(conn, file_path, "Error")
        scheduled_reindex.remove_failed_file(conn, file_path)
        
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM failed_files WHERE path = ?", (str(file_path),))
        count = c.fetchone()[0]
        
        assert count == 0
        
        conn.close()


class TestBatchChecking:
    """Test batch file checking functionality."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database."""
        temp_dir = Path(tempfile.mkdtemp())
        db_path = temp_dir / "test.db"
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,
                size INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        
        yield db_path
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def test_files(self, temp_db):
        """Create test files."""
        temp_dir = Path(tempfile.mkdtemp())
        files = []
        for i in range(10):
            file_path = temp_dir / f"test_{i}.py"
            file_path.write_text(f"# Test {i}\n")
            files.append(file_path)
        
        yield files
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_batch_checking_new_files(self, temp_db, test_files):
        """Test batch checking identifies new files."""
        conn = sqlite3.connect(str(temp_db))
        
        # Batch check files (none in database)
        needing_update = scheduled_reindex.check_files_batch(conn, test_files)
        
        assert len(needing_update) == len(test_files)
        
        conn.close()

    def test_batch_checking_existing_files(self, temp_db, test_files):
        """Test batch checking skips files that are up to date."""
        conn = sqlite3.connect(str(temp_db))
        c = conn.cursor()
        
        # Add some files to database
        for file_path in test_files[:5]:
            stat = file_path.stat()
            c.execute("""
                INSERT INTO files (path, mtime, size, chunk_count)
                VALUES (?, ?, ?, ?)
            """, (str(file_path), stat.st_mtime, stat.st_size, 1))
        conn.commit()
        
        # Batch check - should only return files not in DB or changed
        needing_update = scheduled_reindex.check_files_batch(conn, test_files)
        
        # 5 files in DB (unchanged), 5 new files
        assert len(needing_update) == 5
        
        conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


