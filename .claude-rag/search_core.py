#!/usr/bin/env python3
"""
Core search functionality shared between hybrid_search.py and mcp_server.py.

This module contains the shared search logic, database operations, and utility
functions that are used by both the standalone CLI tool and the MCP server.
"""

import sqlite3
import numpy as np
import json
import time
from pathlib import Path
from typing import Optional, Callable


def load_config() -> dict:
    """Load configuration from config.json."""
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, "r") as f:
        return json.load(f)


# Load configuration once at module level
CONFIG = load_config()
DB_PATH = Path(CONFIG["common"]["database_path"])
DEFAULT_TOP_K = CONFIG["search"]["default_top_k"]
BM25_WEIGHT = CONFIG["search"]["bm25_weight"]
SEMANTIC_WEIGHT = CONFIG["search"]["semantic_weight"]


def format_fts_query(query: str) -> str:
    """
    Convert query to FTS5 OR query format.
    
    Quotes hyphenated words to prevent FTS5 column name parsing (e.g., "Document-Mailing").
    Escapes quotes in quoted words by doubling them (FTS5 syntax: "test""quote").
    
    Args:
        query: The search query string
        
    Returns:
        Formatted FTS5 query string
    """
    words = query.split()
    quoted_words = []
    for word in words:
        if '-' in word:
            escaped_word = word.replace('"', '""')
            quoted_words.append(f'"{escaped_word}"')
        else:
            quoted_words.append(word)
    
    if len(quoted_words) > 1:
        return ' OR '.join(quoted_words)
    elif '-' in query:
        escaped_query = query.replace('"', '""')
        return f'"{escaped_query}"'
    else:
        return query


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.array(a)
    b = np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def get_cached_embedding(conn: sqlite3.Connection, chunk_id: str) -> list[float] | None:
    """Get cached embedding for a chunk from the database."""
    c = conn.cursor()
    c.execute("SELECT embedding FROM chunks WHERE id = ?", (chunk_id,))
    row = c.fetchone()
    if row and row[0]:
        return json.loads(row[0])
    return None


def cache_embedding(conn: sqlite3.Connection, chunk_id: str, embedding: list[float]):
    """Cache embedding for a chunk in the database."""
    c = conn.cursor()
    c.execute(
        "UPDATE chunks SET embedding = ?, updated_at = ? WHERE id = ?",
        (json.dumps(embedding), time.time(), chunk_id)
    )
    conn.commit()


def bm25_search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    file_filter: str = None,
    db_path: Path = None,
    get_db_func: Optional[Callable] = None,
    include_embeddings: bool = False
) -> list[dict]:
    """
    Fast BM25 search using SQLite FTS5.
    
    Args:
        query: Search query string
        top_k: Number of results to return
        file_filter: Optional file path filter pattern
        db_path: Optional database path (uses default if None)
        get_db_func: Optional function to get database connection (uses default if None)
        include_embeddings: If True, load embeddings from database in the query
        
    Returns:
        List of result dictionaries with id, file_path, file_name, chunk_index, content, bm25_score
        and optionally embedding if include_embeddings=True
    """
    if get_db_func is None:
        if db_path is None:
            db_path = DB_PATH
        conn = sqlite3.connect(db_path)
    else:
        conn = get_db_func()
    
    c = conn.cursor()
    fts_query = format_fts_query(query)
    
    # Build query - include embeddings if requested
    if include_embeddings:
        select_fields = "c.id, c.file_path, c.file_name, c.chunk_index, c.content, c.embedding, bm25(chunks_fts) as score"
    else:
        select_fields = "c.id, c.file_path, c.file_name, c.chunk_index, c.content, bm25(chunks_fts) as score"
    
    if file_filter:
        c.execute(f"""
            SELECT {select_fields}
            FROM chunks_fts fts
            JOIN chunks c ON fts.rowid = c.rowid
            WHERE chunks_fts MATCH ? AND c.file_path LIKE ?
            ORDER BY score
            LIMIT ?
        """, (fts_query, f"%{file_filter}%", top_k * 2))  # Get extra for reranking
    else:
        c.execute(f"""
            SELECT {select_fields}
            FROM chunks_fts fts
            JOIN chunks c ON fts.rowid = c.rowid
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
        """, (fts_query, top_k * 2))
    
    results = []
    for row in c.fetchall():
        if include_embeddings:
            result = {
                "id": row[0],
                "file_path": row[1],
                "file_name": row[2],
                "chunk_index": row[3],
                "content": row[4],
                "embedding": json.loads(row[5]) if row[5] else None,
                "bm25_score": -row[6],  # FTS5 returns negative scores, lower is better
            }
        else:
            result = {
                "id": row[0],
                "file_path": row[1],
                "file_name": row[2],
                "chunk_index": row[3],
                "content": row[4],
                "bm25_score": -row[5],  # FTS5 returns negative scores, lower is better
            }
        results.append(result)
    
    conn.close()
    return results


def search_files(
    query: str,
    top_k: int = 10,
    db_path: Path = None,
    get_db_func: Optional[Callable] = None
) -> list[dict]:
    """
    Search for files by name or path.
    
    Args:
        query: Search pattern for file names/paths
        top_k: Maximum number of results
        db_path: Optional database path (uses default if None)
        get_db_func: Optional function to get database connection (uses default if None)
        
    Returns:
        List of dictionaries with file_path and file_name
    """
    if get_db_func is None:
        if db_path is None:
            db_path = DB_PATH
        conn = sqlite3.connect(db_path)
    else:
        conn = get_db_func()
    
    c = conn.cursor()
    c.execute("""
        SELECT DISTINCT file_path, file_name
        FROM chunks
        WHERE file_path LIKE ? OR file_name LIKE ?
        LIMIT ?
    """, (f"%{query}%", f"%{query}%", top_k))
    
    results = [{"file_path": row[0], "file_name": row[1]} for row in c.fetchall()]
    conn.close()
    return results


def get_file_content(
    file_path: str,
    db_path: Path = None,
    get_db_func: Optional[Callable] = None
) -> str | None:
    """
    Get full content of a file from chunks.
    
    Args:
        file_path: Path to the file
        db_path: Optional database path (uses default if None)
        get_db_func: Optional function to get database connection (uses default if None)
        
    Returns:
        Reconstructed file content or None if not found
    """
    if get_db_func is None:
        if db_path is None:
            db_path = DB_PATH
        conn = sqlite3.connect(db_path)
    else:
        conn = get_db_func()
    
    c = conn.cursor()
    c.execute("""
        SELECT content FROM chunks
        WHERE file_path = ?
        ORDER BY chunk_index
    """, (file_path,))
    
    chunks = [row[0] for row in c.fetchall()]
    conn.close()
    
    if not chunks:
        return None
    
    # Reconstruct file (removing overlap)
    # This is approximate - for exact content, read the actual file
    return "\n".join(chunks)


def get_stats(
    db_path: Path = None,
    get_db_func: Optional[Callable] = None,
    include_db_size: bool = False
) -> dict:
    """
    Get index statistics.
    
    Args:
        db_path: Optional database path (uses default if None)
        get_db_func: Optional function to get database connection (uses default if None)
        include_db_size: If True, include database file size in MB
        
    Returns:
        Dictionary with statistics
    """
    if get_db_func is None:
        if db_path is None:
            db_path = DB_PATH
        conn = sqlite3.connect(db_path)
    else:
        conn = get_db_func()
    
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM files")
    file_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM chunks")
    chunk_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL")
    embedded_count = c.fetchone()[0]
    
    conn.close()
    
    stats = {
        "files": file_count,
        "chunks": chunk_count,
        "embedded_chunks": embedded_count,
        "embedding_coverage": f"{embedded_count/chunk_count*100:.1f}%" if chunk_count > 0 else "0%",
    }
    
    if include_db_size:
        if db_path is None:
            db_path = DB_PATH
        stats["database_size_mb"] = db_path.stat().st_size / 1024 / 1024 if db_path.exists() else 0
    
    return stats

