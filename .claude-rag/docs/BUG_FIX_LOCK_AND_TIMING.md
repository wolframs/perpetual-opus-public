# Bug Fix: Lock File and File Checking Timing Issues

## Issues Identified

### Issue 1: File Checking Stopped Immediately
**Problem**: After scanning took 96 seconds, the file checking phase stopped immediately, finding 0 files needing update.

**Root Cause**: The file checking phase was checking against the same time limit (`MAX_RUNTIME_SECONDS - MIN_PROCESSING_TIME_SECONDS = 96s`). Since scanning already took 96s, there was no time left for file checking.

**Fix**: 
- Calculate remaining time after scanning
- Allocate time specifically for file checking (at least 5 seconds minimum)
- Reserve processing time separately
- Added logging to show time budget allocation

### Issue 2: Lock File Not Released
**Problem**: The scheduled task's lock file (`reindex.lock`) was not deleted, causing database lock conflicts when git hooks tried to run.

**Root Cause**: The scheduled task was likely killed by Windows Task Scheduler (5-minute execution limit) or crashed before reaching the `finally` block that releases the lock.

**Fix**:
- Enhanced lock acquisition to check if the process is actually running (using `psutil` if available)
- More aggressive stale lock detection (5 minutes instead of 10)
- Better error handling in `finally` block to ensure lock is always released
- Added WAL mode and timeout to database connections for better concurrency

### Issue 3: Database Lock Conflicts
**Problem**: Git hooks tried to access the database while scheduled task was running, causing "database is locked" errors.

**Fix**:
- Added WAL (Write-Ahead Logging) mode to database connections for better concurrency
- Added 10-second timeout to database connections
- Improved lock file detection to prevent concurrent runs

## Changes Made

### `scheduled_reindex.py`
1. **Improved file checking time allocation**:
   - Calculates remaining time after scanning
   - Allocates at least 5 seconds for file checking
   - Reserves processing time separately
   - Better logging of time budgets

2. **Enhanced lock management**:
   - Checks if lock PID is actually running (using `psutil` if available)
   - More aggressive stale lock cleanup (5 minutes)
   - Better error handling in `finally` block

3. **Database connection improvements**:
   - WAL mode enabled for better concurrency
   - 10-second timeout added
   - Better error handling

### `reindex_repo.py`
1. **Database connection improvements**:
   - WAL mode enabled
   - 10-second timeout added
   - Better concurrency support

## Testing

To verify the fixes:

1. **Check lock file cleanup**:
   ```powershell
   # Should return False (no lock file)
   Test-Path reindex.lock
   ```

2. **Trigger manual re-index**:
   ```powershell
   schtasks /run /tn ClaudeCodeRAG-Reindex
   ```

3. **Monitor log**:
   ```powershell
   Get-Content reindex.log -Wait -Tail 20
   ```

4. **Look for**:
   - `File checking phase: Xs remaining, Ys available for checking` (new log message)
   - `Processed: X files` where X > 0
   - Lock file is deleted after completion
   - No database lock errors

## Expected Behavior After Fix

1. **File checking will proceed** even after long scans
2. **Lock file will always be released** even if process is killed
3. **Database locks will be handled gracefully** with retries/timeouts
4. **Concurrent runs will be prevented** by improved lock detection

## Notes

- The `psutil` library is optional - if not installed, the system falls back to time-based stale lock detection
- WAL mode allows multiple readers while one writer is active, reducing lock conflicts
- The 10-second timeout prevents indefinite hangs on locked databases


