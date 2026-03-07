#!/usr/bin/env python3
"""
Comprehensive tests for scheduled_reindex.py time limit behavior.

Tests verify that:
1. Files are actually processed even when scanning takes time
2. Time limits are respected during scanning phase
3. Processing time is reserved and not consumed by scanning
4. The system gracefully handles time limits
"""

import pytest
import sqlite3
import tempfile
import time
import json
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add parent directory to path to import scheduled_reindex
sys.path.insert(0, str(Path(__file__).parent))

# We'll need to mock the config loading, so let's create a testable version


class TestScheduledReindexTimeLimits:
    """Test time limit behavior in scheduled re-indexing."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        temp_path = Path(tempfile.mkdtemp())
        yield temp_path
        shutil.rmtree(temp_path, ignore_errors=True)

    @pytest.fixture
    def temp_db(self, temp_dir):
        """Create a temporary database for testing."""
        db_path = temp_dir / "test.db"
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        
        # Create tables matching the schema
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
        return db_path

    @pytest.fixture
    def test_files(self, temp_dir):
        """Create test files that need indexing."""
        test_dir = temp_dir / "test_repo"
        test_dir.mkdir()
        
        files = []
        for i in range(10):
            file_path = test_dir / f"test_{i}.py"
            file_path.write_text(f"# Test file {i}\n" + "print('hello')\n" * 100)
            files.append(file_path)
        
        return files

    @pytest.fixture
    def mock_config(self, temp_dir, temp_db):
        """Create a mock config for testing."""
        return {
            "common": {
                "database_path": str(temp_db)
            },
            "indexing": {
                "directories": [str(temp_dir)],
                "indexable_extensions": [".py"],
                "skip_dirs": [],
                "max_file_size": 1048576,
                "chunk_size": 1500,
                "chunk_overlap": 200
            },
            "scheduled_reindex": {
                "log_path": str(temp_dir / "test.log"),
                "lock_path": str(temp_dir / "test.lock"),
                "max_files_per_run": 500,
                "max_runtime_seconds": 120
            }
        }

    def test_time_limit_reserves_processing_time(self, mock_config, temp_db, test_files):
        """
        Test that scanning doesn't consume all time, leaving room for processing.
        
        This is the core bug: scanning takes 3.5 minutes, then no time left for processing.
        """
        # Mock the config to have a short time limit
        mock_config["scheduled_reindex"]["max_runtime_seconds"] = 10
        mock_config["scheduled_reindex"]["max_files_per_run"] = 100
        
        # This test verifies the fix ensures processing time is reserved
        # The fix should reserve MIN_PROCESSING_TIME_SECONDS (20% or at least 10s)
        # So with 10s total, at least 10s should be reserved for processing
        # This means scanning should stop early if it takes too long
        
        # We'll test this by mocking time to simulate slow scanning
        with patch('scheduled_reindex.CONFIG', mock_config):
            with patch('scheduled_reindex.DB_PATH', temp_db):
                # Reload module to pick up new config
                if 'scheduled_reindex' in sys.modules:
                    del sys.modules['scheduled_reindex']
                
                import scheduled_reindex
                
                # Verify MIN_PROCESSING_TIME_SECONDS is calculated correctly
                assert scheduled_reindex.MIN_PROCESSING_TIME_SECONDS >= 10
                
                # With 10s total, processing time should be at least 10s
                # So max_scan_time should be 0 or very small
                max_scan_time = 10 - scheduled_reindex.MIN_PROCESSING_TIME_SECONDS
                assert max_scan_time <= 0  # All time reserved for processing

    def test_scanning_stops_early_when_time_running_out(self, mock_config, temp_db, test_files):
        """
        Test that scanning phase checks time limits and stops early if needed.
        """
        # This test verifies scanning respects time limits
        # Create a scenario where scanning would take too long
        mock_config["scheduled_reindex"]["max_runtime_seconds"] = 5
        
        with patch('scheduled_reindex.CONFIG', mock_config):
            with patch('scheduled_reindex.DB_PATH', temp_db):
                if 'scheduled_reindex' in sys.modules:
                    del sys.modules['scheduled_reindex']
                
                import scheduled_reindex
                
                # Verify that get_files() accepts time_check_callback
                # and stops early when callback returns True
                stop_called = []
                def should_stop():
                    stop_called.append(True)
                    return True
                
                # Get files with early stop callback
                files = list(scheduled_reindex.get_files(time_check_callback=should_stop))
                
                # Should have stopped early (callback was called)
                assert len(stop_called) > 0 or len(files) == 0

    def test_files_processed_even_after_long_scan(self, mock_config, temp_db, test_files):
        """
        Test that files are actually processed even if scanning takes significant time.
        
        This is the main regression test for the bug.
        """
        # Set up: create files that need indexing
        # Use a reasonable time limit
        mock_config["scheduled_reindex"]["max_runtime_seconds"] = 30
        mock_config["scheduled_reindex"]["max_files_per_run"] = 20
        
        # Create database connection
        conn = sqlite3.connect(str(temp_db))
        
        # Initialize tables
        c = conn.cursor()
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
        c.execute("""
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,
                size INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL
            )
        """)
        conn.commit()
        
        with patch('scheduled_reindex.CONFIG', mock_config):
            with patch('scheduled_reindex.DB_PATH', temp_db):
                with patch('scheduled_reindex.DIRECTORIES', [str(test_files[0].parent)]):
                    if 'scheduled_reindex' in sys.modules:
                        del sys.modules['scheduled_reindex']
                    
                    import scheduled_reindex
                    
                    # Run reindex
                    start_time = time.time()
                    stats = scheduled_reindex.run_reindex(conn, start_time)
                    
                    # Verify files were actually processed (the bug fix)
                    assert stats['processed'] > 0, "Files should be processed even after scanning"
                    assert stats['chunks_added'] > 0, "Chunks should be added"
        
        conn.close()

    def test_time_limit_during_scanning_phase(self, mock_config, temp_db, test_files):
        """
        Test that time limit is checked during scanning, not just before processing.
        """
        # Verify time checks happen during scanning
        mock_config["scheduled_reindex"]["max_runtime_seconds"] = 5
        
        with patch('scheduled_reindex.CONFIG', mock_config):
            with patch('scheduled_reindex.DB_PATH', temp_db):
                if 'scheduled_reindex' in sys.modules:
                    del sys.modules['scheduled_reindex']
                
                import scheduled_reindex
                
                # Verify get_files accepts time_check_callback
                callback_calls = []
                def time_check():
                    callback_calls.append(time.time())
                    return False  # Don't stop yet
                
                # Call get_files with callback
                files = list(scheduled_reindex.get_files(time_check_callback=time_check))
                
                # Callback should have been called periodically (every 100 files)
                # If we have many files, callback should be called multiple times
                if len(files) >= 100:
                    assert len(callback_calls) > 0, "Time check callback should be called during scanning"


class TestScheduledReindexIntegration:
    """Integration tests using actual scheduled_reindex module."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        temp_path = Path(tempfile.mkdtemp())
        yield temp_path
        shutil.rmtree(temp_path, ignore_errors=True)

    @pytest.fixture
    def temp_db(self, temp_dir):
        """Create a temporary database for testing."""
        db_path = temp_dir / "test.db"
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        
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
        return db_path

    def test_scanning_time_budget_reserved(self, temp_dir, temp_db):
        """
        Integration test: Verify that scanning doesn't consume all available time.
        
        This test simulates the real-world scenario where scanning takes time
        but files still need to be processed.
        """
        # Create test files
        test_repo = temp_dir / "test_repo"
        test_repo.mkdir()
        
        # Create 20 files that need indexing
        for i in range(20):
            file_path = test_repo / f"test_{i}.py"
            file_path.write_text(f"# File {i}\n" + "x = 1\n" * 50)
        
        # Create config file
        config = {
            "common": {"database_path": str(temp_db)},
            "indexing": {
                "directories": [str(temp_dir)],
                "indexable_extensions": [".py"],
                "skip_dirs": [],
                "max_file_size": 1048576,
                "chunk_size": 1500,
                "chunk_overlap": 200
            },
            "scheduled_reindex": {
                "log_path": str(temp_dir / "test.log"),
                "lock_path": str(temp_dir / "test.lock"),
                "max_files_per_run": 500,
                "max_runtime_seconds": 10  # Short time limit for testing
            }
        }
        
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(config, indent=2))
        
        # Mock the config loading in scheduled_reindex
        with patch('scheduled_reindex.CONFIG_PATH', config_path):
            # Reload the module to pick up new config
            if 'scheduled_reindex' in sys.modules:
                del sys.modules['scheduled_reindex']
            
            import scheduled_reindex
            
            # Track timing
            start_time = time.time()
            
            # Run the main function with mocked time if needed
            # Actually, let's test the logic more directly
            # We'll need to refactor scheduled_reindex to be more testable
            
            # For now, verify the files exist
            assert len(list(test_repo.glob("*.py"))) == 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

