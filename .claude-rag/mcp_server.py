#!/usr/bin/env python3
"""
MCP Server for Claude Code RAG
Provides hybrid search (BM25 + semantic) over indexed codebase.

Features:
- Hybrid search (BM25 + semantic) over indexed codebase
- Non-blocking initialization for fast MCP protocol startup
- Auto-start Ollama if not running
- Graceful handling of cold-start scenarios
"""

import sys
import os
import json
import sqlite3
import requests
import subprocess
import threading
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
from functools import lru_cache
from collections import OrderedDict

# Import shared core functionality
from search_core import (
    CONFIG, DB_PATH, DEFAULT_TOP_K, BM25_WEIGHT, SEMANTIC_WEIGHT,
    bm25_search as core_bm25_search,
    cosine_similarity,
    search_files as core_search_files,
    get_stats as core_get_stats,
)

# Load embedding configuration
OLLAMA_URL = CONFIG["embedding"]["ollama_url"]
EMBEDDING_MODEL = CONFIG["embedding"]["embedding_model"]

# Ollama executable path (configurable via config, or detect from PATH)
import shutil
_ollama_config_path = CONFIG.get("ollama", {}).get("executable_path")
if _ollama_config_path:
    OLLAMA_PATH = Path(_ollama_config_path)
else:
    _which = shutil.which("ollama")
    OLLAMA_PATH = Path(_which) if _which else Path("ollama")


class InitState(Enum):
    """Server initialization states."""
    PENDING = "pending"
    INITIALIZING = "initializing"
    READY = "ready"
    FAILED = "failed"


@dataclass
class ServerState:
    """Tracks server initialization state."""
    init_state: InitState = InitState.PENDING
    init_start_time: Optional[float] = None
    init_error: Optional[str] = None
    stats_cache: Optional[dict] = None
    ollama_available: Optional[bool] = None

    def estimated_time_remaining(self) -> Optional[float]:
        """Estimate remaining initialization time based on elapsed time."""
        if self.init_state != InitState.INITIALIZING or self.init_start_time is None:
            return None
        elapsed = time.time() - self.init_start_time
        # Rough estimate: initialization typically takes 5-30s for cold start
        # Use exponential backoff estimate
        if elapsed < 5:
            return 25.0
        elif elapsed < 15:
            return 15.0
        elif elapsed < 30:
            return 5.0
        else:
            return 1.0  # Almost there


# Global server state
_server_state = ServerState()


class SearchCache:
    """
    Thread-safe TTL cache for search results.

    Caches search results to avoid redundant computation when multiple
    agents query for the same or similar information.

    Auto-invalidates when the database file is modified (e.g., after reindexing).
    """

    def __init__(self, maxsize: int = 100, ttl_seconds: float = 300.0, db_path: Optional[Path] = None):
        """
        Initialize the cache.

        Args:
            maxsize: Maximum number of cached results
            ttl_seconds: Time-to-live for cache entries (default 5 minutes)
            db_path: Path to database file for change detection (auto-invalidation)
        """
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self.db_path = db_path
        self._cache: OrderedDict[str, tuple[float, any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.invalidations = 0
        self._last_db_mtime: Optional[float] = None

    def _get_db_mtime(self) -> Optional[float]:
        """Get database file modification time."""
        if self.db_path is None or not self.db_path.exists():
            return None
        try:
            return self.db_path.stat().st_mtime
        except OSError:
            return None

    def _check_db_invalidation(self) -> bool:
        """
        Check if database has been modified and invalidate cache if so.

        Returns True if cache was invalidated.
        """
        current_mtime = self._get_db_mtime()
        if current_mtime is None:
            return False

        if self._last_db_mtime is None:
            # First check - just record the mtime
            self._last_db_mtime = current_mtime
            return False

        if current_mtime != self._last_db_mtime:
            # Database was modified - invalidate cache
            self._cache.clear()
            self._last_db_mtime = current_mtime
            self.invalidations += 1
            return True

        return False

    def _make_key(self, query: str, top_k: int, file_filter: Optional[str], use_semantic: bool) -> str:
        """Create a cache key from search parameters."""
        key_data = f"{query}|{top_k}|{file_filter}|{use_semantic}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def get(self, query: str, top_k: int, file_filter: Optional[str], use_semantic: bool) -> Optional[any]:
        """
        Get a cached result if available and not expired.

        Returns None if not in cache, expired, or database was modified.
        """
        with self._lock:
            # Check if DB was modified - invalidates cache if so
            if self._check_db_invalidation():
                log("Cache invalidated: database was modified")
                self.misses += 1
                return None

            key = self._make_key(query, top_k, file_filter, use_semantic)

            if key not in self._cache:
                self.misses += 1
                return None

            timestamp, result = self._cache[key]

            # Check if expired
            if time.time() - timestamp > self.ttl_seconds:
                del self._cache[key]
                self.misses += 1
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self.hits += 1
            return result

    def put(self, query: str, top_k: int, file_filter: Optional[str], use_semantic: bool, result: any) -> None:
        """Store a result in the cache."""
        key = self._make_key(query, top_k, file_filter, use_semantic)

        with self._lock:
            # Remove oldest entries if at capacity
            while len(self._cache) >= self.maxsize:
                self._cache.popitem(last=False)

            self._cache[key] = (time.time(), result)

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()

    def stats(self) -> dict:
        """Get cache statistics."""
        with self._lock:
            total = self.hits + self.misses
            hit_rate = (self.hits / total * 100) if total > 0 else 0.0
            return {
                "size": len(self._cache),
                "maxsize": self.maxsize,
                "hits": self.hits,
                "misses": self.misses,
                "invalidations": self.invalidations,
                "hit_rate": f"{hit_rate:.1f}%",
                "ttl_seconds": self.ttl_seconds,
            }


# Global search cache (configurable via config.json mcp_server section)
_cache_config = CONFIG.get("mcp_server", {})
_search_cache = SearchCache(
    maxsize=_cache_config.get("cache_maxsize", 100),
    ttl_seconds=_cache_config.get("cache_ttl_seconds", 300.0),
    db_path=DB_PATH  # For auto-invalidation on reindex
)


def log(msg):
    """Log to stderr (visible in Claude Code logs)."""
    print(msg, file=sys.stderr, flush=True)


def is_ollama_running() -> bool:
    """Check if Ollama is running by attempting to connect to its API."""
    try:
        # Try to reach Ollama's API endpoint with a short timeout
        response = requests.get(
            OLLAMA_URL.replace("/api/embed", "/api/tags"),
            timeout=2
        )
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def start_ollama() -> bool:
    """
    Start Ollama if it's not running.

    Returns True if Ollama is now available, False otherwise.
    """
    global _server_state

    if is_ollama_running():
        log("Ollama is already running")
        _server_state.ollama_available = True
        return True

    if not shutil.which(str(OLLAMA_PATH)):
        log(f"Ollama executable not found: {OLLAMA_PATH}")
        _server_state.ollama_available = False
        return False

    log(f"Starting Ollama from {OLLAMA_PATH}...")
    try:
        # Set up environment with OLLAMA_NUM_PARALLEL for concurrent requests
        env = os.environ.copy()
        ollama_config = CONFIG.get("ollama", {})
        num_parallel = ollama_config.get("num_parallel", 4)
        env["OLLAMA_NUM_PARALLEL"] = str(num_parallel)
        log(f"Setting OLLAMA_NUM_PARALLEL={num_parallel}")

        subprocess.Popen(
            [str(OLLAMA_PATH), "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

        # Wait for Ollama to become available (up to 30 seconds)
        for i in range(30):
            time.sleep(1)
            if is_ollama_running():
                log(f"Ollama started successfully after {i+1}s")
                _server_state.ollama_available = True
                return True

        log("Ollama started but not responding within timeout")
        _server_state.ollama_available = False
        return False

    except Exception as e:
        log(f"Failed to start Ollama: {e}")
        _server_state.ollama_available = False
        return False


def ensure_ollama_available() -> bool:
    """
    Ensure Ollama is available, starting it if necessary.

    This is called lazily when embeddings are needed, not during startup.
    """
    global _server_state

    # If we already checked, return cached result
    if _server_state.ollama_available is not None:
        return _server_state.ollama_available

    # Check if running, start if not
    if is_ollama_running():
        _server_state.ollama_available = True
        return True

    return start_ollama()


def get_db():
    """Get database connection with timeout and WAL mode for better concurrency."""
    # Add timeout to prevent indefinite hangs on locked database
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    # Enable WAL mode for better concurrency (allows readers while writer is active)
    # This is idempotent - if already in WAL mode, it stays in WAL mode
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


class OllamaUnavailableError(Exception):
    """Raised when Ollama is not available and couldn't be started."""
    pass


def get_embedding(text: str, raise_on_unavailable: bool = False) -> list[float] | None:
    """
    Get embedding for text, ensuring Ollama is available first.

    Args:
        text: The text to embed
        raise_on_unavailable: If True, raise OllamaUnavailableError instead of returning None

    Returns:
        Embedding vector or None if unavailable

    Raises:
        OllamaUnavailableError: If raise_on_unavailable=True and Ollama isn't available
    """
    # Ensure Ollama is running before attempting to get embeddings
    if not ensure_ollama_available():
        msg = "Ollama is not running and could not be started automatically."
        log(msg)
        if raise_on_unavailable:
            raise OllamaUnavailableError(msg)
        return None

    try:
        response = requests.post(
            OLLAMA_URL,
            json={"input": text[:8000], "model": EMBEDDING_MODEL},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["embeddings"][0]
    except requests.exceptions.ConnectionError as e:
        msg = f"Cannot connect to Ollama at {OLLAMA_URL}. Is Ollama running?"
        log(msg)
        if raise_on_unavailable:
            raise OllamaUnavailableError(msg)
        return None
    except Exception as e:
        log(f"Embedding error: {e}")
        return None


def bm25_search(query: str, top_k: int = DEFAULT_TOP_K, file_filter: str = None) -> list[dict]:
    """BM25 search that includes embeddings in the query (for MCP server)."""
    return core_bm25_search(query, top_k, file_filter, get_db_func=get_db, include_embeddings=True)


@dataclass
class SearchResult:
    """Result of a hybrid search including any warnings."""
    results: list[dict]
    warnings: list[str]
    semantic_enabled: bool = True


def hybrid_search(query: str, top_k: int = DEFAULT_TOP_K, file_filter: str = None, use_semantic: bool = True) -> SearchResult:
    """
    Perform hybrid BM25 + semantic search.

    Returns a SearchResult with results and any warnings about degraded functionality.
    """
    warnings = []

    candidates = bm25_search(query, top_k, file_filter)
    if not candidates:
        return SearchResult(results=[], warnings=warnings, semantic_enabled=use_semantic)

    if not use_semantic:
        return SearchResult(results=candidates[:top_k], warnings=warnings, semantic_enabled=False)

    # Try to get query embedding
    query_embedding = None
    try:
        query_embedding = get_embedding(query, raise_on_unavailable=True)
    except OllamaUnavailableError as e:
        warnings.append(f"⚠️ Semantic search unavailable: {e}")
        warnings.append("Results are using keyword (BM25) search only. Start Ollama for better results.")
        return SearchResult(results=candidates[:top_k], warnings=warnings, semantic_enabled=False)

    if query_embedding is None:
        warnings.append("⚠️ Could not generate query embedding. Using keyword search only.")
        return SearchResult(results=candidates[:top_k], warnings=warnings, semantic_enabled=False)

    conn = get_db()
    embeddings_failed = 0

    for candidate in candidates:
        embedding = candidate.get("embedding")

        # Lazy embedding if not cached
        if embedding is None:
            embedding = get_embedding(candidate["content"])
            if embedding:
                c = conn.cursor()
                c.execute("UPDATE chunks SET embedding = ? WHERE id = ?",
                         (json.dumps(embedding), candidate["id"]))
                conn.commit()
            else:
                embeddings_failed += 1

        if embedding:
            candidate["semantic_score"] = cosine_similarity(query_embedding, embedding)
        else:
            candidate["semantic_score"] = 0.0

        max_bm25 = max(c["bm25_score"] for c in candidates) if candidates else 1
        normalized_bm25 = candidate["bm25_score"] / max_bm25 if max_bm25 > 0 else 0
        candidate["combined_score"] = BM25_WEIGHT * normalized_bm25 + SEMANTIC_WEIGHT * candidate["semantic_score"]

    conn.close()

    if embeddings_failed > 0:
        warnings.append(f"⚠️ {embeddings_failed} chunks missing embeddings - semantic scoring may be incomplete.")

    candidates.sort(key=lambda x: x["combined_score"], reverse=True)

    # Clean up response
    for c in candidates:
        c.pop("embedding", None)

    return SearchResult(results=candidates[:top_k], warnings=warnings, semantic_enabled=True)


def search_files(query: str, top_k: int = 20) -> list[dict]:
    """Search for files by name or path."""
    return core_search_files(query, top_k, get_db_func=get_db)


def get_stats() -> dict:
    """Get index statistics (MCP server format)."""
    stats = core_get_stats(get_db_func=get_db, include_db_size=False)
    # Convert to MCP server format
    return {
        "indexed_files": stats["files"],
        "total_chunks": stats["chunks"],
        "embedded_chunks": stats["embedded_chunks"],
        "embedding_coverage": stats["embedding_coverage"],
    }


# MCP Protocol Implementation
def handle_initialize(params):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "codebase-rag", "version": "1.0.0"}
    }


def handle_list_tools(params):
    return {
        "tools": [
            {
                "name": "search_codebase",
                "description": "Search the indexed codebase using hybrid BM25 + semantic search. Use this to find relevant code snippets, functions, classes, or documentation.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language search query (e.g., 'authentication logic', 'database connection', 'error handling')"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results to return (default: 10)",
                            "default": 10
                        },
                        "file_filter": {
                            "type": "string",
                            "description": "Optional: filter results to files matching this pattern (e.g., 'glass365-1', '.al', 'src/')"
                        },
                        "semantic": {
                            "type": "boolean",
                            "description": "Use semantic search in addition to keyword search (default: true)",
                            "default": True
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "find_files",
                "description": "Find files by name or path pattern in the indexed codebase.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "File name or path pattern to search for"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Maximum number of files to return (default: 20)",
                            "default": 20
                        }
                    },
                    "required": ["pattern"]
                }
            },
            {
                "name": "codebase_stats",
                "description": "Get statistics about the indexed codebase.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]
    }


def handle_call_tool(params):
    """Handle MCP tool calls with proper error reporting."""
    global _server_state

    tool_name = params.get("name")
    args = params.get("arguments", {})

    # Check if server is still initializing
    if _server_state.init_state == InitState.INITIALIZING:
        eta = _server_state.estimated_time_remaining()
        eta_msg = f" (estimated {eta:.0f}s remaining)" if eta else ""
        return {"content": [{"type": "text", "text":
            f"⏳ Server is still initializing{eta_msg}. Please try again in a moment.\n\n"
            f"The server needs to warm up the database connection after a cold start. "
            f"This typically happens after system boot or hibernate."
        }]}

    if tool_name == "search_codebase":
        query = args["query"]
        top_k = args.get("top_k", DEFAULT_TOP_K)
        file_filter = args.get("file_filter")
        use_semantic = args.get("semantic", True)

        # Check cache first
        cached_result = _search_cache.get(query, top_k, file_filter, use_semantic)
        cache_hit = cached_result is not None

        if cache_hit:
            search_result = cached_result
            log(f"Cache HIT for query: {query[:50]}...")
        else:
            search_result = hybrid_search(
                query=query,
                top_k=top_k,
                file_filter=file_filter,
                use_semantic=use_semantic
            )
            # Cache the result
            _search_cache.put(query, top_k, file_filter, use_semantic, search_result)
            log(f"Cache MISS for query: {query[:50]}...")

        output = []

        # Show warnings first if any
        if search_result.warnings:
            output.append("---")
            for warning in search_result.warnings:
                output.append(warning)
            output.append("---\n")

        if not search_result.results:
            output.append("No results found.")
            return {"content": [{"type": "text", "text": "\n".join(output)}]}

        # Show search mode indicator with cache status
        mode = "hybrid (BM25 + semantic)" if search_result.semantic_enabled else "keyword (BM25 only)"
        cache_indicator = " | cached" if cache_hit else ""
        output.append(f"*Search mode: {mode}{cache_indicator}*\n")

        for i, r in enumerate(search_result.results, 1):
            output.append(f"## Result {i}: {r['file_path']}\n")
            output.append(f"**Chunk {r['chunk_index']}** | Score: {r.get('combined_score', r.get('bm25_score', 0)):.3f}\n")
            output.append(f"```\n{r['content']}\n```\n")

        return {"content": [{"type": "text", "text": "\n".join(output)}]}

    elif tool_name == "find_files":
        results = search_files(args["pattern"], args.get("top_k", 20))

        if not results:
            return {"content": [{"type": "text", "text": "No files found."}]}

        output = ["Found files:\n"]
        for r in results:
            output.append(f"- {r['file_path']}")

        return {"content": [{"type": "text", "text": "\n".join(output)}]}

    elif tool_name == "codebase_stats":
        try:
            stats = get_stats()
            cache_stats = _search_cache.stats()

            output = ["Codebase Index Statistics:\n"]
            for k, v in stats.items():
                output.append(f"- {k}: {v}")

            output.append("\nSearch Cache Statistics:\n")
            output.append(f"- cache_size: {cache_stats['size']}/{cache_stats['maxsize']}")
            output.append(f"- cache_hits: {cache_stats['hits']}")
            output.append(f"- cache_misses: {cache_stats['misses']}")
            output.append(f"- cache_invalidations: {cache_stats['invalidations']}")
            output.append(f"- cache_hit_rate: {cache_stats['hit_rate']}")

            return {"content": [{"type": "text", "text": "\n".join(output)}]}
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                return {"content": [{"type": "text", "text": "Error: Database is currently locked. Please try again in a moment. The scheduled reindex task may be running."}]}
            return {"content": [{"type": "text", "text": f"Error reading database: {e}"}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error getting statistics: {e}"}]}

    else:
        return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}


def background_initialize():
    """
    Perform slow initialization tasks in background thread.

    This allows the MCP server to respond to protocol messages immediately
    while database warmup and stats collection happen asynchronously.
    """
    global _server_state

    _server_state.init_state = InitState.INITIALIZING
    _server_state.init_start_time = time.time()

    try:
        # Step 1: Warm up database connection and get stats
        # This is the slow part after cold boot - can take 10-30s for large DBs
        log("Background init: Warming up database connection...")
        stats = get_stats()
        _server_state.stats_cache = stats
        elapsed = time.time() - _server_state.init_start_time
        log(f"Background init: Database ready in {elapsed:.1f}s")
        log(f"Index: {stats['indexed_files']} files, {stats['total_chunks']} chunks, {stats['embedding_coverage']} embedded")

        # Step 2: Check Ollama availability (don't block on starting it)
        log("Background init: Checking Ollama availability...")
        if is_ollama_running():
            _server_state.ollama_available = True
            log("Background init: Ollama is running")
        else:
            log("Background init: Ollama not running (will auto-start on first embedding request)")
            # Don't set ollama_available to False - let it try to start on demand

        _server_state.init_state = InitState.READY
        total_elapsed = time.time() - _server_state.init_start_time
        log(f"Background init: Complete in {total_elapsed:.1f}s")

    except sqlite3.OperationalError as e:
        elapsed = time.time() - _server_state.init_start_time
        if "locked" in str(e).lower():
            log(f"Background init: Database locked after {elapsed:.1f}s, will retry on tool calls")
            _server_state.init_state = InitState.READY  # Allow tool calls to retry
            _server_state.init_error = "Database was locked during initialization"
        else:
            log(f"Background init: Database error after {elapsed:.1f}s: {e}")
            _server_state.init_state = InitState.FAILED
            _server_state.init_error = str(e)

    except Exception as e:
        elapsed = time.time() - _server_state.init_start_time
        log(f"Background init: Failed after {elapsed:.1f}s: {e}")
        _server_state.init_state = InitState.FAILED
        _server_state.init_error = str(e)


def handle_request_sync(request: dict, handlers: dict) -> dict:
    """
    Handle a single MCP request synchronously.

    This is the core request handling logic, extracted for reuse.
    Returns the JSON-RPC response dict.
    """
    method = request.get("method")
    params = request.get("params", {})
    req_id = request.get("id")

    log(f"Request: {method}")

    try:
        if method in handlers:
            result = handlers[method](params)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        else:
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    except Exception as e:
        log(f"Error handling request: {e}")
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}}


# Thread pool executor for running blocking handlers concurrently
_executor = None  # Initialized in async_main


async def handle_request_async(request: dict, handlers: dict) -> None:
    """
    Handle a single MCP request asynchronously.

    Runs the synchronous handler in a thread pool to avoid blocking
    the event loop, then writes the response with the output lock.
    """
    loop = asyncio.get_running_loop()

    # Run blocking handler in thread pool
    response = await loop.run_in_executor(
        _executor,
        handle_request_sync,
        request,
        handlers
    )

    # Write response with lock to prevent interleaving
    await write_response(response)


# Output lock to prevent response interleaving when we go async
_output_lock = asyncio.Lock()

# Queue for async stdin reading (populated by background thread)
_request_queue: asyncio.Queue = None  # Initialized in async_main


def stdin_reader_thread(queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
    """
    Background thread that reads from stdin and puts lines into async queue.

    This allows async code to await incoming requests on Windows,
    where native async stdin is not well supported.
    """
    try:
        for line in sys.stdin:
            # Strip UTF-8 BOM if present (some Windows shells add this)
            line = line.lstrip('\ufeff').strip()
            if line:
                # Thread-safe way to put item into asyncio queue
                loop.call_soon_threadsafe(queue.put_nowait, line)
    except Exception as e:
        log(f"stdin reader error: {e}")
    finally:
        # Signal end of input
        loop.call_soon_threadsafe(queue.put_nowait, None)


async def write_response(response: dict) -> None:
    """Write a JSON-RPC response to stdout with locking to prevent interleaving."""
    async with _output_lock:
        print(json.dumps(response), flush=True)


async def async_main():
    """
    Async main MCP server loop.

    Key design: The server responds to MCP protocol immediately.
    Slow initialization (database warmup, stats) happens in background.

    Step 3: Now dispatches requests concurrently using asyncio.create_task().
    Handlers run in thread pool executor to avoid blocking the event loop.
    """
    global _server_state, _request_queue, _executor

    log("Codebase RAG MCP Server starting (async)...")

    # Quick check: database file must exist
    if not DB_PATH.exists():
        log(f"Error: Database not found at {DB_PATH}")
        log("Run hybrid_indexer.py first to create the index.")
        sys.exit(1)

    log(f"Database: {DB_PATH}")

    # Initialize thread pool executor for running blocking handlers
    # Using 4 workers allows 4 concurrent requests to be processed
    _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mcp-handler")
    log("Thread pool executor initialized (4 workers)")

    # Start background initialization (database warmup, stats collection)
    # This is NON-BLOCKING - the MCP protocol loop starts immediately
    init_thread = threading.Thread(target=background_initialize, daemon=True)
    init_thread.start()
    log("Background initialization started")

    handlers = {
        "initialize": handle_initialize,
        "tools/list": handle_list_tools,
        "tools/call": handle_call_tool,
    }

    # Set up async stdin reading via background thread
    loop = asyncio.get_running_loop()
    _request_queue = asyncio.Queue()

    stdin_thread = threading.Thread(
        target=stdin_reader_thread,
        args=(_request_queue, loop),
        daemon=True
    )
    stdin_thread.start()
    log("Async stdin reader started")

    # Track pending tasks for graceful shutdown
    pending_tasks: set[asyncio.Task] = set()

    # MCP protocol loop - concurrent request dispatch
    while True:
        try:
            # Await next request from async queue
            line = await _request_queue.get()

            # None signals end of input (stdin closed)
            if line is None:
                log("stdin closed, waiting for pending tasks...")
                # Wait for all pending tasks to complete
                if pending_tasks:
                    await asyncio.gather(*pending_tasks, return_exceptions=True)
                log("All pending tasks completed, shutting down")
                break

            request = json.loads(line)

            # Dispatch request handler as concurrent task
            task = asyncio.create_task(
                handle_request_async(request, handlers),
                name=f"request-{request.get('id', 'unknown')}"
            )
            pending_tasks.add(task)

            # Remove completed tasks from pending set
            task.add_done_callback(pending_tasks.discard)

        except json.JSONDecodeError as e:
            log(f"JSON decode error: {e}")
        except Exception as e:
            log(f"Error: {e}")

    # Cleanup
    _executor.shutdown(wait=False)


def main():
    """
    Entry point - runs the async main loop.

    This wrapper exists for compatibility and to handle the asyncio.run() call.
    """
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        log("Server shutdown requested")
    except Exception as e:
        log(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
