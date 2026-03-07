"""
Tests for agent/session.py dataclasses.

Verifies Session/SessionMessage roundtrip, timestamps, and ID format.
"""

import re

import pytest

from session import Session, SessionMessage


@pytest.mark.tier1
class TestSessionDataclasses:

    def test_session_roundtrip(self):
        """Session survives to_dict() -> from_dict() with all fields intact."""
        original = Session(
            session_id="2026-02-14_031500_abcd1234",
            started_at="2026-02-14T03:15:00+00:00",
            status="active",
            summary="Test session",
        )
        original.add_message("human", "hello")
        original.add_message("assistant", "hi there", {"model": "opus"})

        data = original.to_dict()
        restored = Session.from_dict(data)

        assert restored.session_id == original.session_id
        assert restored.started_at == original.started_at
        assert restored.status == original.status
        assert restored.summary == original.summary
        assert len(restored.messages) == len(original.messages)

        for orig_msg, rest_msg in zip(original.messages, restored.messages):
            assert rest_msg.role == orig_msg.role
            assert rest_msg.content == orig_msg.content
            assert rest_msg.timestamp == orig_msg.timestamp
            assert rest_msg.metadata == orig_msg.metadata

    def test_add_message_with_timestamp(self):
        """add_message() auto-generates an ISO timestamp with timezone offset."""
        session = Session(
            session_id="2026-02-14_031500_abcd1234",
            started_at="2026-02-14T03:15:00+00:00",
        )
        session.add_message("assistant", "hello")

        assert len(session.messages) == 1
        msg = session.messages[0]
        assert msg.role == "assistant"
        assert msg.content == "hello"
        # datetime.now(timezone.utc).isoformat() produces a '+' for UTC offset
        assert "+" in msg.timestamp, f"Expected timezone offset in timestamp: {msg.timestamp!r}"

    def test_session_id_format(self):
        """SessionManager._generate_session_id produces YYYY-MM-DD_HHMMSS_hash8."""
        from session import SessionManager
        from datetime import datetime, timezone

        mgr = SessionManager.__new__(SessionManager)
        ts = datetime(2026, 2, 14, 3, 15, 0, tzinfo=timezone.utc)
        sid = mgr._generate_session_id(ts)

        pattern = r"^\d{4}-\d{2}-\d{2}_\d{6}_[0-9a-f]{8}$"
        assert re.match(pattern, sid), f"Session ID {sid!r} doesn't match expected format"

    def test_default_status_is_active(self):
        """A fresh Session defaults to 'active' status and no summary."""
        session = Session(
            session_id="test",
            started_at="2026-01-01T00:00:00+00:00",
        )
        assert session.status == "active"
        assert session.summary is None

    def test_empty_messages_by_default(self):
        """A fresh Session starts with an empty message list."""
        session = Session(
            session_id="test",
            started_at="2026-01-01T00:00:00+00:00",
        )
        assert session.messages == []

    def test_from_dict_missing_optional_fields(self):
        """from_dict() handles missing optional fields gracefully."""
        data = {
            "session_id": "test",
            "started_at": "2026-01-01T00:00:00+00:00",
        }
        session = Session.from_dict(data)
        assert session.status == "active"
        assert session.summary is None
        assert session.messages == []

    def test_message_metadata_default(self):
        """SessionMessage defaults to empty metadata dict."""
        msg = SessionMessage(
            role="human",
            content="test",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        assert msg.metadata == {}
