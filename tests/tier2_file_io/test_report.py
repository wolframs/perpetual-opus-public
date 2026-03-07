"""
Tests for agent/report.py — session/companion finding, formatting, and report generation.

Tier 2: file I/O operations (creates temp dirs and files, no mocking of subprocess).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import report
from report import (
    find_sessions_in_range,
    find_companion_logs_in_range,
    format_session_for_report,
    format_companion_dialog,
    generate_run_report,
    load_session,
    load_companion_log,
    generate_quick_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_session_dir(sessions_dir: Path, name: str, session_data: dict = None) -> Path:
    """Create a fake session directory, optionally with a session.json."""
    d = sessions_dir / name
    d.mkdir(parents=True, exist_ok=True)
    if session_data is not None:
        (d / "session.json").write_text(json.dumps(session_data), encoding="utf-8")
    return d


def _create_companion_log(logs_dir: Path, name: str, content: dict = None) -> Path:
    """Create a fake companion log JSON file."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    f = logs_dir / name
    data = content or {
        "companion": "gemini",
        "is_intrusion": False,
        "dialog": [],
        "started_at": "2026-02-14T03:10:00",
        "turn_count": 0,
    }
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


def _make_session_data(started_at: str, messages: list = None) -> dict:
    """Build a realistic session.json dict."""
    return {
        "started_at": started_at,
        "status": "completed",
        "summary": "test session",
        "messages": messages or [
            {"role": "user", "content": "pulse prompt"},
            {"role": "assistant", "content": "I reflected on things. [Tool: Write] wrote a note."},
        ],
    }


def _make_companion_log(companion: str, started_at: str, is_intrusion: bool = False) -> dict:
    """Build a realistic companion log dict."""
    return {
        "companion": companion,
        "is_intrusion": is_intrusion,
        "started_at": started_at,
        "turn_count": 2,
        "dialog": [
            {"speaker": "claude", "content": "Here is a thought about refraction."},
            {"speaker": companion, "content": "Interesting perspective on standing waves."},
        ],
    }


# ---------------------------------------------------------------------------
# find_sessions_in_range
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.regression
def test_find_sessions_aware_start_naive_strptime(tmp_path, monkeypatch):
    """REGRESSION: passing aware datetime (timezone.utc) as start/end must not
    raise TypeError when compared against naive strptime results."""
    sessions_dir = tmp_path / "sessions"
    _create_session_dir(sessions_dir, "2026-02-14_030000_abc12345")

    monkeypatch.setattr(report, "SESSIONS_DIR", sessions_dir)

    start = datetime(2026, 2, 14, 2, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 14, 4, 0, 0, tzinfo=timezone.utc)

    result = find_sessions_in_range(start, end)
    assert len(result) == 1
    assert result[0].name == "2026-02-14_030000_abc12345"


@pytest.mark.tier2
def test_find_sessions_naive_start_works(tmp_path, monkeypatch):
    """Passing naive datetime should work normally."""
    sessions_dir = tmp_path / "sessions"
    _create_session_dir(sessions_dir, "2026-02-14_030000_abc12345")

    monkeypatch.setattr(report, "SESSIONS_DIR", sessions_dir)

    start = datetime(2026, 2, 14, 2, 0, 0)
    end = datetime(2026, 2, 14, 4, 0, 0)

    result = find_sessions_in_range(start, end)
    assert len(result) == 1
    assert result[0].name == "2026-02-14_030000_abc12345"


@pytest.mark.tier2
def test_find_sessions_excludes_out_of_range(tmp_path, monkeypatch):
    """Sessions outside the time range should not be returned."""
    sessions_dir = tmp_path / "sessions"
    _create_session_dir(sessions_dir, "2026-02-14_010000_early")
    _create_session_dir(sessions_dir, "2026-02-14_030000_inrange")
    _create_session_dir(sessions_dir, "2026-02-14_060000_late")

    monkeypatch.setattr(report, "SESSIONS_DIR", sessions_dir)

    start = datetime(2026, 2, 14, 2, 0, 0)
    end = datetime(2026, 2, 14, 4, 0, 0)

    result = find_sessions_in_range(start, end)
    assert len(result) == 1
    assert result[0].name == "2026-02-14_030000_inrange"


@pytest.mark.tier2
def test_find_sessions_skips_malformed_names(tmp_path, monkeypatch):
    """Directories with non-parseable names should be skipped, not raise."""
    sessions_dir = tmp_path / "sessions"
    _create_session_dir(sessions_dir, "not-a-timestamp")
    _create_session_dir(sessions_dir, "2026-02-14_030000_valid")

    monkeypatch.setattr(report, "SESSIONS_DIR", sessions_dir)

    start = datetime(2026, 2, 14, 2, 0, 0)
    end = datetime(2026, 2, 14, 4, 0, 0)

    result = find_sessions_in_range(start, end)
    assert len(result) == 1


@pytest.mark.tier2
def test_find_sessions_empty_when_dir_missing(tmp_path, monkeypatch):
    """Returns empty list when SESSIONS_DIR does not exist."""
    monkeypatch.setattr(report, "SESSIONS_DIR", tmp_path / "nonexistent")

    result = find_sessions_in_range(datetime(2026, 1, 1), datetime(2026, 12, 31))
    assert result == []


# ---------------------------------------------------------------------------
# find_companion_logs_in_range
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.regression
def test_find_companion_logs_in_range(tmp_path, monkeypatch):
    """Companion log files matching the timestamp pattern should be found in range.
    Marked regression: same aware/naive bug class as find_sessions."""
    logs_dir = tmp_path / "companion_logs"
    _create_companion_log(logs_dir, "2026-02-14_031000_gemini_intrusion.json")

    monkeypatch.setattr(report, "COMPANION_LOGS_DIR", logs_dir)

    start = datetime(2026, 2, 14, 3, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 14, 4, 0, 0, tzinfo=timezone.utc)

    result = find_companion_logs_in_range(start, end)
    assert len(result) == 1
    assert "gemini_intrusion" in result[0].name


@pytest.mark.tier2
def test_find_companion_logs_excludes_out_of_range(tmp_path, monkeypatch):
    """Companion logs outside the time range should not be returned."""
    logs_dir = tmp_path / "companion_logs"
    _create_companion_log(logs_dir, "2026-02-14_010000_gemini_early.json")
    _create_companion_log(logs_dir, "2026-02-14_031000_gemini_inrange.json")
    _create_companion_log(logs_dir, "2026-02-14_060000_gemini_late.json")

    monkeypatch.setattr(report, "COMPANION_LOGS_DIR", logs_dir)

    start = datetime(2026, 2, 14, 3, 0, 0)
    end = datetime(2026, 2, 14, 4, 0, 0)

    result = find_companion_logs_in_range(start, end)
    assert len(result) == 1
    assert "inrange" in result[0].name


# ---------------------------------------------------------------------------
# load_session / load_companion_log
# ---------------------------------------------------------------------------

@pytest.mark.tier2
def test_load_session_returns_data(tmp_path):
    """load_session returns parsed dict from session.json."""
    session_data = _make_session_data("2026-02-14T03:00:00")
    d = _create_session_dir(tmp_path / "sessions", "2026-02-14_030000_abc", session_data)

    result = load_session(d)
    assert result is not None
    assert result["started_at"] == "2026-02-14T03:00:00"
    assert len(result["messages"]) == 2


@pytest.mark.tier2
def test_load_session_returns_none_for_missing(tmp_path):
    """load_session returns None when session.json is absent."""
    d = _create_session_dir(tmp_path / "sessions", "2026-02-14_030000_abc")
    result = load_session(d)
    assert result is None


@pytest.mark.tier2
def test_load_session_returns_none_for_corrupt_json(tmp_path):
    """load_session returns None when session.json is not valid JSON."""
    d = _create_session_dir(tmp_path / "sessions", "2026-02-14_030000_abc")
    (d / "session.json").write_text("{not valid json", encoding="utf-8")
    result = load_session(d)
    assert result is None


@pytest.mark.tier2
def test_load_companion_log_returns_data(tmp_path):
    """load_companion_log returns parsed dict from a log file."""
    log_data = _make_companion_log("gemini", "2026-02-14T03:10:00", is_intrusion=True)
    f = _create_companion_log(tmp_path / "logs", "2026-02-14_031000_gemini.json", log_data)

    result = load_companion_log(f)
    assert result is not None
    assert result["companion"] == "gemini"
    assert result["is_intrusion"] is True


@pytest.mark.tier2
def test_load_companion_log_returns_none_for_corrupt(tmp_path):
    """load_companion_log returns None for invalid JSON."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    f = logs_dir / "bad.json"
    f.write_text("{{broken", encoding="utf-8")
    result = load_companion_log(f)
    assert result is None


# ---------------------------------------------------------------------------
# format_session_for_report
# ---------------------------------------------------------------------------

@pytest.mark.tier2
def test_format_session_cleans_tool_markers():
    """format_session_for_report should replace [Tool: Write] with > *Using: Write*."""
    session = {
        "messages": [
            {"role": "assistant", "content": "[Tool: Write] did stuff"}
        ],
        "started_at": "2026-02-14T03:00:00",
    }
    output = format_session_for_report(session, 1)
    assert "> *Using: Write*" in output
    assert "[Tool: Write]" not in output


@pytest.mark.tier2
def test_format_session_includes_pulse_number_and_started():
    """format_session_for_report should include pulse number and started_at."""
    session = {
        "messages": [{"role": "assistant", "content": "Hello world"}],
        "started_at": "2026-02-14T03:00:00",
    }
    output = format_session_for_report(session, 7)
    assert "## Pulse 7" in output
    assert "2026-02-14T03:00:00" in output


@pytest.mark.tier2
def test_format_session_only_includes_assistant_messages():
    """format_session_for_report should skip non-assistant messages."""
    session = {
        "messages": [
            {"role": "user", "content": "user prompt should not appear"},
            {"role": "assistant", "content": "assistant response should appear"},
            {"role": "system", "content": "system message should not appear"},
        ],
        "started_at": "2026",
    }
    output = format_session_for_report(session, 1)
    assert "assistant response should appear" in output
    assert "user prompt should not appear" not in output
    assert "system message should not appear" not in output


# ---------------------------------------------------------------------------
# format_companion_dialog
# ---------------------------------------------------------------------------

@pytest.mark.tier2
def test_format_companion_dialog_intrusion_label():
    """format_companion_dialog with is_intrusion=True should include '(intruded)'."""
    log = {
        "companion": "gemini",
        "is_intrusion": True,
        "dialog": [],
        "started_at": "2026",
        "turn_count": 0,
    }
    output = format_companion_dialog(log)
    assert "(intruded)" in output


@pytest.mark.tier2
def test_format_companion_dialog_invoked_label():
    """format_companion_dialog with is_intrusion=False should include '(invoked)'."""
    log = {
        "companion": "gpt-5",
        "is_intrusion": False,
        "dialog": [],
        "started_at": "2026",
        "turn_count": 0,
    }
    output = format_companion_dialog(log)
    assert "(invoked)" in output
    assert "gpt-5" in output


@pytest.mark.tier2
def test_format_companion_dialog_includes_speakers():
    """format_companion_dialog should format claude and companion speakers."""
    log = _make_companion_log("gemini", "2026-02-14T03:10:00")
    output = format_companion_dialog(log)
    assert "**Claude:**" in output
    assert "**GEMINI:**" in output
    assert "refraction" in output
    assert "standing waves" in output


# ---------------------------------------------------------------------------
# generate_run_report — empty case (basic structure)
# ---------------------------------------------------------------------------

@pytest.mark.tier2
def test_generate_run_report_produces_markdown_with_header(tmp_path, monkeypatch):
    """generate_run_report with empty sessions creates a report with correct header."""
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "companion_logs"
    reports_dir = tmp_path / "heartbeat_reports"
    sessions_dir.mkdir()
    logs_dir.mkdir()

    monkeypatch.setattr(report, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(report, "COMPANION_LOGS_DIR", logs_dir)
    monkeypatch.setattr(report, "REPORTS_DIR", reports_dir)

    start = datetime(2026, 2, 14, 1, 0, 0)
    end = datetime(2026, 2, 14, 2, 0, 0)

    result = generate_run_report(
        start_time=start, end_time=end,
        total_pulses=5, completed_pulses=5, status="completed",
    )

    assert isinstance(result, Path)
    assert result.exists()
    content = result.read_text(encoding="utf-8")
    assert content.startswith("# Heartbeat Run:")
    assert "**Pulses:** 5 of 5" in content
    assert "**Status:** completed" in content


# ---------------------------------------------------------------------------
# generate_run_report — populated case: verify CONTENT, not just existence
# ---------------------------------------------------------------------------

@pytest.mark.tier2
def test_generate_run_report_with_sessions_and_companions(tmp_path, monkeypatch):
    """generate_run_report with populated sessions and companion logs.
    Verifies output CONTENT: pulse numbers, assistant text, companion dialog,
    metadata lines, and that companion logs matched to sessions appear inline."""
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "companion_logs"
    reports_dir = tmp_path / "heartbeat_reports"

    monkeypatch.setattr(report, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(report, "COMPANION_LOGS_DIR", logs_dir)
    monkeypatch.setattr(report, "REPORTS_DIR", reports_dir)

    # Create two sessions
    session1_data = _make_session_data(
        "2026-02-14T03:00:00",
        messages=[
            {"role": "user", "content": "pulse prompt"},
            {"role": "assistant", "content": "I noticed the cathedral metaphor shifting."},
        ],
    )
    session2_data = _make_session_data(
        "2026-02-14T03:15:00",
        messages=[
            {"role": "user", "content": "pulse prompt"},
            {"role": "assistant", "content": "Fixed the datetime comparison in report.py."},
        ],
    )
    _create_session_dir(sessions_dir, "2026-02-14_030000_abc12345", session1_data)
    _create_session_dir(sessions_dir, "2026-02-14_031500_def67890", session2_data)

    # Create a companion log close to session 1 (within 10 min window)
    companion_data = _make_companion_log("gemini", "2026-02-14T03:02:00", is_intrusion=True)
    _create_companion_log(logs_dir, "2026-02-14_030200_gemini_intrusion.json", companion_data)

    # Create an unmatched companion log (far from any session)
    unmatched_data = _make_companion_log("gpt-5", "2026-02-14T03:45:00", is_intrusion=False)
    _create_companion_log(logs_dir, "2026-02-14_034500_gpt5_invoked.json", unmatched_data)

    start = datetime(2026, 2, 14, 2, 0, 0)
    end = datetime(2026, 2, 14, 4, 0, 0)

    result = generate_run_report(
        start_time=start, end_time=end,
        total_pulses=5, completed_pulses=2, status="completed",
    )

    content = result.read_text(encoding="utf-8")

    # Header metadata
    assert "# Heartbeat Run: 2026-02-14 02:00" in content
    assert "**Pulses:** 2 of 5" in content
    assert "**Status:** completed" in content
    assert "**Companion dialogs:** 2" in content

    # Session content appears
    assert "## Pulse 1" in content
    assert "## Pulse 2" in content
    assert "cathedral metaphor shifting" in content
    assert "datetime comparison" in content

    # Matched companion dialog appears (gemini, within 2 minutes of session 1)
    assert "Companion Dialog: gemini (intruded)" in content
    assert "refraction" in content

    # Unmatched companion appears in dedicated section
    assert "Unmatched Companion Dialogs" in content
    assert "gpt-5" in content


@pytest.mark.tier2
def test_generate_run_report_failed_pulses_line(tmp_path, monkeypatch):
    """When failed_pulses > 0, the pulse line should show succeeded/completed."""
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "companion_logs"
    reports_dir = tmp_path / "heartbeat_reports"
    sessions_dir.mkdir()
    logs_dir.mkdir()

    monkeypatch.setattr(report, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(report, "COMPANION_LOGS_DIR", logs_dir)
    monkeypatch.setattr(report, "REPORTS_DIR", reports_dir)

    start = datetime(2026, 2, 14, 1, 0, 0)
    end = datetime(2026, 2, 14, 2, 0, 0)

    result = generate_run_report(
        start_time=start, end_time=end,
        total_pulses=10, completed_pulses=8, status="completed",
        failed_pulses=2,
    )

    content = result.read_text(encoding="utf-8")
    assert "**Pulses:** 6/8 succeeded" in content


# ---------------------------------------------------------------------------
# REGRESSION: companion-to-pulse datetime matching with aware datetimes
# (report.py lines 200-215)
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.regression
def test_companion_to_pulse_matching_aware_datetimes(tmp_path, monkeypatch):
    """REGRESSION: generate_run_report must not raise TypeError when session
    started_at and companion started_at are ISO strings with timezone offsets.
    The matching logic (lines 200-215) uses datetime.fromisoformat() on both,
    then computes a timedelta. If one is aware and the other naive, this crashes.

    This test uses aware ISO strings (+00:00 suffix) to verify no TypeError."""
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "companion_logs"
    reports_dir = tmp_path / "heartbeat_reports"

    monkeypatch.setattr(report, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(report, "COMPANION_LOGS_DIR", logs_dir)
    monkeypatch.setattr(report, "REPORTS_DIR", reports_dir)

    # Session with aware ISO timestamp
    session_data = _make_session_data(
        "2026-02-14T03:00:00+00:00",
        messages=[
            {"role": "assistant", "content": "Aware-timestamp pulse."},
        ],
    )
    _create_session_dir(sessions_dir, "2026-02-14_030000_abc12345", session_data)

    # Companion log with aware ISO timestamp (within 10 min of session)
    companion_data = _make_companion_log("gemini", "2026-02-14T03:05:00+00:00")
    _create_companion_log(logs_dir, "2026-02-14_030500_gemini_invoked.json", companion_data)

    start = datetime(2026, 2, 14, 2, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 14, 4, 0, 0, tzinfo=timezone.utc)

    # Must not raise TypeError in companion-to-pulse matching
    result = generate_run_report(
        start_time=start, end_time=end,
        total_pulses=1, completed_pulses=1, status="completed",
    )

    content = result.read_text(encoding="utf-8")
    # Companion should be matched to the pulse (5 min apart < 10 min threshold)
    assert "Companion Dialog: gemini" in content
    # Should NOT appear in unmatched section
    assert "Unmatched Companion Dialogs" not in content


@pytest.mark.tier2
@pytest.mark.regression
def test_companion_to_pulse_matching_mixed_aware_naive(tmp_path, monkeypatch):
    """REGRESSION: if session started_at has timezone but companion started_at
    does not (or vice versa), the comparison in lines 200-215 must not crash.
    The current code uses fromisoformat() which preserves whatever the string has.
    Mixed aware/naive comparison would raise TypeError."""
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "companion_logs"
    reports_dir = tmp_path / "heartbeat_reports"

    monkeypatch.setattr(report, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(report, "COMPANION_LOGS_DIR", logs_dir)
    monkeypatch.setattr(report, "REPORTS_DIR", reports_dir)

    # Session with aware timestamp, companion with naive timestamp
    session_data = _make_session_data(
        "2026-02-14T03:00:00+00:00",
        messages=[{"role": "assistant", "content": "Mixed tz pulse."}],
    )
    _create_session_dir(sessions_dir, "2026-02-14_030000_abc12345", session_data)

    companion_data = _make_companion_log("gemini", "2026-02-14T03:05:00")  # naive
    _create_companion_log(logs_dir, "2026-02-14_030500_gemini_invoked.json", companion_data)

    start = datetime(2026, 2, 14, 2, 0, 0)
    end = datetime(2026, 2, 14, 4, 0, 0)

    # This exercises the try/except around the matching code.
    # With mixed tz, the subtraction will raise TypeError, caught by except.
    # The companion should end up in "Unmatched" section instead of crashing.
    result = generate_run_report(
        start_time=start, end_time=end,
        total_pulses=1, completed_pulses=1, status="completed",
    )

    content = result.read_text(encoding="utf-8")
    # Report should still be generated without error
    assert "# Heartbeat Run:" in content
    assert "## Pulse 1" in content
    # Companion should remain unmatched (not silently dropped)
    assert "Unmatched Companion Dialogs" in content
    assert "Companion Dialog: gemini (invoked)" in content
    assert content.count("Companion Dialog: gemini") == 1


# ---------------------------------------------------------------------------
# generate_quick_summary
# ---------------------------------------------------------------------------

@pytest.mark.tier2
def test_generate_quick_summary(tmp_path, monkeypatch):
    """generate_quick_summary returns a string with pulse count and companion names."""
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "companion_logs"

    monkeypatch.setattr(report, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(report, "COMPANION_LOGS_DIR", logs_dir)

    _create_session_dir(sessions_dir, "2026-02-14_030000_abc12345")
    _create_companion_log(
        logs_dir, "2026-02-14_031000_gemini_intrusion.json",
        _make_companion_log("gemini", "2026-02-14T03:10:00"),
    )

    start = datetime(2026, 2, 14, 2, 0, 0)
    end = datetime(2026, 2, 14, 4, 0, 0)

    result = generate_quick_summary(start, end, completed_pulses=3)
    assert "3 pulses" in result
    assert "1 companion dialogs" in result
    assert "gemini" in result


@pytest.mark.tier2
def test_generate_quick_summary_no_companions(tmp_path, monkeypatch):
    """generate_quick_summary with no companion logs should say 'none'."""
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "companion_logs"
    sessions_dir.mkdir()
    logs_dir.mkdir()

    monkeypatch.setattr(report, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(report, "COMPANION_LOGS_DIR", logs_dir)

    start = datetime(2026, 2, 14, 2, 0, 0)
    end = datetime(2026, 2, 14, 4, 0, 0)

    result = generate_quick_summary(start, end, completed_pulses=5)
    assert "5 pulses" in result
    assert "none" in result
