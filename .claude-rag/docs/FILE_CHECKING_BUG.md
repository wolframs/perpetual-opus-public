# File Checking Bug: 0 Files Found When Files Actually Need Update

## Problem

When git hooks fail to index files (due to database locks), and then scheduled re-index runs, it finds 0 files needing update even though files failed to index.

## Root Cause

1. **Git hook fails**: 22 files fail to index due to "database is locked" errors
2. **Scheduled re-index scans**: Only 50,400 files scanned (stopped early at 96.3s due to time limit)
3. **File checking stops immediately**: The time check happens BEFORE checking files, and since `elapsed_total` (96.3s) >= `MAX_RUNTIME_SECONDS - MIN_PROCESSING_TIME_SECONDS` (96s), the loop breaks immediately
4. **Result**: 0 files checked, 0 files found needing update

## The Logic Flaw

The file checking loop checks time BEFORE checking files:
```python
for f in all_files:
    elapsed_total = time.time() - start_time
    if elapsed_total >= MAX_RUNTIME_SECONDS - MIN_PROCESSING_TIME_SECONDS:
        break  # Stops immediately!
    
    if file_needs_update(conn, f):  # Never reached
        ...
```

When scanning takes 96.3s, and the deadline is 96s, the loop breaks on the first iteration without checking any files.

## Additional Issues

1. **Incomplete scanning**: Only 50,400 of ~65,000 files scanned
2. **Failed files may be in unscanned portion**: The 22 failed files might be in the remaining ~15,000 files
3. **No retry mechanism**: Failed files aren't tracked for retry

## Fix Applied

Changed the time check to use an absolute deadline and allow checking files as long as we haven't exceeded it:

```python
file_check_deadline = MAX_RUNTIME_SECONDS - MIN_PROCESSING_TIME_SECONDS

for f in all_files:
    elapsed_total = time.time() - start_time
    if elapsed_total >= file_check_deadline:
        break  # Only stop if we've exceeded the deadline
    
    # Check file (this will now actually run)
    if file_needs_update(conn, f):
        ...
```

This ensures files are actually checked even if we're close to the deadline, as long as we haven't exceeded it.

## Expected Behavior After Fix

1. File checking will proceed even if scanning took most of the time
2. Files that failed to index will be detected (if they're in the scanned subset)
3. Files will be processed if they need updating

## Remaining Limitations

- Files in the unscanned portion (~15,000 files) still won't be checked
- Need to increase time limit or optimize scanning to scan all files
- Failed files from git hooks aren't tracked for priority retry


