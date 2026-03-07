"""
Smoke test for guardrails module.

Run with: python agent/guardrails/test_guardrails.py
"""

import sys
from pathlib import Path

# Add guardrails directory to path for direct import
guardrails_dir = Path(__file__).parent
sys.path.insert(0, str(guardrails_dir))

from wrapper import GuardedInference, get_guard
from budget_tracker import BudgetTracker
from rate_limiter import RateLimiter
from loop_detector import LoopDetector


def test_budget_tracking():
    """Test budget tracking without API calls."""
    print("\n--- Budget Tracking Test ---")

    guard = GuardedInference()

    # Check initial status
    status = guard.budget.get_status()
    print(f"Initial daily spend: ${status['daily_spend']:.4f}")
    print(f"Daily limit: ${status['daily_limit']:.2f}")

    # Simulate some spending
    guard.budget.record_spend(
        model="anthropic/claude-3-haiku",
        input_tokens=1000,
        output_tokens=500,
        caller="test"
    )

    status = guard.budget.get_status()
    print(f"After simulated call: ${status['daily_spend']:.4f}")

    # Check if we can make more calls
    allowed, reason = guard.budget.check_budget(0.01)
    print(f"Can spend $0.01 more: {allowed}")

    print("Budget tracking: PASS")


def test_rate_limiting():
    """Test rate limiting without API calls."""
    print("\n--- Rate Limiting Test ---")

    guard = GuardedInference()

    # Check initial rate
    allowed, reason = guard.rate_limiter.check_rate("consolidation")
    print(f"First call allowed: {allowed}")

    # Consume some tokens
    for i in range(5):
        guard.rate_limiter.consume("consolidation")

    status = guard.rate_limiter.get_status("consolidation")
    print(f"Tokens remaining after 5 calls: {status['tokens_available']:.1f}")

    print("Rate limiting: PASS")


def test_loop_detection():
    """Test loop detection without API calls."""
    print("\n--- Loop Detection Test ---")

    guard = GuardedInference()

    # Reset state for clean test
    guard.loop_detector.reset()

    test_prompt = "This is a test prompt that might be repeated"

    # First two should be allowed
    for i in range(2):
        allowed, reason = guard.loop_detector.check_loop(test_prompt, "test")
        print(f"Call {i+1}: allowed={allowed}")
        guard.loop_detector.record_prompt(test_prompt, "test")

    # Third should be blocked (threshold is 3)
    allowed, reason = guard.loop_detector.check_loop(test_prompt, "test")
    print(f"Call 3 (should be blocked): allowed={allowed}")
    if reason:
        print(f"  Reason: {reason}")

    # Different prompt should be allowed
    allowed, reason = guard.loop_detector.check_loop("Different prompt", "test")
    print(f"Different prompt: allowed={allowed}")

    # Clean up
    guard.loop_detector.reset()

    print("Loop detection: PASS")


def test_pre_flight_checks():
    """Test pre-flight checks without API calls."""
    print("\n--- Pre-flight Checks Test ---")

    guard = GuardedInference()

    # Reset loop detector for clean test
    guard.loop_detector.reset()

    allowed, errors = guard.check_all(
        model="anthropic/claude-3-haiku",
        prompt="Test prompt for pre-flight checks",
        caller="test"
    )

    print(f"Pre-flight check passed: {allowed}")
    if errors:
        print(f"Errors: {errors}")

    print("Pre-flight checks: PASS")


def test_status_display():
    """Test status display."""
    print("\n--- Status Display Test ---")

    guard = GuardedInference()

    status = guard.get_status()

    print("Budget status:")
    print(f"  Daily: ${status['budget']['daily_spend']:.4f} / ${status['budget']['daily_limit']:.2f}")
    print(f"  Hourly: ${status['budget']['hourly_spend']:.4f} / ${status['budget']['hourly_limit']:.2f}")

    print("Loop detection status:")
    print(f"  Active records: {status['loop_detection']['active_records']}")

    print("Status display: PASS")


def test_guarded_call_without_api_key():
    """Test that missing API key is handled gracefully."""
    print("\n--- Missing API Key Test ---")

    import os
    original_key = os.environ.get("OPENROUTER_API_KEY")

    # Temporarily remove API key
    if "OPENROUTER_API_KEY" in os.environ:
        del os.environ["OPENROUTER_API_KEY"]

    guard = GuardedInference()
    guard.api_key = None  # Force no key

    response = guard.call(
        model="anthropic/claude-3-haiku",
        prompt="Test prompt",
        caller="test"
    )

    print(f"Success: {response.success}")
    print(f"Error: {response.error}")

    # Restore key if it existed
    if original_key:
        os.environ["OPENROUTER_API_KEY"] = original_key

    print("Missing API key handling: PASS")


if __name__ == "__main__":
    print("=" * 50)
    print("Guardrails Module Smoke Test")
    print("=" * 50)

    try:
        test_budget_tracking()
        test_rate_limiting()
        test_loop_detection()
        test_pre_flight_checks()
        test_status_display()
        test_guarded_call_without_api_key()

        print("\n" + "=" * 50)
        print("All tests PASSED")
        print("=" * 50)

    except Exception as e:
        print(f"\nTest FAILED with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
