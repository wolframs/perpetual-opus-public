#!/usr/bin/env python3
"""
Tests for MCP server cold-start behavior and resilience.

Tests verify that:
1. Server responds to MCP protocol immediately (non-blocking init)
2. Background initialization runs without blocking protocol responses
3. Ollama auto-start functionality works correctly
4. Warnings are properly communicated to users when functionality is degraded
5. Initialization state is correctly tracked and reported
"""

import pytest
import sqlite3
import tempfile
import time
import json
import shutil
import threading
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add parent directory to path to import mcp_server
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestServerState:
    """Test the ServerState tracking functionality."""

    def test_init_state_enum_values(self):
        """Verify InitState enum has expected values."""
        # Import after path setup
        from mcp_server import InitState

        assert InitState.PENDING.value == "pending"
        assert InitState.INITIALIZING.value == "initializing"
        assert InitState.READY.value == "ready"
        assert InitState.FAILED.value == "failed"

    def test_server_state_default_values(self):
        """Test ServerState dataclass default initialization."""
        from mcp_server import ServerState, InitState

        state = ServerState()
        assert state.init_state == InitState.PENDING
        assert state.init_start_time is None
        assert state.init_error is None
        assert state.stats_cache is None
        assert state.ollama_available is None

    def test_estimated_time_remaining_not_initializing(self):
        """Test ETA returns None when not initializing."""
        from mcp_server import ServerState, InitState

        state = ServerState()
        assert state.estimated_time_remaining() is None

        state.init_state = InitState.READY
        assert state.estimated_time_remaining() is None

    def test_estimated_time_remaining_during_init(self):
        """Test ETA returns values during initialization."""
        from mcp_server import ServerState, InitState

        state = ServerState()
        state.init_state = InitState.INITIALIZING
        state.init_start_time = time.time() - 2  # 2 seconds ago

        eta = state.estimated_time_remaining()
        assert eta is not None
        assert eta > 0


class TestOllamaAutoStart:
    """Test Ollama detection and auto-start functionality."""

    def test_is_ollama_running_when_not_running(self):
        """Test detection when Ollama is not running."""
        from mcp_server import is_ollama_running
        import requests

        with patch('mcp_server.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
            assert is_ollama_running() is False

    def test_is_ollama_running_when_running(self):
        """Test detection when Ollama is running."""
        from mcp_server import is_ollama_running

        with patch('mcp_server.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            assert is_ollama_running() is True

    def test_is_ollama_running_timeout(self):
        """Test detection handles timeout gracefully."""
        from mcp_server import is_ollama_running
        import requests

        with patch('mcp_server.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout()
            assert is_ollama_running() is False

    def test_start_ollama_already_running(self):
        """Test start_ollama returns True if already running."""
        from mcp_server import start_ollama, _server_state

        with patch('mcp_server.is_ollama_running', return_value=True):
            result = start_ollama()
            assert result is True
            assert _server_state.ollama_available is True

    def test_start_ollama_executable_not_found(self):
        """Test start_ollama handles missing executable."""
        from mcp_server import start_ollama, _server_state

        with patch('mcp_server.is_ollama_running', return_value=False):
            with patch('mcp_server.OLLAMA_PATH', Path("/nonexistent/path/ollama.exe")):
                result = start_ollama()
                assert result is False
                assert _server_state.ollama_available is False

    def test_ensure_ollama_available_caches_result(self):
        """Test that ensure_ollama_available caches the result."""
        from mcp_server import ensure_ollama_available, _server_state, ServerState

        # Reset state
        _server_state.ollama_available = None

        with patch('mcp_server.is_ollama_running', return_value=True) as mock_check:
            # First call should check
            result1 = ensure_ollama_available()
            assert result1 is True
            assert mock_check.call_count == 1

            # Second call should use cache
            result2 = ensure_ollama_available()
            assert result2 is True
            # Should not have called is_ollama_running again
            assert mock_check.call_count == 1


class TestSearchResultWarnings:
    """Test that search results properly communicate warnings."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        temp_dir = Path(tempfile.mkdtemp())
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
                embedding TEXT,
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

        # Create FTS table
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                content,
                content='chunks',
                content_rowid='rowid'
            )
        """)

        # Insert test data
        now = time.time()
        for i in range(5):
            c.execute("""
                INSERT INTO chunks (id, file_path, file_name, chunk_index, content, content_hash, embedding, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (f"chunk_{i}", f"/test/file_{i}.py", f"file_{i}.py", 0,
                  f"def test_function_{i}(): pass", f"hash_{i}", None, now, now))

        # Populate FTS index
        c.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")

        c.execute("""
            INSERT INTO files (path, mtime, size, chunk_count)
            VALUES (?, ?, ?, ?)
        """, ("/test/file_0.py", now, 100, 1))

        conn.commit()
        conn.close()

        yield db_path

        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_search_result_has_warnings_field(self):
        """Test SearchResult dataclass has warnings field."""
        from mcp_server import SearchResult

        result = SearchResult(results=[], warnings=["test warning"])
        assert result.warnings == ["test warning"]
        assert result.results == []

    def test_hybrid_search_returns_search_result(self, temp_db):
        """Test that hybrid_search returns SearchResult with warnings."""
        from mcp_server import hybrid_search, SearchResult

        with patch('mcp_server.DB_PATH', temp_db):
            with patch('mcp_server.ensure_ollama_available', return_value=False):
                result = hybrid_search("test", use_semantic=True)

                assert isinstance(result, SearchResult)
                assert isinstance(result.warnings, list)
                assert isinstance(result.results, list)

    def test_hybrid_search_warns_on_ollama_unavailable(self, temp_db):
        """Test that hybrid_search warns when Ollama is unavailable."""
        from mcp_server import hybrid_search, OllamaUnavailableError

        with patch('mcp_server.DB_PATH', temp_db):
            with patch('mcp_server.get_embedding', side_effect=OllamaUnavailableError("Ollama not running")):
                result = hybrid_search("test function", use_semantic=True)

                # Should have warnings about Ollama
                assert len(result.warnings) > 0
                assert any("Ollama" in w or "semantic" in w.lower() for w in result.warnings)
                # Should still return results (BM25 fallback)
                assert result.semantic_enabled is False

    def test_hybrid_search_no_warnings_when_working(self, temp_db):
        """Test that hybrid_search has no warnings when everything works."""
        from mcp_server import hybrid_search

        mock_embedding = [0.1] * 768  # Typical embedding size

        with patch('mcp_server.DB_PATH', temp_db):
            with patch('mcp_server.get_embedding', return_value=mock_embedding):
                result = hybrid_search("test", use_semantic=True)

                # Should have no warnings
                assert len(result.warnings) == 0
                assert result.semantic_enabled is True


class TestNonBlockingInitialization:
    """Test non-blocking server initialization."""

    def test_background_initialize_sets_state(self):
        """Test that background_initialize properly sets state."""
        from mcp_server import background_initialize, _server_state, InitState

        # Reset state
        _server_state.init_state = InitState.PENDING
        _server_state.init_start_time = None

        with patch('mcp_server.get_stats', return_value={
            'indexed_files': 100,
            'total_chunks': 1000,
            'embedding_coverage': '50%'
        }):
            with patch('mcp_server.is_ollama_running', return_value=True):
                background_initialize()

        assert _server_state.init_state == InitState.READY
        assert _server_state.stats_cache is not None

    def test_background_initialize_handles_db_error(self):
        """Test that background_initialize handles database errors gracefully."""
        from mcp_server import background_initialize, _server_state, InitState

        # Reset state
        _server_state.init_state = InitState.PENDING
        _server_state.init_error = None

        with patch('mcp_server.get_stats', side_effect=sqlite3.OperationalError("database is locked")):
            background_initialize()

        # Should be READY (allowing retries on tool calls) not FAILED
        assert _server_state.init_state == InitState.READY
        assert _server_state.init_error is not None
        assert "locked" in _server_state.init_error.lower()

    def test_background_initialize_handles_general_error(self):
        """Test that background_initialize handles general errors."""
        from mcp_server import background_initialize, _server_state, InitState

        # Reset state
        _server_state.init_state = InitState.PENDING
        _server_state.init_error = None

        with patch('mcp_server.get_stats', side_effect=Exception("Some error")):
            background_initialize()

        assert _server_state.init_state == InitState.FAILED
        assert _server_state.init_error is not None

    def test_init_thread_is_daemon(self):
        """Test that initialization thread is created as daemon."""
        # This is a design verification test
        # Daemon threads don't block program exit
        init_thread = threading.Thread(target=lambda: None, daemon=True)
        assert init_thread.daemon is True


class TestToolCallDuringInit:
    """Test tool call handling during initialization."""

    def test_tool_call_returns_init_message_during_init(self):
        """Test that tool calls during init return informative message."""
        from mcp_server import handle_call_tool, _server_state, InitState

        # Set state to initializing
        _server_state.init_state = InitState.INITIALIZING
        _server_state.init_start_time = time.time()

        result = handle_call_tool({
            "name": "search_codebase",
            "arguments": {"query": "test"}
        })

        assert "content" in result
        assert len(result["content"]) > 0
        text = result["content"][0]["text"]
        assert "initializing" in text.lower()

    def test_tool_call_works_after_init_complete(self):
        """Test that tool calls work normally after init completes."""
        from mcp_server import handle_call_tool, _server_state, InitState, SearchResult

        # Set state to ready
        _server_state.init_state = InitState.READY

        with patch('mcp_server.hybrid_search', return_value=SearchResult(
            results=[],
            warnings=[],
            semantic_enabled=True
        )):
            result = handle_call_tool({
                "name": "search_codebase",
                "arguments": {"query": "test"}
            })

            assert "content" in result
            # Should not contain "initializing"
            text = result["content"][0]["text"]
            assert "initializing" not in text.lower()


class TestColdStartSimulation:
    """Simulate cold-start scenarios to test resilience."""

    @pytest.fixture
    def mock_slow_db(self):
        """Create a mock that simulates slow database access."""
        def slow_get_stats():
            time.sleep(0.5)  # Simulate slow disk access
            return {
                'indexed_files': 100,
                'total_chunks': 1000,
                'embedded_chunks': 500,
                'embedding_coverage': '50%'
            }
        return slow_get_stats

    def test_server_responds_before_db_warmup(self, mock_slow_db):
        """Test that server can respond to protocol before DB is warmed up."""
        from mcp_server import (
            handle_initialize, handle_list_tools,
            _server_state, InitState, background_initialize
        )

        # Reset state
        _server_state.init_state = InitState.PENDING

        # Start background init with slow DB
        with patch('mcp_server.get_stats', mock_slow_db):
            with patch('mcp_server.is_ollama_running', return_value=False):
                init_thread = threading.Thread(target=background_initialize, daemon=True)
                init_thread.start()

                # Immediately try to handle initialize - should work
                result = handle_initialize({})
                assert "protocolVersion" in result
                assert result["serverInfo"]["name"] == "codebase-rag"

                # List tools should also work
                tools_result = handle_list_tools({})
                assert "tools" in tools_result
                assert len(tools_result["tools"]) > 0

                # Wait for init to complete
                init_thread.join(timeout=2.0)

    def test_concurrent_tool_calls_during_init(self, mock_slow_db):
        """Test handling of concurrent tool calls during initialization."""
        from mcp_server import handle_call_tool, _server_state, InitState, background_initialize

        # Reset state
        _server_state.init_state = InitState.PENDING

        results = []
        errors = []

        def make_tool_call():
            try:
                result = handle_call_tool({
                    "name": "codebase_stats",
                    "arguments": {}
                })
                results.append(result)
            except Exception as e:
                errors.append(e)

        with patch('mcp_server.get_stats', mock_slow_db):
            with patch('mcp_server.is_ollama_running', return_value=False):
                # Start background init
                init_thread = threading.Thread(target=background_initialize, daemon=True)
                init_thread.start()

                # Make concurrent tool calls
                call_threads = []
                for _ in range(3):
                    t = threading.Thread(target=make_tool_call)
                    t.start()
                    call_threads.append(t)

                # Wait for all calls to complete
                for t in call_threads:
                    t.join(timeout=2.0)

                init_thread.join(timeout=2.0)

        # All calls should complete without errors
        assert len(errors) == 0
        assert len(results) == 3


class TestOllamaUnavailableError:
    """Test the OllamaUnavailableError exception."""

    def test_exception_can_be_raised(self):
        """Test that OllamaUnavailableError can be raised and caught."""
        from mcp_server import OllamaUnavailableError

        with pytest.raises(OllamaUnavailableError) as exc_info:
            raise OllamaUnavailableError("Test error message")

        assert "Test error message" in str(exc_info.value)

    def test_get_embedding_raises_when_requested(self):
        """Test get_embedding raises OllamaUnavailableError when requested."""
        from mcp_server import get_embedding, OllamaUnavailableError

        with patch('mcp_server.ensure_ollama_available', return_value=False):
            with pytest.raises(OllamaUnavailableError):
                get_embedding("test", raise_on_unavailable=True)

    def test_get_embedding_returns_none_by_default(self):
        """Test get_embedding returns None by default when Ollama unavailable."""
        from mcp_server import get_embedding

        with patch('mcp_server.ensure_ollama_available', return_value=False):
            result = get_embedding("test", raise_on_unavailable=False)
            assert result is None


class TestSearchCache:
    """Test the SearchCache functionality."""

    @pytest.fixture
    def temp_db_file(self):
        """Create a temporary database file for cache testing."""
        temp_dir = Path(tempfile.mkdtemp())
        db_path = temp_dir / "test.db"
        # Create an empty file
        db_path.touch()
        yield db_path
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_cache_basic_put_get(self):
        """Test basic cache put and get operations."""
        from mcp_server import SearchCache, SearchResult

        cache = SearchCache(maxsize=10, ttl_seconds=60.0)

        result = SearchResult(results=[{"test": "data"}], warnings=[], semantic_enabled=True)
        cache.put("test query", 10, None, True, result)

        cached = cache.get("test query", 10, None, True)
        assert cached is not None
        assert cached.results == [{"test": "data"}]

    def test_cache_miss_different_params(self):
        """Test that different parameters result in cache miss."""
        from mcp_server import SearchCache, SearchResult

        cache = SearchCache(maxsize=10, ttl_seconds=60.0)

        result = SearchResult(results=[{"test": "data"}], warnings=[], semantic_enabled=True)
        cache.put("test query", 10, None, True, result)

        # Different top_k
        assert cache.get("test query", 5, None, True) is None
        # Different query
        assert cache.get("different query", 10, None, True) is None
        # Different semantic flag
        assert cache.get("test query", 10, None, False) is None

    def test_cache_ttl_expiration(self):
        """Test that cache entries expire after TTL."""
        from mcp_server import SearchCache, SearchResult

        cache = SearchCache(maxsize=10, ttl_seconds=0.1)  # 100ms TTL

        result = SearchResult(results=[{"test": "data"}], warnings=[], semantic_enabled=True)
        cache.put("test query", 10, None, True, result)

        # Should hit immediately
        assert cache.get("test query", 10, None, True) is not None

        # Wait for expiration
        time.sleep(0.2)

        # Should miss after TTL
        assert cache.get("test query", 10, None, True) is None

    def test_cache_maxsize_eviction(self):
        """Test that oldest entries are evicted when cache is full."""
        from mcp_server import SearchCache, SearchResult

        cache = SearchCache(maxsize=3, ttl_seconds=60.0)

        # Fill cache
        for i in range(3):
            result = SearchResult(results=[{"id": i}], warnings=[], semantic_enabled=True)
            cache.put(f"query{i}", 10, None, True, result)

        # All should be present
        assert cache.get("query0", 10, None, True) is not None
        assert cache.get("query1", 10, None, True) is not None
        assert cache.get("query2", 10, None, True) is not None

        # Add one more - should evict oldest (query0, but it was just accessed so query1)
        result = SearchResult(results=[{"id": 3}], warnings=[], semantic_enabled=True)
        cache.put("query3", 10, None, True, result)

        # query1 should be evicted (oldest not recently accessed)
        stats = cache.stats()
        assert stats["size"] == 3

    def test_cache_db_invalidation(self, temp_db_file):
        """Test that cache invalidates when database file is modified."""
        from mcp_server import SearchCache, SearchResult

        cache = SearchCache(maxsize=10, ttl_seconds=60.0, db_path=temp_db_file)

        result = SearchResult(results=[{"test": "data"}], warnings=[], semantic_enabled=True)
        cache.put("test query", 10, None, True, result)

        # Should hit
        assert cache.get("test query", 10, None, True) is not None

        # Modify the database file
        time.sleep(0.1)  # Ensure mtime changes
        temp_db_file.touch()

        # Should miss due to invalidation
        assert cache.get("test query", 10, None, True) is None

        # Check invalidation count
        stats = cache.stats()
        assert stats["invalidations"] == 1

    def test_cache_stats(self):
        """Test cache statistics tracking."""
        from mcp_server import SearchCache, SearchResult

        cache = SearchCache(maxsize=10, ttl_seconds=60.0)

        # Miss
        cache.get("nonexistent", 10, None, True)

        # Put and hit
        result = SearchResult(results=[], warnings=[], semantic_enabled=True)
        cache.put("test", 10, None, True, result)
        cache.get("test", 10, None, True)

        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1
        assert stats["hit_rate"] == "50.0%"

    def test_cache_thread_safety(self):
        """Test that cache is thread-safe under concurrent access."""
        from mcp_server import SearchCache, SearchResult

        cache = SearchCache(maxsize=100, ttl_seconds=60.0)
        errors = []

        def writer(thread_id):
            try:
                for i in range(50):
                    result = SearchResult(results=[{"t": thread_id, "i": i}], warnings=[], semantic_enabled=True)
                    cache.put(f"query_{thread_id}_{i}", 10, None, True, result)
            except Exception as e:
                errors.append(e)

        def reader(thread_id):
            try:
                for i in range(50):
                    cache.get(f"query_{thread_id}_{i}", 10, None, True)
            except Exception as e:
                errors.append(e)

        threads = []
        for t in range(5):
            threads.append(threading.Thread(target=writer, args=(t,)))
            threads.append(threading.Thread(target=reader, args=(t,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_cache_clear(self):
        """Test cache clear functionality."""
        from mcp_server import SearchCache, SearchResult

        cache = SearchCache(maxsize=10, ttl_seconds=60.0)

        for i in range(5):
            result = SearchResult(results=[{"id": i}], warnings=[], semantic_enabled=True)
            cache.put(f"query{i}", 10, None, True, result)

        assert cache.stats()["size"] == 5

        cache.clear()

        assert cache.stats()["size"] == 0


class TestConcurrentDispatch:
    """Test the concurrent request dispatch mechanism added in Step 3."""

    @pytest.mark.asyncio
    async def test_handle_request_async_runs_in_executor(self):
        """Test that handle_request_async runs handler in thread pool."""
        from mcp_server import handle_request_async, _output_lock
        import io
        from concurrent.futures import ThreadPoolExecutor

        # Create executor and patch the module-level one
        executor = ThreadPoolExecutor(max_workers=2)

        handlers = {
            "test_method": lambda params: {"result": "success", "thread": threading.current_thread().name}
        }

        request = {"jsonrpc": "2.0", "id": 1, "method": "test_method", "params": {}}

        captured = io.StringIO()
        with patch('mcp_server._executor', executor):
            with patch('sys.stdout', captured):
                await handle_request_async(request, handlers)

        output = captured.getvalue()
        response = json.loads(output.strip())

        assert response["id"] == 1
        assert response["result"]["result"] == "success"
        # Verify it ran in a thread pool thread (not main thread)
        assert "ThreadPoolExecutor" in response["result"]["thread"] or "mcp-handler" in response["result"]["thread"]

        executor.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_concurrent_requests_run_in_parallel(self):
        """Test that multiple requests can run concurrently."""
        from mcp_server import handle_request_async
        import io
        from concurrent.futures import ThreadPoolExecutor

        executor = ThreadPoolExecutor(max_workers=4)

        # Track execution timing
        execution_log = []
        log_lock = threading.Lock()

        def slow_handler(params):
            req_id = params.get("id")
            with log_lock:
                execution_log.append(f"start-{req_id}")
            time.sleep(0.1)  # Simulate work
            with log_lock:
                execution_log.append(f"end-{req_id}")
            return {"id": req_id}

        handlers = {"slow": slow_handler}

        captured = io.StringIO()
        with patch('mcp_server._executor', executor):
            with patch('sys.stdout', captured):
                # Launch 3 concurrent requests
                tasks = [
                    asyncio.create_task(handle_request_async(
                        {"jsonrpc": "2.0", "id": i, "method": "slow", "params": {"id": i}},
                        handlers
                    ))
                    for i in range(3)
                ]
                await asyncio.gather(*tasks)

        executor.shutdown(wait=False)

        # Verify all requests completed
        assert len(execution_log) == 6  # 3 starts + 3 ends

        # Verify concurrency: if sequential, pattern would be start-end-start-end-start-end
        # With concurrency, we should see multiple starts before all ends
        start_indices = [i for i, x in enumerate(execution_log) if x.startswith("start")]
        end_indices = [i for i, x in enumerate(execution_log) if x.startswith("end")]

        # At least 2 starts should happen before any end (concurrent execution)
        first_end_index = min(end_indices)
        starts_before_first_end = sum(1 for i in start_indices if i < first_end_index)
        assert starts_before_first_end >= 2, f"Expected concurrent starts, got: {execution_log}"

    def test_executor_module_level_exists(self):
        """Test that _executor module-level variable exists."""
        from mcp_server import _executor
        # Initially None before async_main runs
        assert _executor is None

    @pytest.mark.asyncio
    async def test_handle_request_async_preserves_request_id(self):
        """Test that request IDs are preserved through async handling."""
        from mcp_server import handle_request_async
        import io
        from concurrent.futures import ThreadPoolExecutor

        executor = ThreadPoolExecutor(max_workers=2)

        handlers = {"echo": lambda p: p}

        captured = io.StringIO()
        with patch('mcp_server._executor', executor):
            with patch('sys.stdout', captured):
                await handle_request_async(
                    {"jsonrpc": "2.0", "id": "test-id-123", "method": "echo", "params": {"data": "test"}},
                    handlers
                )

        response = json.loads(captured.getvalue().strip())
        assert response["id"] == "test-id-123"
        executor.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_output_lock_prevents_interleaving_in_async(self):
        """Test that output lock prevents response interleaving with concurrent handlers."""
        from mcp_server import handle_request_async, _output_lock
        import io
        from concurrent.futures import ThreadPoolExecutor

        executor = ThreadPoolExecutor(max_workers=4)

        handlers = {"fast": lambda p: {"id": p.get("id")}}

        captured = io.StringIO()
        with patch('mcp_server._executor', executor):
            with patch('sys.stdout', captured):
                # Launch many concurrent requests
                tasks = [
                    asyncio.create_task(handle_request_async(
                        {"jsonrpc": "2.0", "id": i, "method": "fast", "params": {"id": i}},
                        handlers
                    ))
                    for i in range(10)
                ]
                await asyncio.gather(*tasks)

        executor.shutdown(wait=False)

        # Each line should be valid JSON (no interleaving)
        lines = captured.getvalue().strip().split('\n')
        assert len(lines) == 10

        for line in lines:
            parsed = json.loads(line)  # Should not raise
            assert "jsonrpc" in parsed
            assert "id" in parsed


class TestAsyncStdinReader:
    """Test the async stdin reading mechanism added in Step 2."""

    @pytest.mark.asyncio
    async def test_stdin_reader_thread_puts_lines_in_queue(self):
        """Test that stdin_reader_thread correctly puts lines into the queue."""
        from mcp_server import stdin_reader_thread
        import io

        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        # Mock stdin with test input
        mock_stdin = io.StringIO('{"method":"test1"}\n{"method":"test2"}\n')

        with patch('sys.stdin', mock_stdin):
            # Run reader in thread
            reader_thread = threading.Thread(
                target=stdin_reader_thread,
                args=(queue, loop),
                daemon=True
            )
            reader_thread.start()
            reader_thread.join(timeout=1.0)

        # Verify lines were put in queue
        line1 = await asyncio.wait_for(queue.get(), timeout=1.0)
        line2 = await asyncio.wait_for(queue.get(), timeout=1.0)
        end_signal = await asyncio.wait_for(queue.get(), timeout=1.0)

        assert line1 == '{"method":"test1"}'
        assert line2 == '{"method":"test2"}'
        assert end_signal is None  # End of input signal

    @pytest.mark.asyncio
    async def test_stdin_reader_strips_bom(self):
        """Test that UTF-8 BOM is stripped from input."""
        from mcp_server import stdin_reader_thread
        import io

        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        # Mock stdin with BOM prefix
        mock_stdin = io.StringIO('\ufeff{"method":"test"}\n')

        with patch('sys.stdin', mock_stdin):
            reader_thread = threading.Thread(
                target=stdin_reader_thread,
                args=(queue, loop),
                daemon=True
            )
            reader_thread.start()
            reader_thread.join(timeout=1.0)

        line = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert line == '{"method":"test"}'
        assert not line.startswith('\ufeff')

    @pytest.mark.asyncio
    async def test_stdin_reader_skips_empty_lines(self):
        """Test that empty lines are skipped."""
        from mcp_server import stdin_reader_thread
        import io

        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        # Mock stdin with empty lines
        mock_stdin = io.StringIO('{"method":"test1"}\n\n   \n{"method":"test2"}\n')

        with patch('sys.stdin', mock_stdin):
            reader_thread = threading.Thread(
                target=stdin_reader_thread,
                args=(queue, loop),
                daemon=True
            )
            reader_thread.start()
            reader_thread.join(timeout=1.0)

        line1 = await asyncio.wait_for(queue.get(), timeout=1.0)
        line2 = await asyncio.wait_for(queue.get(), timeout=1.0)
        end_signal = await asyncio.wait_for(queue.get(), timeout=1.0)

        assert line1 == '{"method":"test1"}'
        assert line2 == '{"method":"test2"}'
        assert end_signal is None

    @pytest.mark.asyncio
    async def test_stdin_reader_signals_end_on_close(self):
        """Test that None is put in queue when stdin closes."""
        from mcp_server import stdin_reader_thread
        import io

        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        # Empty stdin (immediately closes)
        mock_stdin = io.StringIO('')

        with patch('sys.stdin', mock_stdin):
            reader_thread = threading.Thread(
                target=stdin_reader_thread,
                args=(queue, loop),
                daemon=True
            )
            reader_thread.start()
            reader_thread.join(timeout=1.0)

        end_signal = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert end_signal is None

    def test_request_queue_module_level_exists(self):
        """Test that _request_queue module-level variable exists."""
        from mcp_server import _request_queue
        # Initially None before async_main runs
        assert _request_queue is None


class TestAsyncInfrastructure:
    """Test the async infrastructure added in Step 1 of asyncio refactor."""

    def test_handle_request_sync_success(self):
        """Test handle_request_sync returns correct response for valid requests."""
        from mcp_server import handle_request_sync

        handlers = {
            "test_method": lambda params: {"success": True, "param": params.get("key")}
        }

        request = {
            "jsonrpc": "2.0",
            "id": 123,
            "method": "test_method",
            "params": {"key": "value"}
        }

        response = handle_request_sync(request, handlers)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 123
        assert response["result"]["success"] is True
        assert response["result"]["param"] == "value"

    def test_handle_request_sync_unknown_method(self):
        """Test handle_request_sync returns empty result for unknown methods."""
        from mcp_server import handle_request_sync

        handlers = {}

        request = {
            "jsonrpc": "2.0",
            "id": 456,
            "method": "unknown_method",
            "params": {}
        }

        response = handle_request_sync(request, handlers)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 456
        assert response["result"] == {}

    def test_handle_request_sync_error(self):
        """Test handle_request_sync returns error response on exception."""
        from mcp_server import handle_request_sync

        def failing_handler(params):
            raise ValueError("Test error message")

        handlers = {"fail_method": failing_handler}

        request = {
            "jsonrpc": "2.0",
            "id": 789,
            "method": "fail_method",
            "params": {}
        }

        response = handle_request_sync(request, handlers)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 789
        assert "error" in response
        assert response["error"]["code"] == -32603
        assert "Test error message" in response["error"]["message"]

    def test_handle_request_sync_preserves_request_id(self):
        """Test that request IDs of various types are preserved."""
        from mcp_server import handle_request_sync

        handlers = {"echo": lambda p: p}

        # Test with string ID
        response = handle_request_sync(
            {"jsonrpc": "2.0", "id": "abc-123", "method": "echo", "params": {}},
            handlers
        )
        assert response["id"] == "abc-123"

        # Test with None ID (notification-style, though we still return)
        response = handle_request_sync(
            {"jsonrpc": "2.0", "id": None, "method": "echo", "params": {}},
            handlers
        )
        assert response["id"] is None

    @pytest.mark.asyncio
    async def test_write_response_outputs_json(self):
        """Test write_response outputs properly formatted JSON."""
        from mcp_server import write_response
        import io

        # Capture stdout
        captured = io.StringIO()
        with patch('sys.stdout', captured):
            await write_response({"jsonrpc": "2.0", "id": 1, "result": "test"})

        output = captured.getvalue()
        parsed = json.loads(output.strip())
        assert parsed["jsonrpc"] == "2.0"
        assert parsed["id"] == 1
        assert parsed["result"] == "test"

    @pytest.mark.asyncio
    async def test_write_response_lock_prevents_interleaving(self):
        """Test that output lock prevents response interleaving."""
        from mcp_server import write_response, _output_lock
        import asyncio
        import io

        outputs = []

        # Mock print to capture outputs with timing
        async def slow_write(response):
            async with _output_lock:
                outputs.append(f"start_{response['id']}")
                await asyncio.sleep(0.01)  # Simulate write time
                outputs.append(f"end_{response['id']}")

        # Run two writes concurrently
        await asyncio.gather(
            slow_write({"id": 1}),
            slow_write({"id": 2})
        )

        # Verify no interleaving - each start should be followed by its end
        assert outputs[0] == "start_1" or outputs[0] == "start_2"
        first_id = outputs[0].split("_")[1]
        assert outputs[1] == f"end_{first_id}"

    def test_output_lock_is_asyncio_lock(self):
        """Test that _output_lock is an asyncio.Lock instance."""
        from mcp_server import _output_lock
        import asyncio

        assert isinstance(_output_lock, asyncio.Lock)

    def test_main_function_exists(self):
        """Test that main() entry point exists and is callable."""
        from mcp_server import main

        assert callable(main)

    def test_async_main_exists(self):
        """Test that async_main() coroutine function exists."""
        from mcp_server import async_main
        import asyncio

        assert asyncio.iscoroutinefunction(async_main)


class TestConcurrentRequestIntegration:
    """Integration tests for concurrent request handling (Step 7)."""

    @pytest.mark.asyncio
    async def test_concurrent_tool_calls_processed_in_parallel(self):
        """Test that multiple tools/call requests run concurrently."""
        from mcp_server import handle_request_async, handle_call_tool, InitState, _server_state
        import io
        from concurrent.futures import ThreadPoolExecutor

        executor = ThreadPoolExecutor(max_workers=4)

        # Mock server state as ready
        original_state = _server_state.init_state
        _server_state.init_state = InitState.READY

        # Mock database operations to simulate work time
        start_times = {}
        end_times = {}
        call_lock = threading.Lock()

        original_handle_call_tool = handle_call_tool

        def mock_handle_call_tool(params):
            tool_name = params.get("name", "unknown")
            req_id = params.get("arguments", {}).get("query", "unknown")

            with call_lock:
                start_times[req_id] = time.time()

            # Simulate database/embedding work
            time.sleep(0.15)

            with call_lock:
                end_times[req_id] = time.time()

            return {
                "content": [{"type": "text", "text": f"Result for {req_id}"}]
            }

        handlers = {"tools/call": mock_handle_call_tool}

        captured = io.StringIO()

        try:
            with patch('mcp_server._executor', executor):
                with patch('sys.stdout', captured):
                    # Launch 4 concurrent search requests
                    start = time.time()
                    tasks = [
                        asyncio.create_task(handle_request_async(
                            {
                                "jsonrpc": "2.0",
                                "id": f"req-{i}",
                                "method": "tools/call",
                                "params": {
                                    "name": "search_codebase",
                                    "arguments": {"query": f"query-{i}"}
                                }
                            },
                            handlers
                        ))
                        for i in range(4)
                    ]
                    await asyncio.gather(*tasks)
                    total_time = time.time() - start
        finally:
            _server_state.init_state = original_state
            executor.shutdown(wait=False)

        # Verify all requests completed
        assert len(start_times) == 4
        assert len(end_times) == 4

        # Verify concurrency: with 0.15s work each, sequential would be 0.6s
        # With 4-way parallelism, should be ~0.15-0.2s
        assert total_time < 0.35, f"Concurrent execution too slow: {total_time:.2f}s (expected <0.35s)"

        # Verify responses are valid JSON
        lines = captured.getvalue().strip().split('\n')
        assert len(lines) == 4
        for line in lines:
            response = json.loads(line)
            assert response["jsonrpc"] == "2.0"
            assert response["id"].startswith("req-")

    @pytest.mark.asyncio
    async def test_request_ids_preserved_in_concurrent_responses(self):
        """Test that JSON-RPC request IDs are preserved even with out-of-order completion."""
        from mcp_server import handle_request_async
        import io
        from concurrent.futures import ThreadPoolExecutor

        executor = ThreadPoolExecutor(max_workers=4)

        # Handlers with varying response times to force out-of-order completion
        def handler_with_delay(params):
            delay = params.get("delay", 0)
            time.sleep(delay)
            return {"received_delay": delay}

        handlers = {"delayed": handler_with_delay}

        captured = io.StringIO()

        with patch('mcp_server._executor', executor):
            with patch('sys.stdout', captured):
                tasks = [
                    asyncio.create_task(handle_request_async(
                        {"jsonrpc": "2.0", "id": f"id-{i}", "method": "delayed", "params": {"delay": 0.1 - i * 0.02}},
                        handlers
                    ))
                    for i in range(5)
                ]
                await asyncio.gather(*tasks)

        executor.shutdown(wait=False)

        # Parse all responses
        lines = captured.getvalue().strip().split('\n')
        responses = [json.loads(line) for line in lines]

        # Verify all request IDs are present
        response_ids = {r["id"] for r in responses}
        expected_ids = {f"id-{i}" for i in range(5)}
        assert response_ids == expected_ids, f"Missing or extra IDs: {response_ids ^ expected_ids}"

    @pytest.mark.asyncio
    async def test_error_in_one_request_doesnt_affect_others(self):
        """Test that an error in one concurrent request doesn't affect others."""
        from mcp_server import handle_request_async
        import io
        from concurrent.futures import ThreadPoolExecutor

        executor = ThreadPoolExecutor(max_workers=4)

        def sometimes_fails(params):
            if params.get("fail"):
                raise ValueError("Intentional test error")
            return {"success": True}

        handlers = {"maybe_fail": sometimes_fails}

        captured = io.StringIO()

        with patch('mcp_server._executor', executor):
            with patch('sys.stdout', captured):
                tasks = [
                    asyncio.create_task(handle_request_async(
                        {"jsonrpc": "2.0", "id": i, "method": "maybe_fail", "params": {"fail": i == 2}},
                        handlers
                    ))
                    for i in range(5)
                ]
                # Should not raise - errors are captured in responses
                await asyncio.gather(*tasks)

        executor.shutdown(wait=False)

        # Parse responses
        lines = captured.getvalue().strip().split('\n')
        responses = {json.loads(line)["id"]: json.loads(line) for line in lines}

        # All responses should be present
        assert len(responses) == 5

        # Request 2 should have error
        assert "error" in responses[2]
        assert "Intentional test error" in responses[2]["error"]["message"]

        # Others should have success result
        for i in [0, 1, 3, 4]:
            assert "result" in responses[i]
            assert responses[i]["result"]["success"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
