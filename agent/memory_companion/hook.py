"""
Memory Companion hook for UserPromptSubmit.

Fires before Claude processes the pulse prompt. Extracts topics,
runs BM25 queries against RAG, and injects brief pointers to
relevant past context. The pulse instance decides whether to follow up
using its RAG MCP tool.

Does NOT inject memory content. Only suggests queries with top match hints.
The model's own intelligence decides what's worth retrieving.
"""

import importlib.util
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("memory_companion.hook")

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Minimum BM25 score for a result to count as a strong match
STRONG_MATCH_SCORE = 5.0
# Minimum BM25 score for feeling queries (lower bar — more exploratory)
FEELING_MATCH_SCORE = 2.0
# Maximum number of pointer lines to inject
MAX_POINTERS = 4
# Maximum queries to run
MAX_QUERIES = 8

# Cached RAG module reference (loaded once per process)
_rag_module = None


def _get_rag_search():
    """Import RAG BM25 search via importlib (no sys.path pollution)."""
    global _rag_module

    if _rag_module is not None:
        return _rag_module.bm25_search

    rag_path = PROJECT_ROOT / ".claude-rag"
    hybrid_search_file = rag_path / "hybrid_search.py"
    if not hybrid_search_file.exists():
        return None

    try:
        # Load search_core first (hybrid_search depends on it)
        core_file = rag_path / "search_core.py"
        core_spec = importlib.util.spec_from_file_location(
            "search_core", core_file,
            submodule_search_locations=[str(rag_path)],
        )
        core_mod = importlib.util.module_from_spec(core_spec)
        import sys
        sys.modules["search_core"] = core_mod
        core_spec.loader.exec_module(core_mod)

        # Now load hybrid_search
        spec = importlib.util.spec_from_file_location(
            "hybrid_search", hybrid_search_file,
            submodule_search_locations=[str(rag_path)],
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        _rag_module = mod
        return mod.bm25_search
    except Exception as e:
        log.warning(f"Could not load RAG search: {e}")
        return None


def _sanitize_query(query: str) -> str:
    """Clean query for FTS5 compatibility.

    FTS5 chokes on certain punctuation and operators.
    Strip them to get a clean keyword query.
    """
    # Remove punctuation that breaks FTS5 (keep alphanumeric, spaces, hyphens)
    cleaned = re.sub(r"[^\w\s-]", " ", query)
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _query_rag(search_fn, query: str, top_k: int = 3) -> list[dict]:
    """Run a single BM25 query and return results."""
    clean = _sanitize_query(query)
    if not clean or len(clean) < 3:
        return []
    try:
        return search_fn(clean, top_k=top_k)
    except Exception as e:
        log.warning(f"RAG query failed for '{clean}': {e}")
        return []


def _shorten_path(path: str) -> str:
    """Make file paths relative and readable."""
    root_str = str(PROJECT_ROOT)
    if path.startswith(root_str):
        return path[len(root_str) + 1:]
    return path.split("/")[-1]


def _extract_hint(content: str, max_len: int = 100) -> str:
    """Extract a short relevance hint from chunk content.

    Grabs the first non-empty, non-header line as a one-line summary.
    """
    for line in content.split("\n"):
        line = line.strip()
        # Skip empty lines, headers, metadata, separators
        if not line or line.startswith("#") or line.startswith("*") or line.startswith("---"):
            continue
        if len(line) < 10:
            continue
        # Truncate to max_len
        if len(line) > max_len:
            return line[:max_len].rsplit(" ", 1)[0] + "..."
        return line
    return ""


def _build_pointer(query: str, results: list[dict], origin: str, min_score: float) -> dict | None:
    """Build a pointer dict if results are strong enough."""
    strong = [r for r in results if r.get("bm25_score", 0) >= min_score]
    if not strong:
        return None

    top = strong[0]
    top_path = _shorten_path(top.get("file_path", "unknown"))
    top_score = top.get("bm25_score", 0)
    hint = _extract_hint(top.get("content", ""))

    return {
        "query": query,
        "top_path": top_path,
        "score": round(top_score, 1),
        "count": len(strong),
        "origin": origin,
        "hint": hint,
    }


def _build_injection(pointers: list[dict]) -> str:
    """Format pointer lines into the additionalContext string."""
    if not pointers:
        return ""

    lines = [
        "## Memory Companion",
        "",
        "Past context that might connect. Use `mcp__codebase-rag__search_codebase` "
        "to retrieve — or ignore entirely.",
        "",
    ]

    for p in pointers[:MAX_POINTERS]:
        query = p["query"]
        top_path = p["top_path"]
        origin = p.get("origin", "")
        count = p["count"]
        hint = p.get("hint", "")

        display_query = query[:80] + "..." if len(query) > 80 else query
        line = f"- `\"{display_query}\"` → `{top_path}`"
        if count > 1:
            line += f" (+{count - 1} more)"
        if hint:
            line += f"\n  *{hint}*"
        if origin:
            line += f" [{origin}]"
        lines.append(line)

    return "\n".join(lines)


async def memory_companion_hook(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """UserPromptSubmit hook: scan prompt, suggest RAG queries.

    Called by the Agent SDK before Claude processes the pulse prompt.
    """
    prompt = input_data.get("prompt", "")
    if not prompt:
        return {}

    from memory_companion.extractor import extract_topics
    from memory_companion.state import apply_decay, is_suppressed, record_offered

    # Step 1: Apply decay to previously offered queries
    apply_decay()

    # Step 2: Extract topics
    topics = extract_topics(prompt)

    # Step 3: Get RAG search
    search_fn = _get_rag_search()
    if search_fn is None:
        log.warning("RAG search not available")
        return {}

    # Step 4: Build query plan with priority
    # Priority 1: [HUMAN]'s instructions (most specific, use as direct query)
    # Priority 2: Feeling-based queries (exploratory, lower threshold)
    # Priority 3: Category terms (broad, high threshold required)
    query_plan = []

    instructions = topics.get("instructions_text", "")
    if instructions and len(instructions) > 10:
        query_plan.append({
            "query": instructions[:200],  # BM25 handles long queries fine
            "min_score": FEELING_MATCH_SCORE,
            "origin": "instructions",
        })

    for fq in topics.get("feeling_queries", []):
        query_plan.append({
            "query": fq,
            "min_score": FEELING_MATCH_SCORE,
            "origin": f"feeling: {topics.get('feeling', '?')}",
        })

    for cat in topics.get("categories", []):
        query_plan.append({
            "query": cat,
            "min_score": STRONG_MATCH_SCORE,
            "origin": "topic",
        })

    # Step 5: Run queries, skip suppressed
    pointers = []
    queries_run = 0
    offered_queries = []

    for qp in query_plan:
        if queries_run >= MAX_QUERIES:
            break
        query = qp["query"]
        if is_suppressed(query):
            continue

        results = _query_rag(search_fn, query)
        queries_run += 1

        pointer = _build_pointer(query, results, qp["origin"], qp["min_score"])
        if pointer:
            pointers.append(pointer)
            offered_queries.append(query)

    # Step 6: Record and format
    if offered_queries:
        record_offered(offered_queries)

    injection = _build_injection(pointers)
    if not injection:
        log.info("Memory companion: no relevant pointers to offer")
        return {}

    log.info(
        f"Memory companion: offering {len(pointers)} pointers "
        f"({queries_run} queries run)"
    )

    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": injection,
        }
    }
