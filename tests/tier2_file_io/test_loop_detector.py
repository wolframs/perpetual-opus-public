"""
Tests for agent/guardrails/loop_detector.py — tier 2 (file I/O via tmp_path).

Verifies loop detection, threshold behavior, window pruning, reset, and normalization.
"""

import json
from datetime import datetime, timedelta

import pytest

from guardrails.loop_detector import LoopDetector


@pytest.mark.tier2
class TestLoopDetector:

    def test_first_prompt_not_loop(self, guardrails_config, tmp_path):
        """A single occurrence of a prompt is not flagged as a loop."""
        state_file = tmp_path / "loop_state.json"
        detector = LoopDetector(guardrails_config, state_file)

        detector.record_prompt("run the heartbeat", "heartbeat")
        allowed, reason = detector.check_loop("run the heartbeat", "heartbeat")

        assert allowed is True
        assert reason is None

    def test_same_prompt_threshold_times_is_loop(self, guardrails_config, tmp_path):
        """Recording the same prompt threshold times triggers loop detection."""
        state_file = tmp_path / "loop_state.json"
        detector = LoopDetector(guardrails_config, state_file)
        threshold = guardrails_config["loop_detection"]["same_prompt_threshold"]  # 3

        for _ in range(threshold):
            detector.record_prompt("stuck in a loop", "heartbeat")

        allowed, reason = detector.check_loop("stuck in a loop", "heartbeat")
        assert allowed is False
        assert reason is not None
        assert "loop" in reason.lower() or "Loop" in reason

    def test_different_prompts_pass(self, guardrails_config, tmp_path):
        """Three different prompts do not trigger loop detection."""
        state_file = tmp_path / "loop_state.json"
        detector = LoopDetector(guardrails_config, state_file)

        prompts = ["first prompt", "second prompt", "third prompt"]
        for p in prompts:
            detector.record_prompt(p, "heartbeat")

        for p in prompts:
            allowed, reason = detector.check_loop(p, "heartbeat")
            assert allowed is True
            assert reason is None

    def test_window_pruning(self, guardrails_config, tmp_path):
        """Records older than the detection window are pruned on load."""
        state_file = tmp_path / "loop_state.json"
        window = guardrails_config["loop_detection"]["window_seconds"]  # 300

        # Write state with records beyond the window
        old_ts = (datetime.now() - timedelta(seconds=window + 60)).isoformat()
        detector_temp = LoopDetector(guardrails_config, state_file)
        prompt_hash = detector_temp._hash_prompt("old prompt")

        data = {
            "records": [
                {"hash": prompt_hash, "timestamp": old_ts, "subsystem": "heartbeat"},
                {"hash": prompt_hash, "timestamp": old_ts, "subsystem": "heartbeat"},
                {"hash": prompt_hash, "timestamp": old_ts, "subsystem": "heartbeat"},
            ],
            "last_updated": datetime.now().isoformat(),
        }
        state_file.write_text(json.dumps(data))

        # New detector should prune all stale records
        detector = LoopDetector(guardrails_config, state_file)
        assert len(detector.records) == 0

        # And the same prompt should now be allowed
        allowed, reason = detector.check_loop("old prompt", "heartbeat")
        assert allowed is True

    def test_reset_per_subsystem(self, guardrails_config, tmp_path):
        """reset(subsystem) clears only that subsystem's records."""
        state_file = tmp_path / "loop_state.json"
        detector = LoopDetector(guardrails_config, state_file)

        detector.record_prompt("heartbeat prompt", "heartbeat")
        detector.record_prompt("heartbeat prompt", "heartbeat")
        detector.record_prompt("companion prompt", "companion")
        detector.record_prompt("companion prompt", "companion")

        detector.reset("heartbeat")

        # Heartbeat records gone
        allowed, reason = detector.check_loop("heartbeat prompt", "heartbeat")
        assert allowed is True

        # Companion records remain
        assert any(r.subsystem == "companion" for r in detector.records)

    def test_whitespace_normalization(self, guardrails_config, tmp_path):
        """Prompts differing only in whitespace produce the same hash."""
        state_file = tmp_path / "loop_state.json"
        detector = LoopDetector(guardrails_config, state_file)

        hash1 = detector._hash_prompt("hello  world")
        hash2 = detector._hash_prompt("hello world")
        hash3 = detector._hash_prompt("  hello   world  ")

        assert hash1 == hash2
        assert hash2 == hash3
