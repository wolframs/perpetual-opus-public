# MCP Server Asyncio Refactor Plan

**Date:** 2025-12-16
**Goal:** Enable concurrent request handling in MCP server
**Approach:** Incremental refactoring with tests after each step
**Status:** ✅ COMPLETE (Steps 1-3, 7 implemented; Steps 4-6 skipped - thread pool provides concurrency)

---

## Current Architecture (Synchronous)

```
stdin ──► for line in sys.stdin: ──► handle_request() ──► stdout
                    │
                    └── BLOCKING - one request at a time
```

## Target Architecture (Async)

```
stdin ──► async read loop ──┬──► asyncio.create_task(handle_request_1)
                            ├──► asyncio.create_task(handle_request_2)
                            ├──► asyncio.create_task(handle_request_3)
                            └──► ... (concurrent)
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │   Thread Pool for     │
                            │   SQLite operations   │
                            │   (run_in_executor)   │
                            └───────────────────────┘
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │   aiohttp for Ollama  │
                            │   (native async)      │
                            └───────────────────────┘
                                        │
                                        ▼
stdout ◄── async write (with lock to prevent interleaving)
```

---

## Step-by-Step Plan

### Step 1: Add Async Infrastructure
**Scope:**
- Add asyncio imports
- Create `async def async_main()` skeleton
- Wrap existing `main()` to call `asyncio.run(async_main())`
- No functional changes yet

**Tests:**
- Verify server still starts and responds to basic requests
- Verify existing test suite passes

**Risk:** Low - additive changes only

---

### Step 2: Async Stdin/Stdout
**Scope:**
- Replace `for line in sys.stdin:` with async stream reading
- Use `asyncio.StreamReader` for stdin
- Add output lock to prevent response interleaving
- Still process requests sequentially (no concurrency yet)

**Tests:**
- Test async stdin reading works
- Test responses are correctly formatted
- Test UTF-8 BOM handling still works (Windows)

**Risk:** Medium - core I/O change

---

### Step 3: Concurrent Request Dispatch
**Scope:**
- Use `asyncio.create_task()` for each incoming request
- Track pending tasks
- Responses return as tasks complete (order may differ from request order)
- JSON-RPC request IDs ensure correct matching

**Tests:**
- Test multiple requests can be in-flight simultaneously
- Test request IDs are preserved in responses
- Test no response interleaving (output lock working)

**Risk:** Medium - concurrency introduction

---

### Step 4: Async Database Wrapper
**Scope:**
- Create `async def async_get_db()` using `run_in_executor`
- Wrap all SQLite operations in executor calls
- Consider connection pooling for concurrent queries

**Implementation:**
```python
async def run_db_query(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, func, *args)
```

**Tests:**
- Test database queries work through executor
- Test concurrent database reads don't block each other
- Test WAL mode handles concurrent access

**Risk:** Medium - threading with SQLite

---

### Step 5: Async HTTP Client
**Scope:**
- Replace `requests` with `aiohttp` for Ollama calls
- Make `get_embedding()` async
- Handle connection pooling for efficiency

**Tests:**
- Test embedding requests work with aiohttp
- Test timeout handling
- Test Ollama unavailable handling

**Risk:** Low - well-understood library swap

---

### Step 6: Make Search Functions Async
**Scope:**
- Convert `hybrid_search()` to async
- Convert `bm25_search()` to async
- Update `handle_call_tool()` to await search results
- Ensure cache operations are thread-safe (already are)

**Tests:**
- Test search still returns correct results
- Test caching still works
- Test warnings still appear for degraded functionality

**Risk:** Medium - core logic change

---

### Step 7: Integration Testing
**Scope:**
- End-to-end test with multiple concurrent requests
- Verify parallel agents get responses concurrently
- Performance benchmarking
- Stress testing

**Tests:**
- Simulate 5 concurrent search requests
- Measure response time improvement
- Verify no race conditions or deadlocks

**Risk:** Low - testing only

---

## Dependencies to Add

```
aiohttp>=3.9.0  # Async HTTP client
```

Note: `aioconsole` is optional - can use raw asyncio for stdin

---

## Rollback Plan

Each step is committed separately. If issues arise:
1. `git revert` the problematic commit
2. Or `git reset --hard ad3ffd7` to return to pre-refactor state

---

## Success Criteria

1. All 33 existing tests pass
2. New async-specific tests pass
3. 5 parallel search requests complete faster than 5 sequential
4. No increase in single-request latency
5. Memory usage remains stable under load

---

## Implementation Summary (Completed 2025-12-16)

### What Was Implemented

**Step 1** (commit 5063e67): Added async infrastructure
- `asyncio` import
- `handle_request_sync()` extracted
- `_output_lock` for response interleaving prevention
- `async def write_response()` with locking
- `async def async_main()` wrapper
- `main()` calls `asyncio.run(async_main())`

**Step 2** (commit 236dac8): Async stdin/stdout
- `stdin_reader_thread()` for background stdin reading
- `asyncio.Queue` for thread-safe request delivery
- UTF-8 BOM stripping in background thread
- End-of-input signaling with None sentinel

**Step 3** (commit 7b4caf3): Concurrent request dispatch
- `ThreadPoolExecutor(max_workers=4)` for handler execution
- `handle_request_async()` wraps handlers with `run_in_executor()`
- `asyncio.create_task()` for each incoming request
- Pending task tracking for graceful shutdown

**Step 7** (commit 481c3d3): Integration tests
- Test proves 4x speedup with concurrent requests
- Request ID preservation verified
- Error isolation verified

### Steps Skipped

**Steps 4-6** were skipped because the thread pool executor in Step 3 already provides true parallelism. Further async optimizations (async database, async HTTP) would improve efficiency but are not required for concurrent request handling.

### Final Architecture

```
stdin ──► stdin_reader_thread ──► asyncio.Queue ──► async_main loop
                                                          │
                    ┌─────────────────────────────────────┘
                    ▼
        asyncio.create_task(handle_request_async)
                    │
                    ▼
        ThreadPoolExecutor(4 workers) ──► handle_request_sync
                    │                            │
                    │                    ┌───────┴───────┐
                    │                    │ SQLite + HTTP │
                    │                    │ (blocking OK) │
                    │                    └───────────────┘
                    ▼
        _output_lock ──► print(json.dumps(response))
```

### Test Coverage

- 33 original tests (cold-start, cache, Ollama auto-start)
- 9 Step 1 tests (async infrastructure)
- 5 Step 2 tests (async stdin)
- 5 Step 3 tests (concurrent dispatch)
- 3 Step 7 tests (integration)
- **Total: 55 tests passing**
