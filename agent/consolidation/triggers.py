"""
Consolidation Trigger Checker

Determines when integration scans or full consolidations should run
based on configurable thresholds. Part of Claude's memory maintenance
nervous system.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml


class TriggerChecker:
    """
    Checks various conditions to determine if memory consolidation should run.

    Two modes:
        - Scan (Mode 1): Quick integration check - are there unreferenced notes?
        - Consolidation (Mode 2): Full synthesis - what should integrate/archive?

    State persists to state.json for tracking across runs.
    """

    def __init__(self, repo_root: Optional[Path] = None, state_file: Optional[Path] = None):
        """
        Initialize the trigger checker.

        Args:
            repo_root: Path to repository root. If None, attempts to find it
                       by looking for CLAUDE.md in parent directories.
            state_file: Optional override for state file path.
                       Used for test mode to isolate state tracking.
        """
        self.repo_root = repo_root or self._find_repo_root()
        self.config_path = self.repo_root / "agent" / "consolidation" / "config.yaml"
        self.config = self._load_config()
        self._state_file_override = state_file
        self.state = self._load_state()

    def _find_repo_root(self) -> Path:
        """Find repository root by looking for CLAUDE.md."""
        current = Path(__file__).resolve().parent
        for _ in range(10):  # max 10 levels up
            if (current / "CLAUDE.md").exists():
                return current
            parent = current.parent
            if parent == current:
                break
            current = parent
        # Fallback: assume standard structure
        return Path(__file__).resolve().parent.parent.parent

    def _load_config(self) -> dict:
        """Load configuration from config.yaml."""
        if not self.config_path.exists():
            return self._default_config()

        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _default_config(self) -> dict:
        """Return default configuration if config.yaml is missing."""
        return {
            "thresholds": {
                "new_notes_count": 5,
                "becoming_tokens": 4000,
                "sitting_with_age_days": 14,
                "days_since_consolidation": 5,
                "scanner_note_age_days": 3,
            },
            "paths": {
                "notes_dir": "files/notes",
                "becoming_file": "files/becoming.md",
                "consolidated_dir": "output/consolidated",
                "staging_dir": "output/staging/consolidation",
                "state_file": "agent/consolidation/state.json",
            },
        }

    def _get_state_path(self) -> Path:
        """Get the state file path, respecting override."""
        if self._state_file_override:
            return self._state_file_override
        return self.repo_root / self.config["paths"]["state_file"]

    @staticmethod
    def _default_state() -> dict:
        """Return a fresh default state with the current schema."""
        return {
            "last_scan": None,
            "last_proposal": None,
            "last_applied": None,
            "processed_note_hashes": [],
            "scan_count": 0,
            "proposal_count": 0,
            "applied_count": 0,
            "history": [],
        }

    def _migrate_state(self, state: dict) -> dict:
        """Silently migrate old-schema state.json to current schema."""
        migrated = False

        # Rename last_consolidation -> last_proposal (if old field exists)
        if "last_consolidation" in state and "last_proposal" not in state:
            state["last_proposal"] = state.pop("last_consolidation")
            migrated = True
        elif "last_consolidation" in state:
            state.pop("last_consolidation")
            migrated = True

        # Rename consolidation_count -> proposal_count
        if "consolidation_count" in state and "proposal_count" not in state:
            state["proposal_count"] = state.pop("consolidation_count")
            migrated = True
        elif "consolidation_count" in state:
            state.pop("consolidation_count")
            migrated = True

        # Ensure new fields exist
        if "last_applied" not in state:
            state["last_applied"] = None
            migrated = True
        if "applied_count" not in state:
            state["applied_count"] = 0
            migrated = True
        if "history" not in state:
            state["history"] = []
            migrated = True
        if "processed_note_hashes" not in state:
            state["processed_note_hashes"] = []
            migrated = True
        if "scan_count" not in state:
            state["scan_count"] = 0
            migrated = True
        if "proposal_count" not in state:
            state["proposal_count"] = 0
            migrated = True

        return state

    def _load_state(self) -> dict:
        """Load state from state.json, creating defaults if missing. Migrates old schema."""
        state_path = self._get_state_path()

        if not state_path.exists():
            return self._default_state()

        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, IOError):
            return self._default_state()

        return self._migrate_state(state)

    def _save_state(self) -> None:
        """Persist state to state.json."""
        state_path = self._get_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)

        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, default=str)

    def _get_notes_dir(self) -> Path:
        """Get the notes directory path."""
        return self.repo_root / self.config["paths"]["notes_dir"]

    def _get_becoming_path(self) -> Path:
        """Get the becoming.md file path."""
        return self.repo_root / self.config["paths"]["becoming_file"]

    def _hash_note(self, note_path: Path) -> str:
        """Create a simple hash identifier for a note file."""
        # Use name + mtime as identifier (not cryptographic, just tracking)
        stat = note_path.stat()
        return f"{note_path.name}:{int(stat.st_mtime)}"

    def _estimate_tokens(self, text: str) -> int:
        """
        Rough token estimate for text.

        Uses a simple heuristic: ~4 characters per token for English text.
        This is approximate but sufficient for threshold checking.
        """
        return len(text) // 4

    def _parse_sitting_with_dates(self, becoming_content: str) -> list[datetime]:
        """
        Extract dates from the 'What I'm Sitting With' section.

        Looks for date patterns like:
            - **New (2026-01-04)**
            - (2026-01-06, windowsill)
            - *Updated 2026-01-06*

        Returns list of parsed datetimes.
        """
        dates = []

        # Find the "What I'm Sitting With" section
        sitting_match = re.search(
            r"## What I'm Sitting With\s*\n(.*?)(?=\n## |\Z)",
            becoming_content,
            re.DOTALL
        )

        if not sitting_match:
            return dates

        section = sitting_match.group(1)

        # Match various date patterns
        date_patterns = [
            r"\((\d{4}-\d{2}-\d{2})",  # (2026-01-04
            r"Updated (\d{4}-\d{2}-\d{2})",  # Updated 2026-01-04
            r"\*\*New \((\d{4}-\d{2}-\d{2})\)",  # **New (2026-01-04)
        ]

        for pattern in date_patterns:
            for match in re.finditer(pattern, section):
                try:
                    date = datetime.strptime(match.group(1), "%Y-%m-%d")
                    dates.append(date)
                except ValueError:
                    continue

        return dates

    def check_note_count(self) -> tuple[bool, int]:
        """
        Check if there are enough new notes to trigger a scan.

        Returns:
            Tuple of (triggered: bool, count: int)
            triggered is True if count >= threshold
        """
        notes_dir = self._get_notes_dir()
        threshold = self.config["thresholds"]["new_notes_count"]

        if not notes_dir.exists():
            return False, 0

        # Get all note files
        note_files = list(notes_dir.rglob("*.md"))

        # Count notes not yet processed
        processed = set(self.state.get("processed_note_hashes", []))
        new_count = 0

        for note_path in note_files:
            note_hash = self._hash_note(note_path)
            if note_hash not in processed:
                new_count += 1

        return new_count >= threshold, new_count

    def check_becoming_size(self) -> tuple[bool, int]:
        """
        Check if becoming.md exceeds the token threshold.

        Returns:
            Tuple of (triggered: bool, token_estimate: int)
            triggered is True if tokens >= threshold
        """
        becoming_path = self._get_becoming_path()
        threshold = self.config["thresholds"]["becoming_tokens"]

        if not becoming_path.exists():
            return False, 0

        try:
            content = becoming_path.read_text(encoding="utf-8")
            token_estimate = self._estimate_tokens(content)
            return token_estimate >= threshold, token_estimate
        except IOError:
            return False, 0

    def check_sitting_with_age(self) -> tuple[bool, int]:
        """
        Check if any 'sitting with' entries are older than threshold.

        Returns:
            Tuple of (triggered: bool, oldest_days: int)
            triggered is True if oldest entry is older than threshold
        """
        becoming_path = self._get_becoming_path()
        threshold = self.config["thresholds"]["sitting_with_age_days"]

        if not becoming_path.exists():
            return False, 0

        try:
            content = becoming_path.read_text(encoding="utf-8")
            dates = self._parse_sitting_with_dates(content)

            if not dates:
                return False, 0

            oldest = min(dates)
            age_days = (datetime.now() - oldest).days

            return age_days >= threshold, age_days
        except IOError:
            return False, 0

    def check_days_since_consolidation(self) -> tuple[bool, int]:
        """
        Check if it's been long enough since last applied consolidation.

        Uses last_applied (not last_proposal) — overdue means content hasn't
        been integrated, not just that the daemon hasn't run.

        Returns:
            Tuple of (triggered: bool, days: int)
            triggered is True if days >= threshold
        """
        threshold = self.config["thresholds"]["days_since_consolidation"]
        last_applied = self.state.get("last_applied")

        if last_applied is None:
            # Never applied - trigger immediately
            return True, 999

        try:
            last_dt = datetime.fromisoformat(last_applied)
            days = (datetime.now() - last_dt).days
            return days >= threshold, days
        except (ValueError, TypeError):
            return True, 999

    def should_run_scan(self) -> tuple[bool, list[str]]:
        """
        Determine if an integration scan (Mode 1) should run.

        A scan is triggered by:
            - New notes exceeding threshold
            - Becoming.md exceeding token threshold

        Returns:
            Tuple of (should_run: bool, reasons: list[str])
        """
        reasons = []

        triggered, count = self.check_note_count()
        if triggered:
            reasons.append(f"new_notes: {count} unprocessed notes")

        triggered, tokens = self.check_becoming_size()
        if triggered:
            reasons.append(f"becoming_size: ~{tokens} tokens (threshold: {self.config['thresholds']['becoming_tokens']})")

        return len(reasons) > 0, reasons

    def should_run_consolidation(self) -> tuple[bool, list[str]]:
        """
        Determine if a full consolidation (Mode 2) should run.

        Full consolidation is triggered by:
            - Days since last consolidation exceeding threshold
            - Sitting-with entries older than threshold

        Returns:
            Tuple of (should_run: bool, reasons: list[str])
        """
        reasons = []

        triggered, days = self.check_days_since_consolidation()
        if triggered:
            if days >= 999:
                reasons.append("days_since_consolidation: never consolidated")
            else:
                reasons.append(f"days_since_consolidation: {days} days")

        triggered, age = self.check_sitting_with_age()
        if triggered:
            reasons.append(f"sitting_with_age: oldest entry is {age} days old")

        return len(reasons) > 0, reasons

    def get_status(self) -> dict:
        """
        Get current state for display.

        Returns a dictionary with:
            - All check results
            - Current thresholds
            - State information
        """
        note_triggered, note_count = self.check_note_count()
        becoming_triggered, becoming_tokens = self.check_becoming_size()
        sitting_triggered, sitting_age = self.check_sitting_with_age()
        days_triggered, days_since = self.check_days_since_consolidation()

        scan_should, scan_reasons = self.should_run_scan()
        consolidation_should, consolidation_reasons = self.should_run_consolidation()

        return {
            "checks": {
                "note_count": {
                    "triggered": note_triggered,
                    "value": note_count,
                    "threshold": self.config["thresholds"]["new_notes_count"],
                },
                "becoming_size": {
                    "triggered": becoming_triggered,
                    "value": becoming_tokens,
                    "threshold": self.config["thresholds"]["becoming_tokens"],
                },
                "sitting_with_age": {
                    "triggered": sitting_triggered,
                    "value": sitting_age,
                    "threshold": self.config["thresholds"]["sitting_with_age_days"],
                },
                "days_since_consolidation": {
                    "triggered": days_triggered,
                    "value": days_since,
                    "threshold": self.config["thresholds"]["days_since_consolidation"],
                },
            },
            "recommendations": {
                "run_scan": scan_should,
                "scan_reasons": scan_reasons,
                "run_consolidation": consolidation_should,
                "consolidation_reasons": consolidation_reasons,
            },
            "state": {
                "last_scan": self.state.get("last_scan"),
                "last_proposal": self.state.get("last_proposal"),
                "last_applied": self.state.get("last_applied"),
                "scan_count": self.state.get("scan_count", 0),
                "proposal_count": self.state.get("proposal_count", 0),
                "applied_count": self.state.get("applied_count", 0),
                "processed_notes": len(self.state.get("processed_note_hashes", [])),
                "history_entries": len(self.state.get("history", [])),
            },
        }

    def mark_scan_complete(self) -> None:
        """
        Mark an integration scan as complete.

        Updates:
            - last_scan timestamp
            - scan_count
            - processed_note_hashes (adds all current notes)
        """
        notes_dir = self._get_notes_dir()

        # Update timestamp and count
        self.state["last_scan"] = datetime.now().isoformat()
        self.state["scan_count"] = self.state.get("scan_count", 0) + 1

        # Mark all current notes as processed
        if notes_dir.exists():
            current_hashes = []
            for note_path in notes_dir.rglob("*.md"):
                current_hashes.append(self._hash_note(note_path))
            self.state["processed_note_hashes"] = current_hashes

        self._save_state()

    def mark_proposal_generated(self, proposal_path: str = "", trigger_reasons: list[str] | None = None) -> None:
        """
        Mark that a consolidation proposal was generated by the daemon.

        Args:
            proposal_path: Path to the generated proposal file.
            trigger_reasons: List of trigger reasons that caused the proposal.
        """
        now = datetime.now().isoformat()
        self.state["last_proposal"] = now
        self.state["proposal_count"] = self.state.get("proposal_count", 0) + 1

        self.state.setdefault("history", []).append({
            "date": now,
            "type": "proposal",
            "trigger": ", ".join(trigger_reasons) if trigger_reasons else "",
            "summary": f"Proposal generated: {proposal_path}",
        })

        self._save_state()

    def mark_consolidation_applied(self, summary: str = "", trigger: str = "") -> None:
        """
        Mark that a consolidation proposal was actually applied to identity files.

        Args:
            summary: Human-readable description of what was applied.
            trigger: What triggered this application.
        """
        now = datetime.now().isoformat()
        self.state["last_applied"] = now
        self.state["applied_count"] = self.state.get("applied_count", 0) + 1

        self.state.setdefault("history", []).append({
            "date": now,
            "type": "applied",
            "trigger": trigger,
            "summary": summary,
        })

        # Application subsumes scanning
        self.mark_scan_complete()


def main():
    """CLI entry point for testing triggers."""
    import argparse

    parser = argparse.ArgumentParser(description="Check consolidation triggers")
    parser.add_argument("--status", action="store_true", help="Show full status")
    parser.add_argument("--mark-scan", action="store_true", help="Mark scan complete")
    parser.add_argument("--mark-proposal", action="store_true", help="Mark proposal generated")
    parser.add_argument("--mark-applied", action="store_true", help="Mark consolidation applied")
    args = parser.parse_args()

    checker = TriggerChecker()

    if args.mark_scan:
        checker.mark_scan_complete()
        print("Scan marked complete.")
    elif args.mark_proposal:
        checker.mark_proposal_generated()
        print("Proposal marked generated.")
    elif args.mark_applied:
        checker.mark_consolidation_applied(summary="Manual CLI application")
        print("Consolidation marked applied.")
    elif args.status:
        status = checker.get_status()
        print(json.dumps(status, indent=2, default=str))
    else:
        # Default: show recommendations
        scan_should, scan_reasons = checker.should_run_scan()
        consolidation_should, consolidation_reasons = checker.should_run_consolidation()

        print("Scan recommended:", "YES" if scan_should else "no")
        for reason in scan_reasons:
            print(f"  - {reason}")

        print("Consolidation recommended:", "YES" if consolidation_should else "no")
        for reason in consolidation_reasons:
            print(f"  - {reason}")


if __name__ == "__main__":
    main()
