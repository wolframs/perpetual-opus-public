"""
Tests for CompanionState, CompanionFailureState, and CompanionManager
from agent/companions/companions.py.

Tier 3: tests real methods on dataclasses and manager logic.
Mocks file I/O and API calls — zero external calls.
"""

from unittest.mock import patch, MagicMock
import random

import pytest

from companions.companions import (
    CompanionState,
    CompanionFailureState,
    CompanionManager,
    CYCLE_LENGTH,
    RANDOM_INTRUSION_CHANCE,
)


# ---------------------------------------------------------------------------
# CompanionFailureState tests
# ---------------------------------------------------------------------------


@pytest.mark.tier3
class TestCompanionFailureState:
    """Tests for the circuit breaker dataclass."""

    def test_initial_state_has_zero_failures(self):
        fs = CompanionFailureState()
        assert fs.consecutive_failures == 0
        assert fs.last_failure == ""
        assert fs.last_success == ""

    def test_record_failure_increments_count(self):
        fs = CompanionFailureState()
        fs.record_failure()
        assert fs.consecutive_failures == 1
        assert fs.last_failure != ""  # timestamp was set

    def test_record_failure_sets_timestamp(self):
        fs = CompanionFailureState()
        fs.record_failure()
        # Should be a valid ISO timestamp with timezone
        assert "T" in fs.last_failure
        assert "+" in fs.last_failure or "Z" in fs.last_failure

    def test_record_success_resets_consecutive_failures(self):
        fs = CompanionFailureState()
        fs.record_failure()
        fs.record_failure()
        fs.record_failure()
        assert fs.consecutive_failures == 3
        fs.record_success()
        assert fs.consecutive_failures == 0

    def test_record_success_sets_timestamp(self):
        fs = CompanionFailureState()
        fs.record_success()
        assert fs.last_success != ""
        assert "T" in fs.last_success

    def test_cooldown_zero_below_threshold(self):
        """Below FAILURE_THRESHOLD, no cooldown."""
        fs = CompanionFailureState()
        assert fs.cooldown_pulses() == 0

        fs.record_failure()
        assert fs.consecutive_failures == 1
        assert fs.consecutive_failures < CompanionFailureState.FAILURE_THRESHOLD
        assert fs.cooldown_pulses() == 0

    def test_cooldown_base_at_threshold(self):
        """At exactly FAILURE_THRESHOLD, cooldown = BASE_COOLDOWN_PULSES."""
        fs = CompanionFailureState()
        for _ in range(CompanionFailureState.FAILURE_THRESHOLD):
            fs.record_failure()
        # exponent = FAILURE_THRESHOLD - FAILURE_THRESHOLD = 0
        # cooldown = BASE_COOLDOWN_PULSES * 2^0 = 3
        assert fs.cooldown_pulses() == CompanionFailureState.BASE_COOLDOWN_PULSES

    def test_cooldown_exponential_backoff(self):
        """Each failure beyond threshold doubles the cooldown."""
        fs = CompanionFailureState()
        threshold = CompanionFailureState.FAILURE_THRESHOLD
        base = CompanionFailureState.BASE_COOLDOWN_PULSES

        # Go to threshold + 1 failures
        for _ in range(threshold + 1):
            fs.record_failure()
        # exponent = (threshold+1) - threshold = 1
        # cooldown = base * 2^1 = 6
        assert fs.cooldown_pulses() == base * 2

        # One more failure: threshold + 2
        fs.record_failure()
        # exponent = 2, cooldown = base * 4 = 12
        assert fs.cooldown_pulses() == base * 4

        # One more: threshold + 3
        fs.record_failure()
        # exponent = 3, cooldown = base * 8 = 24
        assert fs.cooldown_pulses() == base * 8

    def test_cooldown_capped_at_max(self):
        """Cooldown never exceeds MAX_COOLDOWN_PULSES."""
        fs = CompanionFailureState()
        max_cool = CompanionFailureState.MAX_COOLDOWN_PULSES
        # Record many failures to blow past the cap
        for _ in range(20):
            fs.record_failure()
        assert fs.cooldown_pulses() == max_cool

    def test_is_available_below_threshold(self):
        """Companion is always available if failures < threshold."""
        fs = CompanionFailureState()
        assert fs.is_available(current_pulse=0, last_failure_pulse=0) is True

        fs.record_failure()
        # Still below threshold (threshold=2, failures=1)
        assert fs.is_available(current_pulse=0, last_failure_pulse=0) is True

    def test_is_available_false_during_cooldown(self):
        """Companion is unavailable during cooldown period."""
        fs = CompanionFailureState()
        for _ in range(CompanionFailureState.FAILURE_THRESHOLD):
            fs.record_failure()
        # cooldown = 3 pulses. Failed at pulse 10.
        # At pulse 11 (1 pulse later): not available
        assert fs.is_available(current_pulse=11, last_failure_pulse=10) is False
        # At pulse 12 (2 pulses later): not available
        assert fs.is_available(current_pulse=12, last_failure_pulse=10) is False

    def test_is_available_true_after_cooldown(self):
        """Companion becomes available again after cooldown expires."""
        fs = CompanionFailureState()
        for _ in range(CompanionFailureState.FAILURE_THRESHOLD):
            fs.record_failure()
        cooldown = fs.cooldown_pulses()  # 3
        # At exactly cooldown pulses later: available
        assert fs.is_available(current_pulse=10 + cooldown, last_failure_pulse=10) is True

    def test_to_dict_roundtrip(self):
        """to_dict -> from_dict preserves all fields."""
        fs = CompanionFailureState()
        fs.record_failure()
        fs.record_failure()

        d = fs.to_dict()
        restored = CompanionFailureState.from_dict(d)

        assert restored.consecutive_failures == fs.consecutive_failures
        assert restored.last_failure == fs.last_failure
        assert restored.last_success == fs.last_success

    def test_from_dict_defaults(self):
        """from_dict with empty dict gives defaults."""
        fs = CompanionFailureState.from_dict({})
        assert fs.consecutive_failures == 0
        assert fs.last_failure == ""
        assert fs.last_success == ""


# ---------------------------------------------------------------------------
# CompanionState tests
# ---------------------------------------------------------------------------


@pytest.mark.tier3
class TestCompanionState:
    """Tests for the companion state dataclass."""

    def test_initial_state(self):
        state = CompanionState()
        assert state.pulse_count == 0
        assert state.total_pulse_count == 0
        assert state.invocation_used is False
        assert state.companion_failures == {}
        assert state.failure_pulse == {}

    def test_get_failure_state_creates_on_first_access(self):
        state = CompanionState()
        fs = state.get_failure_state("gemini")
        assert isinstance(fs, CompanionFailureState)
        assert fs.consecutive_failures == 0
        assert "gemini" in state.companion_failures

    def test_get_failure_state_returns_same_instance(self):
        state = CompanionState()
        fs1 = state.get_failure_state("gemini")
        fs2 = state.get_failure_state("gemini")
        assert fs1 is fs2

    def test_record_failure_updates_state(self):
        state = CompanionState()
        state.total_pulse_count = 5
        state.record_failure("gemini")

        fs = state.get_failure_state("gemini")
        assert fs.consecutive_failures == 1
        assert state.failure_pulse["gemini"] == 5

    def test_record_failure_updates_failure_pulse_to_current(self):
        """Each failure records the current total_pulse_count."""
        state = CompanionState()
        state.total_pulse_count = 10
        state.record_failure("gemini")
        assert state.failure_pulse["gemini"] == 10

        state.total_pulse_count = 15
        state.record_failure("gemini")
        assert state.failure_pulse["gemini"] == 15

    def test_record_success_resets_failures(self):
        state = CompanionState()
        state.record_failure("gemini")
        state.record_failure("gemini")
        assert state.get_failure_state("gemini").consecutive_failures == 2

        state.record_success("gemini")
        assert state.get_failure_state("gemini").consecutive_failures == 0

    def test_is_companion_available_fresh_companion(self):
        state = CompanionState()
        assert state.is_companion_available("gemini") is True

    def test_is_companion_available_during_cooldown(self):
        """After threshold failures, companion in cooldown is unavailable."""
        state = CompanionState()
        state.total_pulse_count = 10

        for _ in range(CompanionFailureState.FAILURE_THRESHOLD):
            state.record_failure("gemini")

        # Still at pulse 10 — 0 pulses since failure, need 3
        assert state.is_companion_available("gemini") is False

    def test_is_companion_available_after_cooldown(self):
        """After enough pulses pass, companion becomes available again."""
        state = CompanionState()
        state.total_pulse_count = 10

        for _ in range(CompanionFailureState.FAILURE_THRESHOLD):
            state.record_failure("gemini")

        cooldown = state.get_failure_state("gemini").cooldown_pulses()
        state.total_pulse_count = 10 + cooldown
        assert state.is_companion_available("gemini") is True

    def test_to_dict_roundtrip(self):
        """to_dict -> from_dict preserves all fields."""
        state = CompanionState()
        state.pulse_count = 3
        state.total_pulse_count = 42
        state.invocation_used = True
        state.last_reset = "2026-01-01T00:00:00+00:00"
        state.record_failure("gemini")
        state.record_failure("gemini")
        state.record_success("kimi")

        d = state.to_dict()
        restored = CompanionState.from_dict(d)

        assert restored.pulse_count == 3
        assert restored.total_pulse_count == 42
        assert restored.invocation_used is True
        assert restored.last_reset == "2026-01-01T00:00:00+00:00"
        assert restored.get_failure_state("gemini").consecutive_failures == 2
        assert restored.get_failure_state("kimi").consecutive_failures == 0
        assert restored.failure_pulse["gemini"] == state.failure_pulse["gemini"]

    def test_from_dict_backfills_missing_failure_pulse(self):
        """from_dict backfills failure_pulse for companions with failures but no entry."""
        data = {
            "total_pulse_count": 50,
            "companion_failures": {
                "gemini": {"consecutive_failures": 3, "last_failure": "", "last_success": ""},
            },
            "failure_pulse": {},  # missing entry for gemini
        }
        state = CompanionState.from_dict(data)
        # Backfill should set failure_pulse to total_pulse_count
        assert state.failure_pulse["gemini"] == 50

    def test_from_dict_defaults(self):
        """from_dict with empty dict gives defaults."""
        state = CompanionState.from_dict({})
        assert state.pulse_count == 0
        assert state.total_pulse_count == 0
        assert state.invocation_used is False


# ---------------------------------------------------------------------------
# CompanionManager tests (mocked file I/O)
# ---------------------------------------------------------------------------


@pytest.mark.tier3
class TestCompanionManager:
    """Tests for CompanionManager with mocked load/save and prompts."""

    def _make_manager(self, state=None, prompts=None):
        """Create a CompanionManager with mocked dependencies."""
        if state is None:
            state = CompanionState()
        if prompts is None:
            prompts = {"gemini": "You are Gemini.", "kimi": "You are Kimi."}

        with patch("companions.companions.load_state", return_value=state), \
             patch("companions.companions.load_companion_prompts", return_value=prompts):
            mgr = CompanionManager()
        return mgr

    def test_start_pulse_increments_counts(self):
        """start_pulse increments both pulse_count and total_pulse_count."""
        mgr = self._make_manager()
        with patch("companions.companions.save_state"):
            mgr.start_pulse()
        assert mgr.state.pulse_count == 1
        assert mgr.state.total_pulse_count == 1

    def test_start_pulse_multiple_increments(self):
        """Multiple start_pulse calls track cycle position."""
        mgr = self._make_manager()
        with patch("companions.companions.save_state"):
            for _ in range(4):
                mgr.start_pulse()
        assert mgr.state.pulse_count == 4
        assert mgr.state.total_pulse_count == 4

    def test_start_pulse_resets_at_cycle_boundary(self):
        """When pulse_count exceeds CYCLE_LENGTH, cycle resets."""
        state = CompanionState()
        state.pulse_count = CYCLE_LENGTH  # At end of cycle
        state.invocation_used = True
        mgr = self._make_manager(state=state)

        with patch("companions.companions.save_state"):
            mgr.start_pulse()

        # pulse_count was CYCLE_LENGTH, incremented to CYCLE_LENGTH+1,
        # which is > CYCLE_LENGTH, so it resets to 1
        assert mgr.state.pulse_count == 1
        assert mgr.state.invocation_used is False
        assert mgr.state.last_reset != ""

    def test_start_pulse_no_reset_within_cycle(self):
        """No reset when pulse_count is still within CYCLE_LENGTH."""
        state = CompanionState()
        state.pulse_count = CYCLE_LENGTH - 2
        state.invocation_used = True
        mgr = self._make_manager(state=state)

        with patch("companions.companions.save_state"):
            mgr.start_pulse()

        # CYCLE_LENGTH - 2 + 1 = CYCLE_LENGTH - 1, still <= CYCLE_LENGTH
        assert mgr.state.pulse_count == CYCLE_LENGTH - 1
        assert mgr.state.invocation_used is True  # NOT reset

    @patch("companions.companions.save_state")
    def test_start_pulse_random_intrusion_returns_companion(self, mock_save):
        """When random roll succeeds, start_pulse returns a companion name."""
        mgr = self._make_manager()
        with patch("random.random", return_value=0.01):  # < 0.12
            result = mgr.start_pulse()
        assert result in ("gemini", "kimi")

    @patch("companions.companions.save_state")
    def test_start_pulse_no_intrusion_returns_none(self, mock_save):
        """When random roll fails, start_pulse returns None."""
        mgr = self._make_manager()
        with patch("random.random", return_value=0.99):  # > 0.12
            result = mgr.start_pulse()
        assert result is None

    @patch("companions.companions.save_state")
    def test_start_pulse_intrusion_skips_unavailable_companions(self, mock_save):
        """Random intrusion skips companions in cooldown."""
        state = CompanionState()
        # Put gemini in cooldown
        state.total_pulse_count = 10
        for _ in range(CompanionFailureState.FAILURE_THRESHOLD):
            state.record_failure("gemini")

        mgr = self._make_manager(state=state)
        with patch("random.random", return_value=0.01):
            result = mgr.start_pulse()

        # Only kimi should be available
        assert result == "kimi"

    @patch("companions.companions.save_state")
    def test_start_pulse_intrusion_none_when_all_in_cooldown(self, mock_save):
        """Random intrusion returns None when all companions are in cooldown."""
        state = CompanionState()
        state.total_pulse_count = 10
        for name in ("gemini", "kimi"):
            for _ in range(CompanionFailureState.FAILURE_THRESHOLD):
                state.record_failure(name)

        mgr = self._make_manager(state=state)
        with patch("random.random", return_value=0.01):
            result = mgr.start_pulse()

        assert result is None

    def test_can_invoke_true_initially(self):
        mgr = self._make_manager()
        assert mgr.can_invoke() is True

    def test_can_invoke_false_after_use(self):
        state = CompanionState()
        state.invocation_used = True
        mgr = self._make_manager(state=state)
        assert mgr.can_invoke() is False

    @patch("companions.companions.save_state")
    def test_invoke_companion_marks_used(self, mock_save):
        mgr = self._make_manager()
        result = mgr.invoke_companion("gemini")
        assert result is True
        assert mgr.state.invocation_used is True

    @patch("companions.companions.save_state")
    def test_invoke_companion_fails_if_already_used(self, mock_save):
        state = CompanionState()
        state.invocation_used = True
        mgr = self._make_manager(state=state)
        result = mgr.invoke_companion("gemini")
        assert result is False

    def test_get_cycle_status(self):
        state = CompanionState()
        state.pulse_count = 3
        state.invocation_used = True
        mgr = self._make_manager(state=state)

        status = mgr.get_cycle_status()
        assert status["pulse_in_cycle"] == 3
        assert status["cycle_length"] == CYCLE_LENGTH
        assert status["invocation_available"] is False
        assert status["pulses_until_reset"] == CYCLE_LENGTH - 3 + 1

    def test_get_available_companions(self):
        prompts = {"gemini": "prompt1", "kimi": "prompt2", "glm5": "prompt3"}
        mgr = self._make_manager(prompts=prompts)
        available = mgr.get_available_companions()
        assert set(available) == {"gemini", "kimi", "glm5"}

    @patch("companions.companions.save_state")
    def test_start_pulse_saves_state(self, mock_save):
        """start_pulse calls save_state."""
        mgr = self._make_manager()
        mgr.start_pulse()
        assert mock_save.called

    @patch("companions.companions.save_state")
    def test_full_cycle_resets_invocation(self, mock_save):
        """Simulating a full cycle: invocation resets after CYCLE_LENGTH pulses."""
        mgr = self._make_manager()

        # Suppress random intrusions for deterministic test
        with patch("random.random", return_value=0.99):
            # Run through a full cycle
            for _ in range(CYCLE_LENGTH):
                mgr.start_pulse()

            # After CYCLE_LENGTH pulses, pulse_count = CYCLE_LENGTH
            assert mgr.state.pulse_count == CYCLE_LENGTH

            # Use invocation mid-cycle
            mgr.invoke_companion("gemini")
            assert mgr.can_invoke() is False

            # One more pulse triggers reset (CYCLE_LENGTH + 1 > CYCLE_LENGTH)
            mgr.start_pulse()
            assert mgr.state.pulse_count == 1
            assert mgr.can_invoke() is True


# ---------------------------------------------------------------------------
# Circuit breaker integration through CompanionState
# ---------------------------------------------------------------------------


@pytest.mark.tier3
class TestCircuitBreakerIntegration:
    """Tests for circuit breaker behavior through CompanionState methods."""

    def test_multiple_companions_independent(self):
        """Failure state is per-companion."""
        state = CompanionState()
        state.total_pulse_count = 10
        state.record_failure("gemini")
        state.record_failure("gemini")

        assert state.get_failure_state("gemini").consecutive_failures == 2
        assert state.get_failure_state("kimi").consecutive_failures == 0
        assert state.is_companion_available("kimi") is True

    def test_exponential_backoff_progression(self):
        """Verify the exact backoff values: 3, 6, 12, 24, 48, 48..."""
        base = CompanionFailureState.BASE_COOLDOWN_PULSES  # 3
        threshold = CompanionFailureState.FAILURE_THRESHOLD  # 2
        max_cool = CompanionFailureState.MAX_COOLDOWN_PULSES  # 48

        fs = CompanionFailureState()
        expected_sequence = [0, 0, 3, 6, 12, 24, 48, 48, 48]
        for i, expected in enumerate(expected_sequence):
            if i > 0:
                fs.record_failure()
            assert fs.cooldown_pulses() == expected, (
                f"At {fs.consecutive_failures} failures, "
                f"expected cooldown={expected}, got {fs.cooldown_pulses()}"
            )

    def test_recovery_clears_cooldown(self):
        """After recovery (success), cooldown drops to zero."""
        state = CompanionState()
        state.total_pulse_count = 10

        # Build up failures
        for _ in range(5):
            state.record_failure("gemini")

        assert not state.is_companion_available("gemini")

        # Recover
        state.record_success("gemini")
        assert state.get_failure_state("gemini").cooldown_pulses() == 0
        assert state.is_companion_available("gemini") is True

    def test_cooldown_boundary_exact(self):
        """Companion becomes available at exactly cooldown pulses, not before."""
        state = CompanionState()
        state.total_pulse_count = 100
        for _ in range(CompanionFailureState.FAILURE_THRESHOLD):
            state.record_failure("gemini")
        # failure_pulse = 100, cooldown = 3

        # Advance total_pulse_count and check
        state.total_pulse_count = 101  # 1 pulse later
        assert state.is_companion_available("gemini") is False

        state.total_pulse_count = 102  # 2 pulses later
        assert state.is_companion_available("gemini") is False

        state.total_pulse_count = 103  # 3 pulses later (== cooldown)
        assert state.is_companion_available("gemini") is True
