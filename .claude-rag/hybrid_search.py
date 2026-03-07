#!/usr/bin/env python3
"""
Hybrid Search for Claude Code RAG
- BM25 for fast keyword search
- Lazy embedding generation (only for retrieved chunks)
- Cached embeddings for frequently accessed chunks
"""

import sqlite3
import requests
import json
from pathlib import Path

# Import shared core functionality
from search_core import (
    CONFIG, DB_PATH, DEFAULT_TOP_K, BM25_WEIGHT, SEMANTIC_WEIGHT,
    bm25_search as core_bm25_search,
    cosine_similarity,
    get_cached_embedding,
    cache_embedding,
    search_files as core_search_files,
    get_file_content as core_get_file_content,
    get_stats as core_get_stats,
)

# Load embedding configuration
OLLAMA_URL = CONFIG["embedding"]["ollama_url"]
EMBEDDING_MODEL = CONFIG["embedding"]["embedding_model"]


def get_db():
    """Get database connection."""
    return sqlite3.connect(DB_PATH)


def bm25_search(query: str, top_k: int = DEFAULT_TOP_K, file_filter: str = None) -> list[dict]:
    """
    Fast BM25 search using SQLite FTS5.
    Returns chunks ranked by relevance.
    """
    return core_bm25_search(query, top_k, file_filter, get_db_func=get_db, include_embeddings=False)


def get_embedding(text: str) -> list[float] | None:
    """Get embedding from Ollama."""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "input": text[:8000],
                "model": EMBEDDING_MODEL,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data["embeddings"][0]
    except Exception as e:
        print(f"Embedding error: {e}")
        return None


def hybrid_search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    file_filter: str = None,
    use_semantic: bool = True
) -> list[dict]:
    """
    Hybrid search combining BM25 and semantic similarity.

    1. Fast BM25 search to get candidates
    2. Lazy embedding of query and top candidates
    3. Rerank using combined score
    """
    # Step 1: BM25 search for candidates
    candidates = bm25_search(query, top_k, file_filter)

    if not candidates:
        return []

    if not use_semantic:
        # Return BM25 results only
        return candidates[:top_k]

    # Step 2: Get query embedding
    query_embedding = get_embedding(query)
    if query_embedding is None:
        # Fall back to BM25 only
        return candidates[:top_k]

    # Step 3: Get/compute embeddings for candidates and rerank
    conn = get_db()

    for candidate in candidates:
        # Try cached embedding first
        embedding = get_cached_embedding(conn, candidate["id"])

        if embedding is None:
            # Compute and cache embedding
            embedding = get_embedding(candidate["content"])
            if embedding:
                cache_embedding(conn, candidate["id"], embedding)

        if embedding:
            candidate["semantic_score"] = cosine_similarity(query_embedding, embedding)
        else:
            candidate["semantic_score"] = 0.0

        # Normalize BM25 score to 0-1 range (approximate)
        max_bm25 = max(c["bm25_score"] for c in candidates) if candidates else 1
        normalized_bm25 = candidate["bm25_score"] / max_bm25 if max_bm25 > 0 else 0

        # Combined score
        candidate["combined_score"] = (
            BM25_WEIGHT * normalized_bm25 +
            SEMANTIC_WEIGHT * candidate["semantic_score"]
        )

    conn.close()

    # Sort by combined score
    candidates.sort(key=lambda x: x["combined_score"], reverse=True)

    return candidates[:top_k]


def search_files(query: str, top_k: int = 10) -> list[dict]:
    """Search for files by name or path."""
    return core_search_files(query, top_k, get_db_func=get_db)


def get_file_content(file_path: str) -> str | None:
    """Get full content of a file from chunks."""
    return core_get_file_content(file_path, get_db_func=get_db)


def get_stats() -> dict:
    """Get index statistics."""
    return core_get_stats(get_db_func=get_db, include_db_size=True)


# CLI interface
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python hybrid_search.py <query>")
        print("       python hybrid_search.py --stats")
        sys.exit(1)

    if sys.argv[1] == "--stats":
        stats = get_stats()
        print("Index Statistics:")
        for k, v in stats.items():
            print(f"  {k}: {v}")
    else:
        query = " ".join(sys.argv[1:])
        print(f"Searching for: {query}\n")

        results = hybrid_search(query, top_k=5)

        if not results:
            print("No results found.")
        else:
            for i, r in enumerate(results, 1):
                print(f"{i}. {r['file_path']}:{r['chunk_index']}")
                print(f"   Score: {r.get('combined_score', r.get('bm25_score', 0)):.3f}")
                print(f"   Preview: {r['content'][:100]}...")
                print()
