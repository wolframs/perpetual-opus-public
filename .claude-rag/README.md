# Claude Code RAG - Local Codebase Search

A hybrid Retrieval-Augmented Generation (RAG) system for Claude Code CLI that enables fast semantic and keyword search across large codebases.

**Platform note:** This README was originally written for Windows. The system now also runs on macOS (Ollama + launchd). Core concepts (Ollama embeddings, BM25+semantic hybrid) are cross-platform; the setup commands below are Windows-specific. For macOS: use `brew install ollama`, standard `pip install`, and launchd or cron for scheduling.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Claude Code CLI                             │
│                            │                                     │
│                    MCP Protocol (stdio)                          │
│                            │                                     │
│                            ▼                                     │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │              codebase-rag MCP Server (async)                ││
│  │                  (mcp_server.py)                            ││
│  │                                                             ││
│  │  Features:                                                  ││
│  │  • Concurrent request handling (4 workers)                  ││
│  │  • Non-blocking cold-start (responds immediately)           ││
│  │  • Ollama auto-start if not running                         ││
│  │  • Search result caching with TTL                           ││
│  │                                                             ││
│  │  Tools:                                                     ││
│  │  • search_codebase - Hybrid BM25 + semantic search          ││
│  │  • find_files      - File name/path search                  ││
│  │  • codebase_stats  - Index statistics + cache info          ││
│  └─────────────────────────────────────────────────────────────┘│
│                            │                                     │
│              ┌─────────────┴─────────────┐                       │
│              ▼                           ▼                       │
│  ┌───────────────────┐       ┌───────────────────┐              │
│  │   SQLite + FTS5   │       │      Ollama       │              │
│  │   (codebase.db)   │       │ (nomic-embed-text)│              │
│  │                   │       │                   │              │
│  │  • BM25 keyword   │       │  • 768-dim vectors│              │
│  │  • Chunk storage  │       │  • GPU accelerated│              │
│  │  • Embedding cache│       │  • Lazy generation│              │
│  └───────────────────┘       └───────────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

### Concurrent Request Handling

The MCP server uses asyncio with a thread pool to handle multiple requests concurrently:

```
stdin ──► stdin_reader_thread ──► asyncio.Queue ──► async_main loop
                                                          │
                    ┌─────────────────────────────────────┘
                    ▼
        asyncio.create_task(handle_request_async)
                    │
                    ▼
        ThreadPoolExecutor(4 workers) ──► handle_request_sync
                    │
                    ▼
        _output_lock ──► print(json.dumps(response))
```

This enables multiple Claude Code explore agents to query the codebase simultaneously.

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Vector Store | SQLite + FTS5 | BM25 search + chunk storage + embedding cache |
| Embeddings | Ollama (nomic-embed-text) | 768-dimensional vectors, GPU-accelerated |
| MCP Server | Python (asyncio + ThreadPool) | Concurrent request handling, cold-start resilience |
| Scheduling | Windows Task Scheduler | Automatic incremental re-indexing |

### Why This Stack?

- **SQLite over ChromaDB/Milvus**: No server process needed, single file, FTS5 provides instant BM25 search
- **Hybrid Search**: BM25 catches exact keyword matches, embeddings catch semantic similarity
- **Lazy Embeddings**: Only generate embeddings for chunks that are actually retrieved (saves GPU time)
- **nomic-embed-text over qwen3-embedding**: 17x smaller (274MB vs 4.7GB), 768 vs 4096 dimensions, much faster

### MCP Server Features

**Cold-Start Resilience:**
- Server responds to MCP protocol immediately (non-blocking initialization)
- Database warmup and stats collection happens in background thread
- No 30-second timeout failures after system reboot/hibernate

**Ollama Auto-Start:**
- Automatically starts Ollama if not running when server initializes
- Falls back to BM25-only search with warning if Ollama unavailable
- Clear warnings shown in search results when semantic search is degraded

**Search Result Caching:**
- LRU cache with configurable TTL (default: 5 minutes)
- Automatic invalidation when database is modified (mtime check)
- Cache stats visible in `codebase_stats` tool output

**Concurrent Request Handling:**
- 4-worker thread pool processes requests in parallel
- Multiple explore agents get responses simultaneously
- Output lock prevents response interleaving

## Storage Location

```
%USERPROFILE%\.claude-rag\          (C:\Users\<username>\.claude-rag\)
├── config.json                     # All settings (copy from config.json.example)
├── config.json.example             # Template for new installations
├── codebase.db                     # SQLite database (BM25 index + embeddings)
├── mcp_server.py                   # MCP server for Claude Code (async)
├── hybrid_indexer.py               # Initial full indexing script
├── hybrid_search.py                # Search module (CLI + library)
├── preembed.py                     # Pre-embed priority folders
├── scheduled_reindex.py            # Incremental re-indexer (fault tolerant)
├── reindex_repo.py                 # Single-repo re-indexer (git hooks)
├── install_hooks.py                # Installs git post-checkout hooks
├── setup_scheduled_task.ps1        # Windows Task Scheduler setup
├── migrate_db.py                   # Database migration helper
├── verify_implementation.py        # Implementation verification
├── reindex.log                     # Re-indexing logs
├── reindex.lock                    # Lock file (prevents concurrent runs)
├── tests/                          # Test suite (55 tests)
│   └── test_mcp_server_coldstart.py
└── docs/                           # Documentation
    ├── 2025-12-16-asyncio-refactor-plan.md
    └── 2025-12-16-parallel-performance-roadmap.md
```

---

# Operator Handbook

## 1. Initial Setup

### 1.1 Install Ollama

Download and install from: https://ollama.com/download/windows

Or via winget:
```powershell
winget install Ollama.Ollama
```

Pull the embedding model:
```powershell
ollama pull nomic-embed-text
```

### 1.2 Install Python Dependencies

```powershell
pip install numpy requests win11toast
```

Note: `win11toast` is optional but required for error notifications from the scheduled task.

### 1.3 Configure

```powershell
copy %USERPROFILE%\.claude-rag\config.json.example %USERPROFILE%\.claude-rag\config.json
```

Edit `config.json` to set your directories, paths, and preferences.

### 1.4 Run Initial Indexing

```powershell
python %USERPROFILE%\.claude-rag\hybrid_indexer.py
```

This creates the SQLite database with BM25 full-text search. Takes ~6 minutes for ~65k files.

### 1.5 Register MCP Server with Claude Code

```powershell
claude mcp add codebase-rag -s user -- python %USERPROFILE%\.claude-rag\mcp_server.py
```

Verify registration:
```powershell
claude mcp list
```

### 1.6 Restart Claude Code

Start a new Claude Code session. The `codebase-rag` tools should now be available.

---

## 2. Pre-Embedding Priority Folders

For frequently searched folders, pre-compute embeddings for faster semantic search:

```powershell
python %USERPROFILE%\.claude-rag\preembed.py <folder-name>
```

Example:
```powershell
python %USERPROFILE%\.claude-rag\preembed.py glass365-1
python %USERPROFILE%\.claude-rag\preembed.py glass365-1 another-project
```

To set default priority folders, edit `config.json`:
```json
"preembed": {
  "priority_folders": ["glass365-1", "your-other-project"]
}
```

---

## 3. Git Hook Auto-Reindex

Automatically re-index repositories when switching branches.

### 3.1 Install Hooks

```powershell
python %USERPROFILE%\.claude-rag\install_hooks.py
```

This discovers all git repositories in indexed directories and installs `post-checkout` hooks.
- Safe to re-run (idempotent)
- Appends to existing hooks without overwriting
- Hooks trigger background re-indexing on branch switch

### 3.2 Manual Repo Re-index

```powershell
python %USERPROFILE%\.claude-rag\reindex_repo.py "C:\path\to\repo"
```

---

## 4. Scheduled Re-Indexing

### 4.1 Setup Windows Task Scheduler

Run as Administrator:
```powershell
powershell -ExecutionPolicy Bypass -File "%USERPROFILE%\.claude-rag\setup_scheduled_task.ps1"
```

This creates a task that:
- Runs 2 minutes after logon
- Repeats every 2 hours
- Processes max 500 files or 2 minutes per run
- Runs silently (no terminal window) using `pythonw.exe`
- Shows Windows notification ONLY on errors (requires `pip install win11toast`)
- Safe to interrupt (fault tolerant)

### 4.2 Manual Commands

Run re-indexing manually:
```powershell
schtasks /run /tn ClaudeCodeRAG-Reindex
```

View task status:
```powershell
schtasks /query /tn ClaudeCodeRAG-Reindex
```

Remove task:
```powershell
schtasks /delete /tn ClaudeCodeRAG-Reindex /f
```

### 4.3 View Logs

```powershell
Get-Content %USERPROFILE%\.claude-rag\reindex.log -Tail 50
```

---

## 5. Using the RAG Tools

Once configured, Claude Code has access to these tools:

### search_codebase

Hybrid BM25 + semantic search across the indexed codebase.

Parameters:
- `query` (required): Natural language search query
- `top_k` (optional): Number of results (default: 10)
- `file_filter` (optional): Filter by file path pattern
- `semantic` (optional): Enable semantic search (default: true)

### find_files

Find files by name or path pattern.

Parameters:
- `pattern` (required): File name or path pattern
- `top_k` (optional): Max results (default: 20)

### codebase_stats

Get statistics about the indexed codebase.

---

## 6. Configuration Reference

All settings are in `config.json`. Key sections:

| Section | Settings |
|---------|----------|
| `indexing.directories` | Paths to index |
| `indexing.indexable_extensions` | File types to include |
| `indexing.skip_dirs` | Directories to ignore |
| `embedding.embedding_model` | Ollama model name |
| `search.bm25_weight` / `semantic_weight` | Ranking balance |
| `preembed.priority_folders` | Folders to pre-embed |
| `scheduled_reindex.max_files_per_run` | Batch limit per run |
| `mcp_server.cache_maxsize` | Search result cache size (default: 100) |
| `mcp_server.cache_ttl_seconds` | Cache TTL in seconds (default: 300) |
| `ollama.executable_path` | Path to Ollama executable (for auto-start) |
| `ollama.num_parallel` | Parallel embedding requests (default: 4) |

---

## 7. Troubleshooting

### MCP Server Not Loading

1. Check registration:
   ```powershell
   claude mcp list
   ```

2. Test server manually:
   ```powershell
   python %USERPROFILE%\.claude-rag\mcp_server.py
   ```
   (Should wait for JSON input on stdin)

3. Check Claude Code config:
   ```powershell
   type %USERPROFILE%\.claude.json | findstr codebase-rag
   ```

### Ollama Not Running

Check if Ollama is running:
```powershell
tasklist | findstr ollama
```

Start Ollama:
```powershell
ollama serve
```

Or click the Ollama icon in system tray.

### Database Locked

If you see "database is locked" errors:
```powershell
del %USERPROFILE%\.claude-rag\reindex.lock
```

### Re-index From Scratch

To rebuild the entire index:
```powershell
del %USERPROFILE%\.claude-rag\codebase.db
python %USERPROFILE%\.claude-rag\hybrid_indexer.py
```

### MCP Server Not Responding After Reboot

The server has cold-start resilience, but if issues persist:
1. Check MCP server logs for errors
2. Verify Ollama can be started: `ollama serve`
3. Reconnect MCP: `/mcp` in Claude Code

### Clear Search Cache

The cache auto-invalidates when the database changes. To force clear:
```powershell
# Restart Claude Code session, or use /mcp to reconnect
```

---

## 8. Performance Tuning

All tuning via `config.json`:

```json
{
  "preembed": { "batch_size": 256 },
  "scheduled_reindex": {
    "max_files_per_run": 500,
    "max_runtime_seconds": 120
  },
  "search": {
    "bm25_weight": 0.4,
    "semantic_weight": 0.6
  },
  "mcp_server": {
    "cache_maxsize": 100,
    "cache_ttl_seconds": 300
  },
  "ollama": {
    "num_parallel": 4
  }
}
```

---

## 9. File Inventory

| File | Purpose |
|------|---------|
| `config.json` | All settings (directories, models, weights, cache) |
| `config.json.example` | Template for new installations |
| `codebase.db` | SQLite database with FTS5 index and embeddings |
| `mcp_server.py` | Async MCP server with concurrent request handling |
| `hybrid_indexer.py` | Initial full indexing (creates database) |
| `hybrid_search.py` | Search library + CLI testing tool |
| `preembed.py` | Pre-compute embeddings for priority folders |
| `scheduled_reindex.py` | Incremental re-indexer with failed file retry |
| `reindex_repo.py` | Single-repo re-indexer (called by git hooks) |
| `install_hooks.py` | Installs git post-checkout hooks in all repos |
| `setup_scheduled_task.ps1` | Creates Windows scheduled task |
| `migrate_db.py` | Database schema migration helper |
| `verify_implementation.py` | Implementation verification script |
| `reindex.log` | Log file for scheduled and hook-triggered runs |
| `reindex.lock` | Lock file preventing concurrent runs |
| `tests/test_mcp_server_coldstart.py` | Test suite (55 tests) |
| `docs/*.md` | Development documentation and plans |

---

## 10. Running Tests

The test suite verifies cold-start resilience, caching, and concurrent request handling.

```powershell
cd %USERPROFILE%\.claude-rag
python -m pytest tests/ -v
```

Test coverage:
- Server state and initialization
- Ollama auto-start functionality
- Search result caching with TTL and invalidation
- Async stdin/stdout handling
- Concurrent request dispatch
- Integration tests for parallel execution
