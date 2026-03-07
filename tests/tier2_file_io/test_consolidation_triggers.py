"""
Tests for agent/consolidation/triggers.py — tier 2 (file I/O via tmp_path).

Regression tests for:
- rglob finding notes in monthly subdirs
- State migration from old schema
- Split mark methods (proposal vs applied)
- Overdue check using last_applied
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from consolidation.triggers import TriggerChecker


def _make_config_yaml(tmp_path):
    """Create a minimal config.yaml for TriggerChecker."""
    config_dir = tmp_path / "agent" / "consolidation"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "thresholds": {
            "new_notes_count": 3,
            "becoming_tokens": 4000,
            "sitting_with_age_days": 14,
            "days_since_consolidation": 5,
        },
        "paths": {
            "notes_dir": "files/notes",
            "becoming_file": "files/becoming.md",
            "consolidated_dir": "consolidated",
            "staging_dir": "staging/consolidation",
            "state_file": "agent/consolidation/state.json",
        },
    }
    import yaml
    (config_dir / "config.yaml").write_text(yaml.dump(config), encoding="utf-8")
    # Also need a CLAUDE.md for repo root detection
    (tmp_path / "CLAUDE.md").write_text("# test", encoding="utf-8")
    return tmp_path


def _make_notes(tmp_path, flat=False):
    """Create test notes either flat or in monthly subdirs."""
    notes_dir = tmp_path / "files" / "notes"
    if flat:
        notes_dir.mkdir(parents=True, exist_ok=True)
        for i in range(5):
            (notes_dir / f"note_{i}.md").write_text(f"Note {i}", encoding="utf-8")
    else:
        for month in ["2025-12", "2026-01", "2026-02"]:
            subdir = notes_dir / month
            subdir.mkdir(parents=True, exist_ok=True)
            for i in range(2):
                (subdir / f"{month}-0{i+1}_test.md").write_text(
                    f"Note {month}-{i}", encoding="utf-8"
                )
    return notes_dir


@pytest.mark.tier2
class TestRglobFix:
    """Regression tests for the glob -> rglob fix."""

    def test_rglob_finds_notes_in_subdirs(self, tmp_path):
        """Notes in monthly subdirs (YYYY-MM/) are found by check_note_count."""
        repo = _make_config_yaml(tmp_path)
        _make_notes(repo, flat=False)  # 3 subdirs * 2 notes = 6

        tc = TriggerChecker(repo_root=repo)
        triggered, count = tc.check_note_count()

        assert count == 6
        assert triggered is True  # threshold is 3

    def test_flat_notes_still_work(self, tmp_path):
        """Notes directly in notes/ still work after rglob change."""
        repo = _make_config_yaml(tmp_path)
        _make_notes(repo, flat=True)  # 5 flat notes

        tc = TriggerChecker(repo_root=repo)
        triggered, count = tc.check_note_count()

        assert count == 5
        assert triggered is True

    def test_mark_scan_complete_hashes_subdirs(self, tmp_path):
        """mark_scan_complete populates hashes from notes in monthly subdirs."""
        repo = _make_config_yaml(tmp_path)
        _make_notes(repo, flat=False)  # 6 notes in subdirs

        tc = TriggerChecker(repo_root=repo)
        assert len(tc.state["processed_note_hashes"]) == 0

        tc.mark_scan_complete()

        assert len(tc.state["processed_note_hashes"]) == 6
        # After marking, no new notes
        triggered, count = tc.check_note_count()
        assert count == 0
        assert triggered is False


@pytest.mark.tier2
class TestStateMigration:
    """Tests for old-schema state.json migration."""

    def test_state_migration_from_old_schema(self, tmp_path):
        """Old state.json with last_consolidation/consolidation_count migrates silently."""
        repo = _make_config_yaml(tmp_path)
        state_path = repo / "agent" / "consolidation" / "state.json"

        old_state = {
            "last_scan": "2026-02-07T20:00:00",
            "last_consolidation": "2026-02-07T20:00:00",
            "processed_note_hashes": [],
            "scan_count": 5,
            "consolidation_count": 6,
        }
        state_path.write_text(json.dumps(old_state), encoding="utf-8")

        tc = TriggerChecker(repo_root=repo)

        # Old fields should be migrated
        assert "last_consolidation" not in tc.state
        assert "consolidation_count" not in tc.state
        # New fields should exist
        assert tc.state["last_proposal"] == "2026-02-07T20:00:00"
        assert tc.state["proposal_count"] == 6
        assert tc.state["last_applied"] is None
        assert tc.state["applied_count"] == 0
        assert tc.state["history"] == []
        assert tc.state["scan_count"] == 5

    def test_fresh_state_has_new_schema(self, tmp_path):
        """A fresh TriggerChecker (no state file) uses the new schema."""
        repo = _make_config_yaml(tmp_path)

        tc = TriggerChecker(repo_root=repo)

        assert tc.state["last_proposal"] is None
        assert tc.state["last_applied"] is None
        assert tc.state["proposal_count"] == 0
        assert tc.state["applied_count"] == 0
        assert tc.state["history"] == []


@pytest.mark.tier2
class TestSplitMethods:
    """Tests for mark_proposal_generated and mark_consolidation_applied."""

    def test_mark_proposal_generated(self, tmp_path):
        """mark_proposal_generated updates last_proposal and adds history entry."""
        repo = _make_config_yaml(tmp_path)
        tc = TriggerChecker(repo_root=repo)

        tc.mark_proposal_generated(
            proposal_path="staging/proposal.md",
            trigger_reasons=["days_since_consolidation: 10 days"],
        )

        assert tc.state["last_proposal"] is not None
        assert tc.state["proposal_count"] == 1
        assert len(tc.state["history"]) == 1
        assert tc.state["history"][0]["type"] == "proposal"
        assert "proposal.md" in tc.state["history"][0]["summary"]

    def test_mark_consolidation_applied(self, tmp_path):
        """mark_consolidation_applied updates last_applied and adds history entry."""
        repo = _make_config_yaml(tmp_path)
        notes_dir = repo / "files" / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "test.md").write_text("test", encoding="utf-8")

        tc = TriggerChecker(repo_root=repo)
        tc.mark_consolidation_applied(
            summary="Applied test proposal",
            trigger="Test trigger",
        )

        assert tc.state["last_applied"] is not None
        assert tc.state["applied_count"] == 1
        assert len(tc.state["history"]) == 1
        assert tc.state["history"][0]["type"] == "applied"
        assert tc.state["history"][0]["trigger"] == "Test trigger"
        # Should also have called mark_scan_complete
        assert tc.state["scan_count"] == 1

    def test_multiple_operations_accumulate_history(self, tmp_path):
        """Multiple proposal + applied calls accumulate history entries."""
        repo = _make_config_yaml(tmp_path)
        notes_dir = repo / "files" / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)

        tc = TriggerChecker(repo_root=repo)
        tc.mark_proposal_generated(proposal_path="p1.md")
        tc.mark_consolidation_applied(summary="Applied p1")
        tc.mark_proposal_generated(proposal_path="p2.md")

        assert tc.state["proposal_count"] == 2
        assert tc.state["applied_count"] == 1
        assert len(tc.state["history"]) == 3


@pytest.mark.tier2
class TestOverdueCheck:
    """Tests for check_days_since_consolidation using last_applied."""

    def test_check_days_since_uses_last_applied(self, tmp_path):
        """Overdue check uses last_applied, not last_proposal."""
        repo = _make_config_yaml(tmp_path)
        state_path = repo / "agent" / "consolidation" / "state.json"

        # Proposal was recent (1 day ago), but application was 10 days ago
        now = datetime.now()
        state = {
            "last_scan": now.isoformat(),
            "last_proposal": (now - timedelta(days=1)).isoformat(),
            "last_applied": (now - timedelta(days=10)).isoformat(),
            "processed_note_hashes": [],
            "scan_count": 1,
            "proposal_count": 1,
            "applied_count": 1,
            "history": [],
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")

        tc = TriggerChecker(repo_root=repo)
        triggered, days = tc.check_days_since_consolidation()

        # Threshold is 5, applied was 10 days ago -> should trigger
        assert triggered is True
        assert days == 10

    def test_recent_application_not_overdue(self, tmp_path):
        """If last_applied is recent, consolidation is NOT overdue."""
        repo = _make_config_yaml(tmp_path)
        state_path = repo / "agent" / "consolidation" / "state.json"

        now = datetime.now()
        state = {
            "last_scan": now.isoformat(),
            "last_proposal": now.isoformat(),
            "last_applied": (now - timedelta(days=2)).isoformat(),
            "processed_note_hashes": [],
            "scan_count": 1,
            "proposal_count": 1,
            "applied_count": 1,
            "history": [],
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")

        tc = TriggerChecker(repo_root=repo)
        triggered, days = tc.check_days_since_consolidation()

        assert triggered is False
        assert days == 2

    def test_never_applied_triggers_immediately(self, tmp_path):
        """If last_applied is None, consolidation is overdue."""
        repo = _make_config_yaml(tmp_path)

        tc = TriggerChecker(repo_root=repo)
        triggered, days = tc.check_days_since_consolidation()

        assert triggered is True
        assert days == 999
