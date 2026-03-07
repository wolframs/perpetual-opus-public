"""
Rate Limiter for Subsystem Inference Calls

Token bucket implementation with per-subsystem limits.
Allows burst capacity after idle periods.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict, field


@dataclass
class Bucket:
    tokens: float
    last_update: str
    max_tokens: float
    refill_rate: float  # tokens per second


class RateLimiter:
    def __init__(self, config: dict, state_file: Path):
        self.config = config
        self.state_file = state_file
        self.rate_limits = config.get("rate_limits", {})
        self.buckets: dict[str, Bucket] = {}
        self._load_state()

    def _load_state(self):
        """Load bucket state from disk."""
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                for name, bucket_data in data.get("buckets", {}).items():
                    self.buckets[name] = Bucket(**bucket_data)
            except (json.JSONDecodeError, KeyError):
                self.buckets = {}

    def _save_state(self):
        """Persist bucket state to disk."""
        data = {
            "buckets": {name: asdict(b) for name, b in self.buckets.items()},
            "last_updated": datetime.now().isoformat()
        }
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(data, indent=2))

    def _get_or_create_bucket(self, subsystem: str) -> Bucket:
        """Get existing bucket or create new one for subsystem."""
        if subsystem in self.buckets:
            return self.buckets[subsystem]

        # Look up config for this subsystem
        limits = self.rate_limits.get(subsystem, self.rate_limits.get("general", {}))

        # Determine rate based on config (per_minute or per_hour)
        if "per_minute" in limits:
            max_tokens = limits["per_minute"]
            refill_rate = max_tokens / 60.0  # tokens per second
        elif "per_hour" in limits:
            max_tokens = limits["per_hour"]
            refill_rate = max_tokens / 3600.0  # tokens per second
        else:
            # Default: 10 per minute
            max_tokens = 10
            refill_rate = 10 / 60.0

        # Add burst allowance to max
        burst = limits.get("burst_allowance", 0)
        max_tokens += burst

        bucket = Bucket(
            tokens=max_tokens,  # Start full
            last_update=datetime.now().isoformat(),
            max_tokens=max_tokens,
            refill_rate=refill_rate
        )
        self.buckets[subsystem] = bucket
        return bucket

    def _refill_bucket(self, bucket: Bucket) -> Bucket:
        """Refill bucket based on elapsed time."""
        now = datetime.now()
        last = datetime.fromisoformat(bucket.last_update)
        elapsed = (now - last).total_seconds()

        # Add tokens based on elapsed time
        new_tokens = min(
            bucket.max_tokens,
            bucket.tokens + (elapsed * bucket.refill_rate)
        )

        bucket.tokens = new_tokens
        bucket.last_update = now.isoformat()
        return bucket

    def check_rate(self, subsystem: str, tokens_needed: int = 1) -> tuple[bool, Optional[str]]:
        """
        Check if a call is allowed under rate limits.

        Args:
            subsystem: Name of the calling subsystem
            tokens_needed: Number of tokens to consume (usually 1 per call)

        Returns:
            (allowed, reason) - allowed is True if call can proceed
        """
        bucket = self._get_or_create_bucket(subsystem)
        bucket = self._refill_bucket(bucket)

        if bucket.tokens >= tokens_needed:
            return True, None
        else:
            # Calculate wait time
            tokens_missing = tokens_needed - bucket.tokens
            wait_seconds = tokens_missing / bucket.refill_rate
            return False, f"Rate limit for {subsystem}: wait {wait_seconds:.1f}s"

    def consume(self, subsystem: str, tokens: int = 1):
        """Consume tokens after a successful call."""
        bucket = self._get_or_create_bucket(subsystem)
        bucket = self._refill_bucket(bucket)
        bucket.tokens = max(0, bucket.tokens - tokens)
        self._save_state()

    def get_status(self, subsystem: Optional[str] = None) -> dict:
        """Get rate limit status for display."""
        if subsystem:
            bucket = self._get_or_create_bucket(subsystem)
            bucket = self._refill_bucket(bucket)
            return {
                "subsystem": subsystem,
                "tokens_available": bucket.tokens,
                "max_tokens": bucket.max_tokens,
                "refill_rate": bucket.refill_rate,
                "percent_available": (bucket.tokens / bucket.max_tokens) * 100
            }
        else:
            # Return status for all known subsystems
            result = {}
            for name in self.buckets:
                result[name] = self.get_status(name)
            return result
