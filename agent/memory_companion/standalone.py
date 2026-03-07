"""
Standalone CLI wrapper for memory companion.

Called from the windowsill-web TypeScript backend via child_process.execFile.
Takes a user message, runs BM25 queries against RAG, returns JSON with
pointer injection (or empty injection if nothing relevant).

Usage:
    MEMORY_COMPANION_MESSAGE="user message" python -m memory_companion.standalone
    python -m memory_companion.standalone "user message"

Returns JSON to stdout:
    {"success": true, "injection": "## Memory Companion\\n..."}
    {"success": true, "injection": ""}
    {"success": false, "error": "description"}
"""

import json
import logging
import os
import sys
from pathlib import Path

# Ensure agent/ is on sys.path so memory_companion resolves
_agent_dir = str(Path(__file__).parent.parent)
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)

# Silence logging to stderr so only JSON goes to stdout
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

# Minimum message length to attempt raw-message BM25 query
RAW_MESSAGE_MIN_LENGTH = 80
# BM25 score threshold for raw message queries (very high — filter noise)
RAW_MESSAGE_THRESHOLD = 12.0


def get_injection(user_message: str) -> str:
    """
    Get memory companion injection for a windowsill user message.

    Uses a focused query strategy for conversational text:
    1. Issue/file references explicitly mentioned (high signal)
    2. Feeling-based queries from interoception state (exploratory)
    3. Raw message as BM25 query (only if long + specific, very high threshold)

    NOTE: Category keyword matching is deliberately excluded here.
    It was designed for structured pulse prompts, not conversational text.
    Words like "arrival", "server", "write" match categories but carry
    no useful signal in casual messages like "How's arrival?"
    """
    from memory_companion.hook import (
        _get_rag_search, _query_rag, _build_pointer, _build_injection,
        FEELING_MATCH_SCORE, MAX_QUERIES,
    )
    from memory_companion.extractor import (
        _read_feeling, _extract_issue_refs,
        _extract_file_refs, FEELING_QUERIES,
    )
    from memory_companion.state import (
        is_suppressed, record_offered,
    )

    # NOTE: No apply_decay() here. The windowsill is a separate interaction
    # channel — its messages should not decay heartbeat companion state.
    # Decay happens per-pulse in the heartbeat hook.

    # Build query plan (focused, high-signal only)
    query_plan = []

    # Layer 1: Issue and file references mentioned in the message
    for ref in _extract_issue_refs(user_message):
        query_plan.append({
            "query": ref,
            "min_score": FEELING_MATCH_SCORE,
            "origin": "issue-ref",
        })
    for ref in _extract_file_refs(user_message):
        query_plan.append({
            "query": ref,
            "min_score": FEELING_MATCH_SCORE,
            "origin": "file-ref",
        })

    # Layer 2: Feeling-based queries from interoception state
    feeling = _read_feeling()
    if feeling and feeling != "neutral":
        for fq in FEELING_QUERIES.get(feeling, []):
            query_plan.append({
                "query": fq,
                "min_score": FEELING_MATCH_SCORE,
                "origin": f"feeling: {feeling}",
            })

    # NOTE: Raw message BM25 deliberately disabled for windowsill.
    # BM25 on conversational text is keyword soup — "memory injections not helpful"
    # matches on "helpful" from a December compliment. The windowsill Claude confirmed
    # manual RAG search works well; the companion should only fire on high-signal
    # queries (issue refs, file refs, feeling-based), not raw conversational text.

    # Get RAG search function
    search_fn = _get_rag_search()
    if search_fn is None:
        return ""

    # Run queries, skip suppressed
    pointers = []
    queries_run = 0
    offered_queries = []

    for qp in query_plan:
        if queries_run >= MAX_QUERIES:
            break
        q = qp["query"]
        if is_suppressed(q):
            continue

        results = _query_rag(search_fn, q)
        queries_run += 1

        pointer = _build_pointer(q, results, qp["origin"], qp["min_score"])
        if pointer:
            pointers.append(pointer)
            offered_queries.append(q)

    # Record offered queries and build injection
    if offered_queries:
        record_offered(offered_queries)

    return _build_injection(pointers)


def main():
    # Read message from env var (safe from shell injection) or argv
    user_message = os.environ.get("MEMORY_COMPANION_MESSAGE", "")
    if not user_message and len(sys.argv) >= 2:
        user_message = sys.argv[1]

    if not user_message.strip():
        print(json.dumps({"success": True, "injection": ""}))
        return

    try:
        injection = get_injection(user_message)
        print(json.dumps({"success": True, "injection": injection}))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))


if __name__ == "__main__":
    main()
