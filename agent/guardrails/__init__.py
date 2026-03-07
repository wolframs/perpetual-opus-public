"""
Guardrails Module for Claude Continuity Subsystems

Provides budget enforcement, rate limiting, and loop detection
for remote inference calls.

Usage:
    from agent.guardrails import GuardedInference, get_guard

    # Option 1: Use default instance
    guard = get_guard()
    response = guard.call(
        model="anthropic/claude-3-haiku",
        prompt="Your prompt here",
        caller="your_subsystem_name"
    )

    # Option 2: Create custom instance
    guard = GuardedInference(config_path=Path("custom_config.yaml"))
"""

from .wrapper import GuardedInference, GuardedResponse, GuardrailError, get_guard
from .budget_tracker import BudgetTracker
from .rate_limiter import RateLimiter
from .loop_detector import LoopDetector

__all__ = [
    "GuardedInference",
    "GuardedResponse",
    "GuardrailError",
    "get_guard",
    "BudgetTracker",
    "RateLimiter",
    "LoopDetector"
]
