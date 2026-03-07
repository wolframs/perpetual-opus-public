# MCP Server Parallel Performance Roadmap

**Date:** 2025-12-16
**Status:** ✅ COMPLETE - Phases 1 & 3 Implemented

## Problem Statement

When Claude Code spawns multiple explore agents in parallel (3-5 agents), they all make concurrent requests to the codebase-rag MCP server. Currently:

1. Agent 1 gets priority and receives responses sequentially
2. Agents 2-4 must wait for Agent 1's requests to complete
3. This creates a significant bottleneck for context-intensive tasks

## Current Architecture Bottlenecks

### 1. MCP Server is Synchronous
```python
for line in sys.stdin:  # One request at a time
    result = handlers[method](params)  # Blocks until complete
    print(json.dumps(response))
```
- Single-threaded stdin loop
- Each request blocks until complete
- No concurrent request handling

### 2. Ollama Embedding Requests are Sequential
- Each `get_embedding()` call is a blocking HTTP request
- Multiple search requests = serial embedding calls
- No batching of embedding requests

### 3. No Result Caching
- Identical queries from different agents compute results from scratch
- No memoization of recent searches

### 4. Database (Not a bottleneck)
- SQLite WAL mode handles concurrent reads well
- Connection per query is fine for current load

## Proposed Solutions

### Phase 1: Quick Wins (Low effort, immediate impact)

#### 1.1 Result Caching
Add LRU cache for search results:
```python
from functools import lru_cache

@lru_cache(maxsize=100)
def cached_search(query: str, top_k: int, file_filter: str | None, use_semantic: bool) -> SearchResult:
    return hybrid_search(query, top_k, file_filter, use_semantic)
```

**Benefits:**
- If Agent 2 asks the same query as Agent 1, instant response
- Zero additional latency for cache hits
- Memory bounded by maxsize

#### 1.2 Ollama Parallel Configuration
Configure Ollama to handle parallel embedding requests:
```bash
OLLAMA_NUM_PARALLEL=4 ollama serve
```

Or set in environment/startup script.

**Benefits:**
- Multiple embedding requests can be processed concurrently
- No code changes to MCP server required
- Immediate improvement for semantic search

### Phase 2: Embedding Batching (Medium effort)

#### 2.1 Batch Embedding Requests
Ollama's `/api/embed` endpoint supports batching:
```python
# Instead of 5 separate calls:
response = requests.post(OLLAMA_URL, json={
    "input": ["text1", "text2", "text3", "text4", "text5"],
    "model": EMBEDDING_MODEL
})
embeddings = response.json()["embeddings"]  # Returns list
```

#### 2.2 Request Coalescing
Collect embedding requests within a time window and batch them:
```python
class EmbeddingBatcher:
    def __init__(self, max_batch_size=10, max_wait_ms=50):
        self.pending = []
        self.max_batch_size = max_batch_size
        self.max_wait_ms = max_wait_ms

    async def get_embedding(self, text: str) -> list[float]:
        # Add to pending, wait for batch or timeout
        # Submit batch when full or timeout reached
```

**Benefits:**
- Reduces HTTP overhead
- Better GPU utilization in Ollama
- Smoother latency under load

### Phase 3: Async MCP Server (Larger refactor)

#### 3.1 Async Request Handling
Rewrite MCP server to use asyncio:
```python
import asyncio

async def main():
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        # Handle each request concurrently
        asyncio.create_task(handle_request(json.loads(line)))
```

#### 3.2 Connection Pooling
```python
class ConnectionPool:
    def __init__(self, db_path: Path, size: int = 5):
        self.pool = asyncio.Queue()
        for _ in range(size):
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            self.pool.put_nowait(conn)

    async def acquire(self) -> sqlite3.Connection:
        return await self.pool.get()

    async def release(self, conn: sqlite3.Connection):
        await self.pool.put(conn)
```

**Benefits:**
- True concurrent request handling
- Multiple agents served simultaneously
- Better resource utilization

### Phase 4: Advanced Optimizations (Future)

- **Query similarity detection:** If queries are semantically similar, return cached results
- **Predictive caching:** Pre-cache common query patterns
- **Distributed caching:** Redis for multi-instance deployments
- **Streaming results:** Return partial results as they're found

## Implementation Priority

| Phase | Effort | Impact | Status |
|-------|--------|--------|--------|
| 1.1 Result Caching | Low | High | ✅ Complete |
| 1.2 Ollama Parallel | Low | Medium | ✅ Complete |
| 2.1 Batch Embeddings | Medium | Medium | Skipped (not needed) |
| 2.2 Request Coalescing | Medium | Medium | Skipped (not needed) |
| 3.1 Async Server | High | High | ✅ Complete |
| 3.2 Connection Pool | Medium | Low | Skipped (ThreadPool approach) |

## Metrics to Track

- Average request latency (p50, p95, p99)
- Cache hit rate
- Concurrent request count
- Time to first result for parallel agents
- Ollama embedding throughput

## Notes

- The MCP protocol uses JSON-RPC with request IDs, which inherently supports concurrent requests
- SQLite WAL mode is already enabled and handles concurrent reads well
- Ollama embedding for nomic-embed-text is fast (~50-100ms per text), batching has diminishing returns for small batches
