"""
Tests for agent/guardrails/rate_limiter.py — tier 2 (file I/O via tmp_path).

Verifies token bucket creation, consumption, refill, burst, and rate-exceeded behavior.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from guardrails.rate_limiter import RateLimiter


@pytest.mark.tier2
class TestRateLimiter:

    def test_new_bucket_starts_full(self, guardrails_config, tmp_path):
        """A freshly created bucket starts at max_tokens (per_minute + burst_allowance)."""
        state_file = tmp_path / "rate_state.json"
        limiter = RateLimiter(guardrails_config, state_file)

        allowed, reason = limiter.check_rate("general")
        assert allowed is True
        assert reason is None

        status = limiter.get_status("general")
        # general: per_minute=10 + burst_allowance=3 = 13
        assert status["tokens_available"] == pytest.approx(13.0, abs=0.5)
        assert status["max_tokens"] == 13.0

    def test_consume_then_check(self, guardrails_config, tmp_path):
        """Consuming tokens reduces the available count."""
        state_file = tmp_path / "rate_state.json"
        limiter = RateLimiter(guardrails_config, state_file)

        # Force bucket creation first
        limiter.check_rate("general")
        limiter.consume("general", 12)

        status = limiter.get_status("general")
        # Started at 13, consumed 12 -> ~1 (plus tiny refill from elapsed time)
        assert status["tokens_available"] < 2.0

    def test_refill_over_elapsed_time(self, guardrails_config, tmp_path):
        """Tokens refill based on elapsed time since last update."""
        state_file = tmp_path / "rate_state.json"
        limiter = RateLimiter(guardrails_config, state_file)

        # Create bucket and drain it
        limiter.check_rate("general")
        limiter.consume("general", 13)

        # Verify it's near-empty
        status = limiter.get_status("general")
        assert status["tokens_available"] < 1.0

        # Mock time forward by 60 seconds
        # general refill_rate = 10/60 = 0.1667 tokens/sec
        # After 60s: 60 * (10/60) = 10 tokens refilled
        future = datetime.now() + timedelta(seconds=60)
        with patch("guardrails.rate_limiter.datetime") as mock_dt:
            mock_dt.now.return_value = future
            mock_dt.fromisoformat = datetime.fromisoformat
            status = limiter.get_status("general")

        assert status["tokens_available"] >= 9.0

    def test_rate_exceeded_returns_wait_time(self, guardrails_config, tmp_path):
        """When all tokens are consumed, check_rate returns False with a wait message."""
        state_file = tmp_path / "rate_state.json"
        limiter = RateLimiter(guardrails_config, state_file)

        # Drain the bucket completely
        limiter.check_rate("general")
        limiter.consume("general", 13)

        allowed, reason = limiter.check_rate("general")
        assert allowed is False
        assert reason is not None
        assert "wait" in reason.lower()

    def test_burst_allowance_added_to_max(self, guardrails_config, tmp_path):
        """Burst allowance adds to per_minute to form max_tokens."""
        state_file = tmp_path / "rate_state.json"
        limiter = RateLimiter(guardrails_config, state_file)

        # general: per_minute=10, burst_allowance=3 -> max=13
        status = limiter.get_status("general")
        assert status["max_tokens"] == 13.0

        # heartbeat: per_minute=5, burst_allowance=2 -> max=7
        status_hb = limiter.get_status("heartbeat")
        assert status_hb["max_tokens"] == 7.0

    def test_persistence_roundtrip(self, guardrails_config, tmp_path):
        """State persists across limiter instances via shared state file."""
        state_file = tmp_path / "rate_state.json"

        # First limiter: create bucket and consume tokens
        limiter1 = RateLimiter(guardrails_config, state_file)
        limiter1.check_rate("general")
        limiter1.consume("general", 10)

        status1 = limiter1.get_status("general")
        tokens_after_consume = status1["tokens_available"]
        assert tokens_after_consume < 4.0  # Started at 13, consumed 10

        # Second limiter: loads from same state file
        limiter2 = RateLimiter(guardrails_config, state_file)
        status2 = limiter2.get_status("general")

        # Tokens should reflect the consumption (plus minor refill from elapsed time)
        assert status2["tokens_available"] < 5.0
        assert "general" in limiter2.buckets

    def test_unknown_subsystem_falls_back_to_general(self, guardrails_config, tmp_path):
        """An unknown subsystem falls back to 'general' config."""
        state_file = tmp_path / "rate_state.json"
        limiter = RateLimiter(guardrails_config, state_file)

        # "unknown_subsystem" is not in rate_limits config — should use "general" fallback
        allowed, reason = limiter.check_rate("unknown_subsystem")
        assert allowed is True

        status = limiter.get_status("unknown_subsystem")
        # Should get general's config: per_minute=10 + burst_allowance=3 = 13
        assert status["max_tokens"] == 13.0
