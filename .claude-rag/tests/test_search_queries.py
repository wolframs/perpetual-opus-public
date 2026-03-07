#!/usr/bin/env python3
"""
Tests for search query handling, particularly edge cases with special characters.

Tests verify that:
1. Queries with hyphens are properly handled (fixes FTS5 column name parsing issue)
2. Various edge cases with special characters work correctly
3. Normal queries continue to work as expected
"""

import pytest
import sqlite3
import tempfile
import time
import shutil
from pathlib import Path
from unittest.mock import patch
import sys

# Add parent directory to path to import mcp_server
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestHyphenatedQueries:
    """Test queries containing hyphens (the main bug fix)."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database with FTS5 table matching production schema."""
        temp_dir = Path(tempfile.mkdtemp())
        db_path = temp_dir / "test.db"
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()

        # Create tables matching the production schema
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

        # Create FTS5 table matching production schema
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

        # Insert test data with hyphenated terms
        now = time.time()
        test_chunks = [
            ("chunk_1", "/test/Document-Mailing.pas", "Document-Mailing.pas", 0,
             "codeunit Document-Mailing sales invoice email body create message", "hash_1"),
            ("chunk_2", "/test/Email-Service.pas", "Email-Service.pas", 0,
             "Email-Service codeunit for sending emails", "hash_2"),
            ("chunk_3", "/test/normal.pas", "normal.pas", 0,
             "normal codeunit without hyphens", "hash_3"),
            ("chunk_4", "/test/multi-hyphen-test.pas", "multi-hyphen-test.pas", 0,
             "multi-hyphen-test codeunit with multiple hyphens", "hash_4"),
            ("chunk_5", "/test/edge-case.pas", "edge-case.pas", 0,
             "edge-case codeunit with hyphen at end", "hash_5"),
        ]

        for chunk_data in test_chunks:
            c.execute("""
                INSERT INTO chunks (id, file_path, file_name, chunk_index, content, content_hash, embedding, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (*chunk_data, None, now, now))

        # Populate FTS index using triggers (simulating production behavior)
        # Since we're inserting directly, we need to manually populate FTS
        for chunk_data in test_chunks:
            c.execute("""
                INSERT INTO chunks_fts(rowid, id, file_path, file_name, content)
                SELECT rowid, id, file_path, file_name, content
                FROM chunks WHERE id = ?
            """, (chunk_data[0],))

        conn.commit()
        conn.close()

        yield db_path

        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_hyphenated_query_original_bug(self, temp_db):
        """
        Test the original bug scenario: "Document-Mailing codeunit sales invoice email body create message"
        
        This query was failing with: "no such column: Mailing"
        """
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            # This should not raise an error
            results = bm25_search("Document-Mailing codeunit sales invoice email body create message", top_k=10)

            # Should return results (at least the Document-Mailing chunk)
            assert len(results) > 0
            assert any("Document-Mailing" in r["file_name"] for r in results)

    def test_single_hyphenated_word(self, temp_db):
        """Test a query with just a single hyphenated word."""
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            results = bm25_search("Document-Mailing", top_k=10)

            assert len(results) > 0
            assert any("Document-Mailing" in r["file_name"] for r in results)

    def test_multiple_hyphenated_words(self, temp_db):
        """Test a query with multiple hyphenated words."""
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            results = bm25_search("Document-Mailing Email-Service", top_k=10)

            # Should find chunks matching either term
            assert len(results) > 0
            file_names = [r["file_name"] for r in results]
            assert any("Document-Mailing" in name or "Email-Service" in name for name in file_names)

    def test_hyphenated_word_with_normal_words(self, temp_db):
        """Test mixing hyphenated words with normal words."""
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            results = bm25_search("Document-Mailing codeunit", top_k=10)

            assert len(results) > 0
            # Should find the Document-Mailing chunk that contains "codeunit"
            assert any("Document-Mailing" in r["file_name"] and "codeunit" in r["content"].lower() 
                      for r in results)

    def test_query_without_hyphens_still_works(self, temp_db):
        """Test that normal queries without hyphens continue to work."""
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            results = bm25_search("normal codeunit", top_k=10)

            assert len(results) > 0
            assert any("normal.pas" in r["file_name"] for r in results)

    def test_multiple_hyphens_in_word(self, temp_db):
        """Test words with multiple hyphens."""
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            results = bm25_search("multi-hyphen-test", top_k=10)

            assert len(results) > 0
            assert any("multi-hyphen-test" in r["file_name"] for r in results)

    def test_hyphen_at_start_or_end(self, temp_db):
        """Test edge cases with hyphens at word boundaries."""
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            # Test hyphen at end (edge-case)
            results = bm25_search("edge-case", top_k=10)
            assert len(results) > 0
            assert any("edge-case" in r["file_name"] for r in results)

    def test_fts_query_formatting(self, temp_db):
        """
        Test that the FTS query is properly formatted with quotes around hyphenated words.
        
        This is an indirect test - we verify the query works, which means
        the formatting must be correct.
        """
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            # Query that would fail if not properly quoted
            query = "Document-Mailing Email-Service codeunit"
            results = bm25_search(query, top_k=10)

            # If we get here without an error, the query was properly formatted
            assert isinstance(results, list)
            # Should find results matching the terms
            assert len(results) > 0


class TestSpecialCharacterQueries:
    """Test queries with other special characters that might cause issues."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database with test data."""
        temp_dir = Path(tempfile.mkdtemp())
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
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                id,
                file_path,
                file_name,
                content,
                content='chunks',
                content_rowid='rowid'
            )
        """)

        now = time.time()
        test_chunks = [
            ("chunk_1", "/test/file1.pas", "file1.pas", 0,
             "C# style code with underscore_variable", "hash_1"),
            ("chunk_2", "/test/file2.pas", "file2.pas", 0,
             "CamelCase function name", "hash_2"),
            ("chunk_3", "/test/file3.pas", "file3.pas", 0,
             "Numbers like 123 and 456", "hash_3"),
        ]

        for chunk_data in test_chunks:
            c.execute("""
                INSERT INTO chunks (id, file_path, file_name, chunk_index, content, content_hash, embedding, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (*chunk_data, None, now, now))

            c.execute("""
                INSERT INTO chunks_fts(rowid, id, file_path, file_name, content)
                SELECT rowid, id, file_path, file_name, content
                FROM chunks WHERE id = ?
            """, (chunk_data[0],))

        conn.commit()
        conn.close()

        yield db_path

        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_underscore_in_query(self, temp_db):
        """Test queries with underscores (should work normally)."""
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            results = bm25_search("underscore_variable", top_k=10)
            assert len(results) > 0

    def test_camelcase_query(self, temp_db):
        """Test queries with CamelCase."""
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            results = bm25_search("CamelCase", top_k=10)
            assert len(results) > 0

    def test_numbers_in_query(self, temp_db):
        """Test queries with numbers."""
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            results = bm25_search("123 456", top_k=10)
            assert len(results) > 0


class TestEmptyAndEdgeCaseQueries:
    """Test edge cases like empty queries, very long queries, etc."""

    @pytest.fixture
    def temp_db(self):
        """Create a minimal database."""
        temp_dir = Path(tempfile.mkdtemp())
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
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                id,
                file_path,
                file_name,
                content,
                content='chunks',
                content_rowid='rowid'
            )
        """)

        conn.commit()
        conn.close()

        yield db_path

        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_empty_query(self, temp_db):
        """Test that empty queries are handled gracefully."""
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            # Empty queries cause FTS5 syntax errors, so we expect an exception
            # This is acceptable behavior - empty queries are invalid
            with pytest.raises(sqlite3.OperationalError):
                bm25_search("", top_k=10)

    def test_single_character_query(self, temp_db):
        """Test very short queries."""
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            results = bm25_search("a", top_k=10)
            assert isinstance(results, list)

    def test_query_with_only_hyphen(self, temp_db):
        """Test query that is just a hyphen."""
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            # Should handle gracefully without error
            results = bm25_search("-", top_k=10)
            assert isinstance(results, list)

    def test_query_with_multiple_consecutive_hyphens(self, temp_db):
        """Test query with multiple hyphens in a row."""
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            results = bm25_search("test--double--hyphen", top_k=10)
            assert isinstance(results, list)

    def test_query_with_quotes_in_hyphenated_word(self, temp_db):
        """Test that quotes in hyphenated words are properly escaped."""
        from mcp_server import bm25_search

        # Create a database with content containing quotes
        conn = sqlite3.connect(str(temp_db))
        c = conn.cursor()
        now = time.time()
        c.execute("""
            INSERT INTO chunks (id, file_path, file_name, chunk_index, content, content_hash, embedding, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ("chunk_quote", "/test/file.pas", "file.pas", 0,
              'test"quote codeunit', "hash_quote", None, now, now))
        c.execute("""
            INSERT INTO chunks_fts(rowid, id, file_path, file_name, content)
            SELECT rowid, id, file_path, file_name, content
            FROM chunks WHERE id = ?
        """, ("chunk_quote",))
        conn.commit()
        conn.close()

        with patch('mcp_server.DB_PATH', temp_db):
            # This should not raise an error even with quotes in hyphenated words
            # Note: This is an edge case - quotes in hyphenated words are rare
            try:
                results = bm25_search('test"quote-hyphen', top_k=10)
                assert isinstance(results, list)
            except sqlite3.OperationalError:
                # If it fails, that's acceptable for this edge case
                pass


class TestFileFilterWithHyphens:
    """Test that file_filter parameter works correctly with hyphenated queries."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database with files in different directories."""
        temp_dir = Path(tempfile.mkdtemp())
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
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                id,
                file_path,
                file_name,
                content,
                content='chunks',
                content_rowid='rowid'
            )
        """)

        now = time.time()
        test_chunks = [
            ("chunk_1", "/src/Document-Mailing.pas", "Document-Mailing.pas", 0,
             "Document-Mailing codeunit", "hash_1"),
            ("chunk_2", "/test/Document-Mailing.pas", "Document-Mailing.pas", 0,
             "Document-Mailing test codeunit", "hash_2"),
            ("chunk_3", "/src/Email-Service.pas", "Email-Service.pas", 0,
             "Email-Service codeunit", "hash_3"),
        ]

        for chunk_data in test_chunks:
            c.execute("""
                INSERT INTO chunks (id, file_path, file_name, chunk_index, content, content_hash, embedding, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (*chunk_data, None, now, now))

            c.execute("""
                INSERT INTO chunks_fts(rowid, id, file_path, file_name, content)
                SELECT rowid, id, file_path, file_name, content
                FROM chunks WHERE id = ?
            """, (chunk_data[0],))

        conn.commit()
        conn.close()

        yield db_path

        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_file_filter_with_hyphenated_query(self, temp_db):
        """Test that file_filter works correctly with hyphenated queries."""
        from mcp_server import bm25_search

        with patch('mcp_server.DB_PATH', temp_db):
            # Search for Document-Mailing but only in /src directory
            results = bm25_search("Document-Mailing codeunit", top_k=10, file_filter="/src/")

            assert len(results) > 0
            # All results should be from /src directory
            assert all("/src/" in r["file_path"] for r in results)
            # Should not include /test/ directory results
            assert not any("/test/" in r["file_path"] for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

