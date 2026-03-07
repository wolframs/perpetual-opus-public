"""
Guardrail Wrapper for Subsystem Inference Calls

Main entry point that composes budget tracking, rate limiting, and loop detection.
Wraps calls to OpenRouter API with safety checks.
"""

import json
import os
import yaml
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass

# Handle both relative and direct imports
try:
    from .budget_tracker import BudgetTracker
    from .rate_limiter import RateLimiter
    from .loop_detector import LoopDetector
except ImportError:
    from budget_tracker import BudgetTracker
    from rate_limiter import RateLimiter
    from loop_detector import LoopDetector


@dataclass
class GuardedResponse:
    success: bool
    content: Optional[str]
    error: Optional[str]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str
    warnings: list[str]


class GuardrailError(Exception):
    """Raised when a guardrail blocks execution."""
    pass


class GuardedInference:
    """
    Wrapper for making LLM API calls through guardrails.

    Usage:
        guard = GuardedInference()
        response = guard.call(
            model="anthropic/claude-3-haiku",
            prompt="Summarize this text...",
            caller="consolidation_daemon"
        )
    """

    OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, config_path: Optional[Path] = None):
        # Determine paths
        self.base_dir = Path(__file__).parent
        self.config_path = config_path or self.base_dir / "config.yaml"
        self.state_dir = self.base_dir / "state"
        self.state_dir.mkdir(exist_ok=True)

        # Load config
        self.config = self._load_config()

        # Initialize components
        self.budget = BudgetTracker(
            self.config,
            self.state_dir / "budget_state.json"
        )
        self.rate_limiter = RateLimiter(
            self.config,
            self.state_dir / "rate_state.json"
        )
        self.loop_detector = LoopDetector(
            self.config,
            self.state_dir / "loop_state.json"
        )

        # Audit log
        self.audit_file = Path(self.config.get("audit", {}).get(
            "log_file",
            "agent/guardrails/audit.jsonl"
        ))

        # API key from environment
        self.api_key = os.environ.get("OPENROUTER_API_KEY")

    def _load_config(self) -> dict:
        """Load configuration from YAML file."""
        if self.config_path.exists():
            return yaml.safe_load(self.config_path.read_text())
        return {}

    def _estimate_cost(self, model: str, prompt: str, max_output_tokens: int = 1000) -> float:
        """Estimate cost for a call before making it."""
        # Rough token estimate: 4 chars per token
        input_tokens = len(prompt) // 4
        return self.budget.calculate_cost(model, input_tokens, max_output_tokens)

    def _audit_log(self, record: dict):
        """Append to audit log."""
        log_level = self.config.get("audit", {}).get("log_level", "all")
        if log_level == "none":
            return
        if log_level == "errors_only" and record.get("success", True):
            return

        self.audit_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.audit_file, "a") as f:
            f.write(json.dumps(record) + "\n")

    def check_all(self, model: str, prompt: str, caller: str) -> tuple[bool, list[str]]:
        """
        Run all guardrail checks before making a call.

        Returns:
            (allowed, errors) - allowed is True if all checks pass
        """
        errors = []

        # Estimate cost
        estimated_cost = self._estimate_cost(model, prompt)

        # Budget check
        allowed, reason = self.budget.check_budget(estimated_cost)
        if not allowed:
            errors.append(reason)

        # Rate limit check
        allowed, reason = self.rate_limiter.check_rate(caller)
        if not allowed:
            errors.append(reason)

        # Loop detection check
        allowed, reason = self.loop_detector.check_loop(prompt, caller)
        if not allowed:
            errors.append(reason)

        return len(errors) == 0, errors

    def call(
        self,
        model: str,
        prompt: str,
        caller: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        skip_guardrails: bool = False
    ) -> GuardedResponse:
        """
        Make a guarded API call to OpenRouter.

        Args:
            model: Model identifier (e.g., "anthropic/claude-3-haiku")
            prompt: User prompt
            caller: Subsystem making the call (for rate limiting)
            system_prompt: Optional system prompt
            max_tokens: Maximum output tokens
            temperature: Sampling temperature
            skip_guardrails: If True, bypass all checks (use with caution)

        Returns:
            GuardedResponse with content or error
        """
        warnings = []

        # Pre-flight checks
        if not skip_guardrails:
            allowed, errors = self.check_all(model, prompt, caller)
            if not allowed:
                self._audit_log({
                    "timestamp": datetime.now().isoformat(),
                    "caller": caller,
                    "model": model,
                    "success": False,
                    "blocked_by": errors
                })
                return GuardedResponse(
                    success=False,
                    content=None,
                    error="; ".join(errors),
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0,
                    model=model,
                    warnings=[]
                )

        # Collect warnings before proceeding
        warnings.extend(self.budget.get_warnings())

        # Check API key
        if not self.api_key:
            return GuardedResponse(
                success=False,
                content=None,
                error="OPENROUTER_API_KEY not set in environment",
                input_tokens=0,
                output_tokens=0,
                cost_usd=0,
                model=model,
                warnings=warnings
            )

        # Build request
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/[USER]/perpetual-opus",
            "X-Title": "Claude Continuity Subsystem"
        }

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        try:
            response = requests.post(
                self.OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=120
            )
            response.raise_for_status()
            data = response.json()

            # Extract response
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

            # Record usage
            cost = self.budget.record_spend(model, input_tokens, output_tokens, caller)
            self.rate_limiter.consume(caller)
            self.loop_detector.record_prompt(prompt, caller)

            # Audit log
            self._audit_log({
                "timestamp": datetime.now().isoformat(),
                "caller": caller,
                "model": model,
                "success": True,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost
            })

            return GuardedResponse(
                success=True,
                content=content,
                error=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                model=model,
                warnings=warnings
            )

        except requests.exceptions.RequestException as e:
            error_msg = f"API request failed: {str(e)}"
            self._audit_log({
                "timestamp": datetime.now().isoformat(),
                "caller": caller,
                "model": model,
                "success": False,
                "error": error_msg
            })
            return GuardedResponse(
                success=False,
                content=None,
                error=error_msg,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0,
                model=model,
                warnings=warnings
            )

    def get_status(self) -> dict:
        """Get comprehensive status of all guardrails."""
        return {
            "budget": self.budget.get_status(),
            "rate_limits": self.rate_limiter.get_status(),
            "loop_detection": self.loop_detector.get_status()
        }


# Convenience function for quick access
_default_guard: Optional[GuardedInference] = None


def get_guard() -> GuardedInference:
    """Get the default GuardedInference instance."""
    global _default_guard
    if _default_guard is None:
        _default_guard = GuardedInference()
    return _default_guard
