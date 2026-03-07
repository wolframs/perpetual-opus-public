#!/usr/bin/env python3
"""
Database migration script to add failed_files table.
Safe to run multiple times (idempotent).
"""

import sqlite3
import json
from pathlib import Path

# Load configuration
CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)

DB_PATH = Path(CONFIG["common"]["database_path"])

if not DB_PATH.exists():
    print(f"Database not found: {DB_PATH}")
    print("Run hybrid_indexer.py first to create the database")
    exit(1)

conn = sqlite3.connect(str(DB_PATH))
c = conn.cursor()

# Check if failed_files table exists
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='failed_files'")
if c.fetchone() is None:
    print("Creating failed_files table...")
    c.execute("""
        CREATE TABLE failed_files (
            path TEXT PRIMARY KEY,
            error TEXT NOT NULL,
            retry_count INTEGER DEFAULT 0,
            last_attempt REAL NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_failed_files_retry ON failed_files(retry_count, last_attempt)")
    conn.commit()
    print("✓ failed_files table created")
else:
    print("✓ failed_files table already exists")

conn.close()
print("Migration complete")


