"""
Datetime regression tests: aware vs naive datetime comparison bugs (Feb 14 class).

Tier 4 + regression: ensures all code paths that compare aware datetimes against
naive strptime results handle tzinfo stripping correctly.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import report
from report import find_sessions_in_range, find_companion_logs_in_range
import heartbeat
from heartbeat import _detect_companion_activity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_session_dir(base: Path, name: str) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _create_log_file(base: Path, name: str, content: dict = None) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    f = base / name
    data = content or {"companion": "gemini"}
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.tier4
@pytest.mark.regression
def test_aware_naive_comparison_report_sessions(tmp_path, monkeypatch):
    """find_sessions_in_range with aware (timezone.utc) start/end must not raise
    TypeError when session dir timestamps are parsed as naive."""
    sessions_dir = tmp_path / "sessions"
    _create_session_dir(sessions_dir, "2026-02-14_030000_deadbeef")

    monkeypatch.setattr(report, "SESSIONS_DIR", sessions_dir)

    start = datetime(2026, 2, 14, 2, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 14, 4, 0, 0, tzinfo=timezone.utc)

    # Must not raise TypeError
    result = find_sessions_in_range(start, end)
    assert len(result) == 1


@pytest.mark.tier4
@pytest.mark.regression
def test_aware_naive_comparison_report_companions(tmp_path, monkeypatch):
    """find_companion_logs_in_range with aware start/end must not raise TypeError."""
    logs_dir = tmp_path / "companion_logs"
    _create_log_file(logs_dir, "2026-02-14_031500_kimi_invoked.json")

    monkeypatch.setattr(report, "COMPANION_LOGS_DIR", logs_dir)

    start = datetime(2026, 2, 14, 3, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 14, 4, 0, 0, tzinfo=timezone.utc)

    result = find_companion_logs_in_range(start, end)
    assert len(result) == 1


@pytest.mark.tier4
@pytest.mark.regression
def test_aware_naive_comparison_companion_activity(tmp_path, monkeypatch):
    """_detect_companion_activity with aware pulse_start must not raise TypeError."""
    monkeypatch.setattr(heartbeat, "PROJECT_ROOT", tmp_path)

    log_dir = tmp_path / "agent" / "companion_logs"
    _create_log_file(log_dir, "2026-02-14_040000_gemini_intrusion.json")

    pulse_start = datetime(2026, 2, 14, 3, 0, 0, tzinfo=timezone.utc)

    # Must not raise TypeError
    result = _detect_companion_activity(pulse_start)
    assert result is True


@pytest.mark.tier4
@pytest.mark.regression
def test_isoformat_suffix_still_string():
    """datetime.now(timezone.utc).isoformat() should end with '+00:00' and be a string."""
    iso = datetime.now(timezone.utc).isoformat()
    assert isinstance(iso, str)
    assert iso.endswith("+00:00")


