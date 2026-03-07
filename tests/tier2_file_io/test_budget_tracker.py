"""
Tests for agent/guardrails/budget_tracker.py — tier 2 (file I/O via tmp_path).

Verifies spend recording, persistence, budget checks, warnings, and pruning.
"""

import json
from datetime import datetime, timedelta

import pytest

from guardrails.budget_tracker import BudgetTracker


@pytest.mark.tier2
class TestBudgetTracker:

    def test_fresh_tracker_empty(self, guardrails_config, tmp_path):
        """New BudgetTracker with nonexistent state file starts with empty records."""
        state_file = tmp_path / "budget_state.json"
        tracker = BudgetTracker(guardrails_config, state_file)

        assert tracker.records == []
        allowed, reason = tracker.check_budget(0.01)
        assert allowed is True
        assert reason is None

    def test_record_spend_persists_to_disk(self, guardrails_config, tmp_path):
        """record_spend writes to disk; a new tracker from the same file recovers records."""
        state_file = tmp_path / "budget_state.json"
        tracker = BudgetTracker(guardrails_config, state_file)

        cost = tracker.record_spend("default", 100_000, 50_000, "heartbeat")
        assert cost > 0
        assert state_file.exists()

        # Create a second tracker from the same file — records should survive
        tracker2 = BudgetTracker(guardrails_config, state_file)
        assert len(tracker2.records) == 1
        assert tracker2.records[0].model == "default"
        assert tracker2.records[0].caller == "heartbeat"

    def test_hourly_budget_exceeded(self, guardrails_config, tmp_path):
        """Spending up to the hourly max causes check_budget to reject the next call."""
        state_file = tmp_path / "budget_state.json"
        tracker = BudgetTracker(guardrails_config, state_file)

        hourly_max = guardrails_config["budget"]["hourly_max_usd"]  # 2.0

        # Use default pricing: input=1.0/M, output=2.0/M
        # 1M input + 0.5M output = 1.0 + 1.0 = 2.0 USD per call
        tracker.record_spend("default", 1_000_000, 500_000, "test")

        allowed, reason = tracker.check_budget(0.01)
        assert allowed is False
        assert reason is not None
        assert "Hourly" in reason or "hourly" in reason.lower()

    def test_daily_budget_exceeded(self, guardrails_config, tmp_path):
        """Spending up to the daily max causes check_budget to reject on daily limit."""
        state_file = tmp_path / "budget_state.json"

        # To trigger the daily check (not hourly), we need records that are
        # older than 1 hour (so they don't count toward hourly) but within
        # 24 hours (so they count toward daily).  Seed the state file directly.
        hours_ago_2 = (datetime.now() - timedelta(hours=2)).isoformat()
        hours_ago_3 = (datetime.now() - timedelta(hours=3)).isoformat()
        data = {
            "records": [
                {
                    "timestamp": hours_ago_2,
                    "model": "default",
                    "input_tokens": 2_500_000,
                    "output_tokens": 1_250_000,
                    "cost_usd": 5.0,
                    "caller": "test",
                },
                {
                    "timestamp": hours_ago_3,
                    "model": "default",
                    "input_tokens": 2_500_000,
                    "output_tokens": 1_250_000,
                    "cost_usd": 5.0,
                    "caller": "test",
                },
            ],
            "last_updated": datetime.now().isoformat(),
        }
        state_file.write_text(json.dumps(data))

        tracker = BudgetTracker(guardrails_config, state_file)
        # Daily total is $10.0, hourly total is $0.0 — daily check should trigger
        allowed, reason = tracker.check_budget(0.01)
        assert allowed is False
        assert reason is not None
        assert "Daily" in reason or "daily" in reason.lower()

    def test_cost_calculation_model_pricing(self, guardrails_config, tmp_path):
        """calculate_cost uses per-model pricing from config (opus: 15/75 per M tokens)."""
        state_file = tmp_path / "budget_state.json"
        tracker = BudgetTracker(guardrails_config, state_file)

        cost = tracker.calculate_cost("claude-3-opus", 1_000_000, 1_000_000)
        # 1M input * 15.0/M + 1M output * 75.0/M = 15.0 + 75.0 = 90.0
        assert cost == pytest.approx(90.0)

    def test_warning_at_75_percent(self, guardrails_config, tmp_path):
        """Spending 76% of hourly limit triggers a warning."""
        state_file = tmp_path / "budget_state.json"
        tracker = BudgetTracker(guardrails_config, state_file)

        hourly_max = guardrails_config["budget"]["hourly_max_usd"]  # 2.0
        # Need to spend > 75% of 2.0 = > 1.5 USD
        # default pricing: input=1.0/M, output=2.0/M
        # 1M input + 250K output = 1.0 + 0.5 = 1.5 ... need slightly more
        # 1M input + 260K output = 1.0 + 0.52 = 1.52 USD (> 1.5)
        tracker.record_spend("default", 1_000_000, 260_000, "test")

        warnings = tracker.get_warnings()
        assert len(warnings) > 0
        assert any("Hourly" in w or "hourly" in w.lower() for w in warnings)

    def test_old_records_pruned(self, guardrails_config, tmp_path):
        """Records older than 25 hours are pruned when a new tracker loads state."""
        state_file = tmp_path / "budget_state.json"

        # Write state with an old record (26 hours ago)
        old_ts = (datetime.now() - timedelta(hours=26)).isoformat()
        data = {
            "records": [
                {
                    "timestamp": old_ts,
                    "model": "default",
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "cost_usd": 0.001,
                    "caller": "old_caller",
                }
            ],
            "last_updated": datetime.now().isoformat(),
        }
        state_file.write_text(json.dumps(data))

        # New tracker should prune the stale record
        tracker = BudgetTracker(guardrails_config, state_file)
        assert len(tracker.records) == 0
