# Setup Windows Task Scheduler for Claude Code RAG Re-indexing
# Run this script as Administrator to create the scheduled task

$TaskName = "ClaudeCodeRAG-Reindex"
$ScriptPath = "C:\Users\[USER]\source\repos\perpetual-opus-extended\.claude-rag\scheduled_reindex.py"

# Use pythonw.exe for silent execution (no terminal window)
# Falls back to python.exe if pythonw not found
$PythonPath = (Get-Command python).Source
$PythonwPath = $PythonPath -replace "python\.exe$", "pythonw.exe"
if (Test-Path $PythonwPath) {
    $PythonPath = $PythonwPath
    Write-Host "Using pythonw.exe for silent execution" -ForegroundColor Cyan
} else {
    Write-Host "Warning: pythonw.exe not found, using python.exe (will show terminal window)" -ForegroundColor Yellow
}

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Create the action
$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument $ScriptPath

# Create triggers:
# 1. At logon (with 2 minute delay to let system settle)
# 2. Every 2 hours while logged in
$TriggerLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$TriggerLogon.Delay = "PT2M"  # 2 minute delay after logon

$TriggerRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 2)

# Settings for fault tolerance
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -RestartCount 0 `
    -MultipleInstances IgnoreNew

# Principal (run as current user, no admin needed)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Register the task
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $TriggerLogon, $TriggerRepeat `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Incremental re-indexing of codebase for Claude Code RAG. Runs at logon and every 2 hours. Safe to interrupt."

Write-Host ""
Write-Host "Scheduled task '$TaskName' created successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "The task will:"
Write-Host "  - Run 2 minutes after logon"
Write-Host "  - Repeat every 2 hours while logged in"
Write-Host "  - Process max 500 files or 2 minutes per run"
Write-Host "  - Run silently (no terminal window)"
Write-Host "  - Show Windows notification ONLY on errors"
Write-Host "  - Safe to interrupt (fault tolerant)"
Write-Host ""
Write-Host "To view/modify: Task Scheduler -> Task Scheduler Library -> $TaskName"
Write-Host "To run manually: schtasks /run /tn $TaskName"
Write-Host "To remove: schtasks /delete /tn $TaskName /f"
