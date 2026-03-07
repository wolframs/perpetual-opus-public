"""
Loop Detector for Subsystem Inference Calls

Detects when the same (or very similar) prompt is being sent repeatedly,
which usually indicates a stuck agent or infinite loop.
"""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict


@dataclass
class PromptRecord:
    hash: str
    timestamp: str
    subsystem: str


class LoopDetector:
    def __init__(self, config: dict, state_file: Path):
        self.config = config
        self.state_file = state_file

        loop_config = config.get("loop_detection", {})
        self.threshold = loop_config.get("same_prompt_threshold", 3)
        self.window_seconds = loop_config.get("window_seconds", 300)
        self.hash_method = loop_config.get("hash_method", "sha256_prefix")

        self.records: list[PromptRecord] = []
        self._load_state()

    def _load_state(self):
        """Load prompt records from disk."""
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self.records = [
                    PromptRecord(**r) for r in data.get("records", [])
                ]
                self._prune_old_records()
            except (json.JSONDecodeError, KeyError):
                self.records = []

    def _save_state(self):
        """Persist prompt records to disk."""
        self._prune_old_records()
        data = {
            "records": [asdict(r) for r in self.records],
            "last_updated": datetime.now().isoformat()
        }
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(data, indent=2))

    def _prune_old_records(self):
        """Remove records outside the detection window."""
        cutoff = datetime.now() - timedelta(seconds=self.window_seconds)
        self.records = [
            r for r in self.records
            if datetime.fromisoformat(r.timestamp) > cutoff
        ]

    def _hash_prompt(self, prompt: str) -> str:
        """Generate hash of prompt for comparison."""
        # Normalize whitespace for more robust matching
        normalized = " ".join(prompt.split())
        full_hash = hashlib.sha256(normalized.encode()).hexdigest()

        if self.hash_method == "sha256_prefix":
            return full_hash[:16]
        return full_hash

    def check_loop(self, prompt: str, subsystem: str) -> tuple[bool, Optional[str]]:
        """
        Check if this prompt appears to be part of a loop.

        Returns:
            (allowed, reason) - allowed is True if call can proceed
        """
        self._prune_old_records()
        prompt_hash = self._hash_prompt(prompt)

        # Count occurrences of this hash in the window
        count = sum(1 for r in self.records if r.hash == prompt_hash)

        if count >= self.threshold:
            return False, f"Loop detected: same prompt hash appeared {count}x in {self.window_seconds}s window"

        return True, None

    def record_prompt(self, prompt: str, subsystem: str):
        """Record a prompt for loop detection."""
        prompt_hash = self._hash_prompt(prompt)
        record = PromptRecord(
            hash=prompt_hash,
            timestamp=datetime.now().isoformat(),
            subsystem=subsystem
        )
        self.records.append(record)
        self._save_state()

    def reset(self, subsystem: Optional[str] = None):
        """
        Reset loop detection state.

        Args:
            subsystem: If provided, only reset records for that subsystem.
                      If None, reset all records.
        """
        if subsystem:
            self.records = [r for r in self.records if r.subsystem != subsystem]
        else:
            self.records = []
        self._save_state()

    def get_status(self) -> dict:
        """Get loop detection status for display."""
        self._prune_old_records()

        # Count by hash
        hash_counts: dict[str, int] = {}
        for r in self.records:
            hash_counts[r.hash] = hash_counts.get(r.hash, 0) + 1

        # Find any hashes approaching threshold
        concerning = {h: c for h, c in hash_counts.items() if c >= self.threshold - 1}

        return {
            "window_seconds": self.window_seconds,
            "threshold": self.threshold,
            "active_records": len(self.records),
            "unique_hashes": len(hash_counts),
            "concerning_patterns": concerning
        }
