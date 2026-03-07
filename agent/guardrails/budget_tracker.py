"""
Budget Tracker for Subsystem Inference Calls

Tracks spending against daily/hourly limits.
Persists state to disk for continuity across sessions.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict


@dataclass
class SpendRecord:
    timestamp: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    caller: str  # Which subsystem made the call


class BudgetTracker:
    def __init__(self, config: dict, state_file: Path):
        self.config = config
        self.state_file = state_file
        self.pricing = config.get("model_pricing", {})
        self.daily_max = config["budget"]["daily_max_usd"]
        self.hourly_max = config["budget"]["hourly_max_usd"]
        self.warning_threshold = config["budget"].get("warning_threshold_percent", 75) / 100

        self.records: list[SpendRecord] = []
        self._load_state()

    def _load_state(self):
        """Load spending records from disk."""
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self.records = [
                    SpendRecord(**r) for r in data.get("records", [])
                ]
                # Prune old records (older than 25 hours - keeps full day + buffer)
                cutoff = datetime.now() - timedelta(hours=25)
                self.records = [
                    r for r in self.records
                    if datetime.fromisoformat(r.timestamp) > cutoff
                ]
            except (json.JSONDecodeError, KeyError):
                self.records = []

    def _save_state(self):
        """Persist spending records to disk."""
        data = {
            "records": [asdict(r) for r in self.records],
            "last_updated": datetime.now().isoformat()
        }
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(data, indent=2))

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost for a call based on model pricing."""
        pricing = self.pricing.get(model, self.pricing.get("default", {}))
        input_cost = (input_tokens / 1_000_000) * pricing.get("input", 1.0)
        output_cost = (output_tokens / 1_000_000) * pricing.get("output", 2.0)
        return input_cost + output_cost

    def get_hourly_spend(self) -> float:
        """Get total spend in the last hour."""
        cutoff = datetime.now() - timedelta(hours=1)
        return sum(
            r.cost_usd for r in self.records
            if datetime.fromisoformat(r.timestamp) > cutoff
        )

    def get_daily_spend(self) -> float:
        """Get total spend in the last 24 hours."""
        cutoff = datetime.now() - timedelta(hours=24)
        return sum(
            r.cost_usd for r in self.records
            if datetime.fromisoformat(r.timestamp) > cutoff
        )

    def check_budget(self, estimated_cost: float) -> tuple[bool, Optional[str]]:
        """
        Check if a call with estimated cost would exceed budget.

        Returns:
            (allowed, reason) - allowed is True if call can proceed
        """
        hourly = self.get_hourly_spend()
        daily = self.get_daily_spend()

        if hourly + estimated_cost > self.hourly_max:
            return False, f"Hourly budget exceeded: ${hourly:.4f} + ${estimated_cost:.4f} > ${self.hourly_max:.2f}"

        if daily + estimated_cost > self.daily_max:
            return False, f"Daily budget exceeded: ${daily:.4f} + ${estimated_cost:.4f} > ${self.daily_max:.2f}"

        return True, None

    def get_warnings(self) -> list[str]:
        """Get any budget warnings (approaching limits)."""
        warnings = []
        hourly = self.get_hourly_spend()
        daily = self.get_daily_spend()

        if hourly > self.hourly_max * self.warning_threshold:
            pct = (hourly / self.hourly_max) * 100
            warnings.append(f"Hourly budget at {pct:.0f}%: ${hourly:.4f} of ${self.hourly_max:.2f}")

        if daily > self.daily_max * self.warning_threshold:
            pct = (daily / self.daily_max) * 100
            warnings.append(f"Daily budget at {pct:.0f}%: ${daily:.4f} of ${self.daily_max:.2f}")

        return warnings

    def record_spend(self, model: str, input_tokens: int, output_tokens: int, caller: str):
        """Record a completed API call."""
        cost = self.calculate_cost(model, input_tokens, output_tokens)
        record = SpendRecord(
            timestamp=datetime.now().isoformat(),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            caller=caller
        )
        self.records.append(record)
        self._save_state()
        return cost

    def get_status(self) -> dict:
        """Get current budget status for display."""
        hourly = self.get_hourly_spend()
        daily = self.get_daily_spend()
        return {
            "hourly_spend": hourly,
            "hourly_limit": self.hourly_max,
            "hourly_remaining": self.hourly_max - hourly,
            "hourly_percent": (hourly / self.hourly_max) * 100 if self.hourly_max > 0 else 0,
            "daily_spend": daily,
            "daily_limit": self.daily_max,
            "daily_remaining": self.daily_max - daily,
            "daily_percent": (daily / self.daily_max) * 100 if self.daily_max > 0 else 0,
            "warnings": self.get_warnings()
        }
