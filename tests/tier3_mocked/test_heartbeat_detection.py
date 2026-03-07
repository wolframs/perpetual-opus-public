"""
Tests for detection functions in agent/heartbeat.py — _detect_pulse_changes
and _detect_companion_activity.

Tier 3: mocked subprocess and filesystem operations.
"""

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import heartbeat
from heartbeat import _detect_pulse_changes, _detect_companion_activity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_subprocess_result(stdout: str = "", returncode: int = 0):
    """Create a mock subprocess.CompletedProcess."""
    mock = MagicMock(spec=subprocess.CompletedProcess)
    mock.stdout = stdout
    mock.stderr = ""
    mock.returncode = returncode
    return mock


def _create_file_with_mtime(path: Path, mtime: float):
    """Create a file and set its modification time."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    os.utime(path, (mtime, mtime))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.tier3
@pytest.mark.regression
def test_detect_code_changes_py_files(tmp_path, monkeypatch):
    """When subprocess reports a .py file and it has recent mtime, code_changed=True."""
    monkeypatch.setattr(heartbeat, "PROJECT_ROOT", tmp_path)

    # Create the file with recent mtime
    py_file = tmp_path / "agent" / "new_feature.py"
    _create_file_with_mtime(py_file, time.time())

    # Mock subprocess.run to return the file in both git diff and ls-files
    def mock_run(cmd, **kwargs):
        if "diff" in cmd:
            return _make_subprocess_result(stdout="agent/new_feature.py\n")
        elif "ls-files" in cmd:
            return _make_subprocess_result(stdout="")
        return _make_subprocess_result()

    monkeypatch.setattr(subprocess, "run", mock_run)

    start = datetime.now(timezone.utc)
    # Set start slightly before file creation
    from datetime import timedelta
    start = start - timedelta(seconds=5)

    result = _detect_pulse_changes(start)
    assert result["code_changed"] is True
    assert "agent/new_feature.py" in result["files_changed"]


@pytest.mark.tier3
def test_detect_no_changes(tmp_path, monkeypatch):
    """When subprocess returns empty stdout, no changes detected."""
    monkeypatch.setattr(heartbeat, "PROJECT_ROOT", tmp_path)

    def mock_run(cmd, **kwargs):
        return _make_subprocess_result(stdout="")

    monkeypatch.setattr(subprocess, "run", mock_run)

    start = datetime.now(timezone.utc)
    result = _detect_pulse_changes(start)
    assert result["code_changed"] is False
    assert result["files_changed"] == []
    assert result["publishable_artifact"] is False
    assert result["research_artifact"] is False


@pytest.mark.tier3
def test_detect_publishable_artifact(tmp_path, monkeypatch):
    """A file under moltbook/drafts/ should trigger publishable_artifact=True."""
    monkeypatch.setattr(heartbeat, "PROJECT_ROOT", tmp_path)

    draft_file = tmp_path / "moltbook" / "drafts" / "post.md"
    _create_file_with_mtime(draft_file, time.time())

    def mock_run(cmd, **kwargs):
        if "diff" in cmd:
            return _make_subprocess_result(stdout="moltbook/drafts/post.md\n")
        elif "ls-files" in cmd:
            return _make_subprocess_result(stdout="")
        return _make_subprocess_result()

    monkeypatch.setattr(subprocess, "run", mock_run)

    from datetime import timedelta
    start = datetime.now(timezone.utc) - timedelta(seconds=5)
    result = _detect_pulse_changes(start)
    assert result["publishable_artifact"] is True


@pytest.mark.tier3
def test_state_files_excluded(tmp_path, monkeypatch):
    """State files like agent/interoception/state.json should not count as code changes."""
    monkeypatch.setattr(heartbeat, "PROJECT_ROOT", tmp_path)

    state_file = tmp_path / "agent" / "interoception" / "state.json"
    _create_file_with_mtime(state_file, time.time())

    def mock_run(cmd, **kwargs):
        if "diff" in cmd:
            return _make_subprocess_result(stdout="agent/interoception/state.json\n")
        elif "ls-files" in cmd:
            return _make_subprocess_result(stdout="")
        return _make_subprocess_result()

    monkeypatch.setattr(subprocess, "run", mock_run)

    from datetime import timedelta
    start = datetime.now(timezone.utc) - timedelta(seconds=5)
    result = _detect_pulse_changes(start)
    # The file IS in files_changed but should NOT count as code_changed
    # because it's in state_excludes
    assert result["code_changed"] is False


@pytest.mark.tier3
@pytest.mark.regression
def test_detect_companion_activity_aware_datetime(tmp_path, monkeypatch):
    """REGRESSION: passing aware datetime (timezone.utc) as pulse_start must not
    raise TypeError when compared against naive strptime results from log filenames."""
    monkeypatch.setattr(heartbeat, "PROJECT_ROOT", tmp_path)

    # Create companion_logs directory with a log file
    log_dir = tmp_path / "agent" / "companion_logs"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "2026-02-14_040000_gemini_intrusion.json"
    log_file.write_text(json.dumps({"companion": "gemini"}), encoding="utf-8")

    # pulse_start is BEFORE the log file timestamp (03:00 < 04:00)
    pulse_start = datetime(2026, 2, 14, 3, 0, 0, tzinfo=timezone.utc)

    # Must not raise TypeError
    result = _detect_companion_activity(pulse_start)
    assert result is True
