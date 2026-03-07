"""
Tests for agent/session.py SessionManager — tier 2 (file I/O via tmp_path).

Verifies session lifecycle: start, save, load, end, and listing.
"""

import re
from unittest.mock import patch

import pytest

from session import SessionManager, update_runner_state


@pytest.mark.tier2
class TestSessionManager:

    def test_start_creates_session_with_id(self, tmp_path):
        """start_session() creates a current_session whose ID matches YYYY-MM-DD_HHMMSS_hash8."""
        exports = tmp_path / "exports"
        mgr = SessionManager(exports_dir=exports)

        session = mgr.start_session()
        assert session is not None
        assert mgr.current_session is session

        pattern = r"^\d{4}-\d{2}-\d{2}_\d{6}_[0-9a-f]{8}$"
        assert re.match(pattern, session.session_id), (
            f"Session ID {session.session_id!r} doesn't match YYYY-MM-DD_HHMMSS_hash8"
        )

    def test_session_id_format_via_start(self, tmp_path):
        """Session ID format verified through normal instantiation (not __new__ hack)."""
        exports = tmp_path / "exports"
        mgr = SessionManager(exports_dir=exports)
        session = mgr.start_session()

        parts = session.session_id.split("_")
        # Format: YYYY-MM-DD_HHMMSS_hash8 → 3 parts after split
        assert len(parts) == 3
        # Date part
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0])
        # Time part
        assert re.match(r"^\d{6}$", parts[1])
        # Hash part
        assert re.match(r"^[0-9a-f]{8}$", parts[2])

    def test_save_load_roundtrip(self, tmp_path):
        """A saved session can be loaded back with the same session_id and messages."""
        exports = tmp_path / "exports"
        mgr = SessionManager(exports_dir=exports)

        session = mgr.start_session()
        session.add_message("human", "hello from test")
        mgr.save_session()

        # Load by session_id
        loaded = mgr.load_session(session.session_id)
        assert loaded is not None
        assert loaded.session_id == session.session_id
        assert len(loaded.messages) == len(session.messages)
        assert loaded.messages[0].content == "hello from test"

    def test_save_load_roundtrip_full_fidelity(self, tmp_path):
        """Verify role, timestamp, metadata, status, and summary all survive roundtrip."""
        exports = tmp_path / "exports"
        mgr = SessionManager(exports_dir=exports)

        session = mgr.start_session()
        session.add_message("human", "user input", metadata={"source": "test"})
        session.add_message("assistant", "response text", metadata={"model": "opus"})
        session.status = "paused"
        session.summary = "Test summary for roundtrip"
        mgr.save_session()

        loaded = mgr.load_session(session.session_id)
        assert loaded is not None

        # Top-level fields
        assert loaded.session_id == session.session_id
        assert loaded.started_at == session.started_at
        assert loaded.status == "paused"
        assert loaded.summary == "Test summary for roundtrip"

        # Message 0: human
        msg0 = loaded.messages[0]
        assert msg0.role == "human"
        assert msg0.content == "user input"
        assert msg0.timestamp  # non-empty ISO string
        assert msg0.metadata == {"source": "test"}

        # Message 1: assistant
        msg1 = loaded.messages[1]
        assert msg1.role == "assistant"
        assert msg1.content == "response text"
        assert msg1.timestamp
        assert msg1.metadata == {"model": "opus"}

    def test_load_nonexistent_session_returns_none(self, tmp_path):
        """Loading a session ID that doesn't exist returns None."""
        exports = tmp_path / "exports"
        mgr = SessionManager(exports_dir=exports)
        result = mgr.load_session("1999-01-01_000000_deadbeef")
        assert result is None

    def test_end_session_sets_status(self, tmp_path):
        """end_session() writes the status and summary, then clears current_session."""
        exports = tmp_path / "exports"
        mgr = SessionManager(exports_dir=exports)

        session = mgr.start_session()
        sid = session.session_id

        mgr.end_session("paused", "taking a break")
        assert mgr.current_session is None

        loaded = mgr.load_session(sid)
        assert loaded is not None
        assert loaded.status == "paused"
        assert loaded.summary == "taking a break"

    def test_list_sessions_returns_dirs(self, tmp_path):
        """list_sessions() returns one entry per saved session directory."""
        exports = tmp_path / "exports"
        mgr = SessionManager(exports_dir=exports)

        # Save two separate sessions
        s1 = mgr.start_session(initial_prompt="first")
        mgr.save_session()
        sid1 = s1.session_id

        # End the first so we can start another
        mgr.end_session("completed")

        s2 = mgr.start_session(initial_prompt="second")
        mgr.save_session()
        sid2 = s2.session_id

        sessions = mgr.list_sessions()
        assert len(sessions) == 2
        assert sid1 in sessions
        assert sid2 in sessions


@pytest.mark.tier2
class TestUpdateRunnerState:

    def test_update_runner_state_writes_file(self, tmp_path):
        """update_runner_state() writes status, task, and notes to runner_state.md."""
        runner_state_file = tmp_path / "agent" / "runner_state.md"
        runner_state_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("session.PROJECT_ROOT", tmp_path):
            update_runner_state(
                status="RUNNING",
                current_task="heartbeat pulse 5",
                notes="All systems nominal",
            )

        content = runner_state_file.read_text(encoding="utf-8")
        assert "## Status: RUNNING" in content
        assert "heartbeat pulse 5" in content
        assert "All systems nominal" in content
        assert "Last updated:" in content

    def test_update_runner_state_without_optional_fields(self, tmp_path):
        """update_runner_state() works with only status (no task or notes)."""
        runner_state_file = tmp_path / "agent" / "runner_state.md"
        runner_state_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("session.PROJECT_ROOT", tmp_path):
            update_runner_state(status="IDLE")

        content = runner_state_file.read_text(encoding="utf-8")
        assert "## Status: IDLE" in content
        assert "Current Task" not in content
        assert "Notes" not in content
