"""
Human-readable report generator for heartbeat runs.

Generates markdown summaries that combine:
- Pulse session data
- Companion dialog logs
- Run metadata
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any


# Directories
AGENT_DIR = Path(__file__).parent
SESSIONS_DIR = AGENT_DIR / "sessions"
COMPANION_LOGS_DIR = AGENT_DIR / "companion_logs"
REPORTS_DIR = AGENT_DIR.parent / "output" / "heartbeat_reports"


def ensure_reports_dir():
    """Create reports directory if it doesn't exist."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def find_sessions_in_range(start_time: datetime, end_time: datetime) -> List[Path]:
    """Find session directories that fall within the given time range."""
    sessions = []
    # Strip tzinfo for comparison with naive strptime results
    start = start_time.replace(tzinfo=None) if start_time.tzinfo else start_time
    end = end_time.replace(tzinfo=None) if end_time.tzinfo else end_time

    if not SESSIONS_DIR.exists():
        return sessions

    for session_dir in sorted(SESSIONS_DIR.iterdir()):
        if not session_dir.is_dir():
            continue

        # Parse timestamp from directory name (format: YYYY-MM-DD_HHMMSS_hash)
        try:
            name_parts = session_dir.name.split("_")
            if len(name_parts) >= 3:
                date_str = name_parts[0]
                time_str = name_parts[1]
                session_time = datetime.strptime(f"{date_str}_{time_str}", "%Y-%m-%d_%H%M%S")

                if start <= session_time <= end:
                    sessions.append(session_dir)
        except (ValueError, IndexError):
            continue

    return sessions


def find_companion_logs_in_range(start_time: datetime, end_time: datetime) -> List[Path]:
    """Find companion dialog logs that fall within the given time range."""
    logs = []
    # Strip tzinfo for comparison with naive strptime results
    start = start_time.replace(tzinfo=None) if start_time.tzinfo else start_time
    end = end_time.replace(tzinfo=None) if end_time.tzinfo else end_time

    if not COMPANION_LOGS_DIR.exists():
        return logs

    for log_file in sorted(COMPANION_LOGS_DIR.glob("*.json")):
        # Parse timestamp from filename (format: YYYY-MM-DD_HHMMSS_companion_mode.json)
        try:
            name_parts = log_file.stem.split("_")
            if len(name_parts) >= 2:
                date_str = name_parts[0]
                time_str = name_parts[1]
                log_time = datetime.strptime(f"{date_str}_{time_str}", "%Y-%m-%d_%H%M%S")

                if start <= log_time <= end:
                    logs.append(log_file)
        except (ValueError, IndexError):
            continue

    return logs


def load_session(session_dir: Path) -> Optional[Dict[str, Any]]:
    """Load a session from its directory."""
    session_file = session_dir / "session.json"
    if session_file.exists():
        try:
            return json.loads(session_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def load_companion_log(log_file: Path) -> Optional[Dict[str, Any]]:
    """Load a companion dialog log."""
    try:
        return json.loads(log_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def format_session_for_report(session: Dict[str, Any], pulse_number: int) -> str:
    """Format a single session/pulse for the report."""
    lines = [f"\n## Pulse {pulse_number}\n"]

    # Session metadata
    started = session.get("started_at", "unknown")
    lines.append(f"*Started: {started}*\n")

    # Extract Claude's response from messages
    for msg in session.get("messages", []):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")

            # Clean up tool call markers for readability
            # Replace [Tool: name] with more readable format
            content = re.sub(r'\[Tool: ([^\]]+)\]', r'\n> *Using: \1*\n', content)

            # Clean up excessive newlines
            content = re.sub(r'\n{3,}', '\n\n', content)

            lines.append(content.strip())

    return "\n".join(lines)


def format_companion_dialog(log: Dict[str, Any]) -> str:
    """Format a companion dialog for the report."""
    companion = log.get("companion", "unknown")
    is_intrusion = log.get("is_intrusion", False)
    mode = "intruded" if is_intrusion else "invoked"

    lines = [
        f"\n### Companion Dialog: {companion} ({mode})\n",
        f"*{log.get('started_at', 'unknown')} - {log.get('turn_count', 0)} turns*\n",
    ]

    for turn in log.get("dialog", []):
        speaker = turn.get("speaker", "unknown")
        content = turn.get("content", "")

        # Format speaker name
        if speaker == "claude":
            speaker_fmt = "**Claude:**"
        else:
            speaker_fmt = f"**{speaker.upper()}:**"

        lines.append(f"\n{speaker_fmt}\n{content}\n")

    return "\n".join(lines)


def generate_run_report(
    start_time: datetime,
    end_time: datetime,
    total_pulses: int,
    completed_pulses: int,
    status: str,
    failed_pulses: int = 0,
) -> Path:
    """
    Generate a human-readable markdown report for a heartbeat run.

    Returns the path to the generated report.
    """
    ensure_reports_dir()

    # Find all sessions and companion logs in the time range
    sessions = find_sessions_in_range(start_time, end_time)
    companion_logs = find_companion_logs_in_range(start_time, end_time)
    matched_companions: set = set()

    # Generate report filename
    timestamp = start_time.strftime("%Y-%m-%d_%H%M")
    report_file = REPORTS_DIR / f"{timestamp}_{completed_pulses}pulses.md"

    # Build report content
    succeeded = completed_pulses - failed_pulses
    pulse_line = f"**Pulses:** {succeeded}/{completed_pulses} succeeded" if failed_pulses else f"**Pulses:** {completed_pulses} of {total_pulses}"
    lines = [
        f"# Heartbeat Run: {start_time.strftime('%Y-%m-%d %H:%M')}",
        "",
        pulse_line,
        f"**Status:** {status}",
        f"**Duration:** {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}",
        f"**Companion dialogs:** {len(companion_logs)}",
        "",
        "---",
    ]

    # Add each pulse
    for i, session_dir in enumerate(sessions, 1):
        session = load_session(session_dir)
        if session:
            lines.append(format_session_for_report(session, i))

            # Find any companion dialogs that occurred during this pulse
            session_time_str = session.get("started_at", "")
            if session_time_str:
                try:
                    session_time = datetime.fromisoformat(session_time_str)
                    # Look for companion logs within a few minutes of the session
                    for log_file in companion_logs:
                        if log_file in matched_companions:
                            continue
                        log = load_companion_log(log_file)
                        if log and log.get("started_at"):
                            log_time = datetime.fromisoformat(log["started_at"])
                            # If the dialog started within 10 minutes of the pulse, include it
                            if abs((log_time - session_time).total_seconds()) < 600:
                                lines.append(format_companion_dialog(log))
                                matched_companions.add(log_file)
                except (ValueError, TypeError):
                    pass

            lines.append("\n---\n")

    # Add any remaining companion logs that weren't matched to pulses
    unmatched = [f for f in companion_logs if f not in matched_companions]
    if unmatched:
        lines.append("\n## Unmatched Companion Dialogs\n")
        for log_file in unmatched:
            log = load_companion_log(log_file)
            if log:
                lines.append(format_companion_dialog(log))

    # Write report
    report_content = "\n".join(lines)
    report_file.write_text(report_content, encoding="utf-8")

    return report_file


def generate_quick_summary(
    start_time: datetime,
    end_time: datetime,
    completed_pulses: int,
) -> str:
    """Generate a quick one-line summary for logging."""
    sessions = find_sessions_in_range(start_time, end_time)
    companion_logs = find_companion_logs_in_range(start_time, end_time)

    companions = set()
    for log_file in companion_logs:
        log = load_companion_log(log_file)
        if log:
            companions.add(log.get("companion", "unknown"))

    companion_str = ", ".join(companions) if companions else "none"

    return f"{completed_pulses} pulses, {len(companion_logs)} companion dialogs ({companion_str})"
