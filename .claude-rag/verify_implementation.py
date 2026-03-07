#!/usr/bin/env python3
"""
Quick verification script to test key functionality.
"""

import sqlite3
import json
from pathlib import Path

# Load config
CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)

DB_PATH = Path(CONFIG["common"]["database_path"])

print("Verifying implementation...")
print("=" * 50)

# 1. Check config
print("\n1. Configuration:")
max_runtime = CONFIG["scheduled_reindex"]["max_runtime_seconds"]
print(f"   max_runtime_seconds: {max_runtime} (expected: 270)")
assert max_runtime == 270, f"Expected 270, got {max_runtime}"

batch_size = CONFIG["scheduled_reindex"].get("batch_check_size", 100)
print(f"   batch_check_size: {batch_size} (expected: 100)")
assert batch_size == 100

print("   ✓ Configuration correct")

# 2. Check database schema
if DB_PATH.exists():
    print("\n2. Database schema:")
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    
    # Check failed_files table
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='failed_files'")
    if c.fetchone():
        print("   ✓ failed_files table exists")
        
        # Check index
        c.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_failed_files_retry'")
        if c.fetchone():
            print("   ✓ failed_files index exists")
        else:
            print("   ⚠ failed_files index missing (will be created on next run)")
    else:
        print("   ⚠ failed_files table missing (run migrate_db.py)")
    
    conn.close()
else:
    print("\n2. Database:")
    print("   ⚠ Database not found (run hybrid_indexer.py first)")

# 3. Check imports
print("\n3. Module imports:")
try:
    import scheduled_reindex
    print("   ✓ scheduled_reindex imports successfully")
    
    # Check key functions exist
    assert hasattr(scheduled_reindex, 'track_failed_file'), "track_failed_file missing"
    assert hasattr(scheduled_reindex, 'get_failed_files'), "get_failed_files missing"
    assert hasattr(scheduled_reindex, 'check_files_batch'), "check_files_batch missing"
    assert hasattr(scheduled_reindex, 'index_file_with_retry'), "index_file_with_retry missing"
    assert hasattr(scheduled_reindex, 'prioritize_files'), "prioritize_files missing"
    print("   ✓ All key functions present")
except Exception as e:
    print(f"   ✗ Import failed: {e}")

try:
    import reindex_repo
    print("   ✓ reindex_repo imports successfully")
except Exception as e:
    print(f"   ✗ Import failed: {e}")

print("\n" + "=" * 50)
print("Verification complete!")
print("\nNext steps:")
print("1. Run: python migrate_db.py (if database exists)")
print("2. Monitor next scheduled re-index run")
print("3. Check reindex.log for improved logging")


