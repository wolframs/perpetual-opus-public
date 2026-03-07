"""
Consolidation Daemon Runner

Entry point that orchestrates trigger checking, scanning, and consolidation.
Provides CLI interface for manual runs and is called by post-session hooks.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Load environment variables from .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, assume env vars set externally

# Handle both relative and direct imports
try:
    from .triggers import TriggerChecker
    from .scanner import IntegrationScanner
    from .consolidator import Consolidator
except ImportError:
    from triggers import TriggerChecker
    from scanner import IntegrationScanner
    from consolidator import Consolidator


class ConsolidationRunner:
    """
    Orchestrates the consolidation daemon's two modes.

    Mode 1 (Scan): Quick check for unreferenced notes
    Mode 2 (Consolidation): Full synthesis pass

    By default, respects trigger thresholds. Can be overridden for manual runs.

    Test mode: Uses sandboxed paths for state and output, allowing real API
    calls without affecting production state.
    """

    def __init__(self, repo_root: Optional[Path] = None, test_mode: bool = False):
        """
        Initialize the runner.

        Args:
            repo_root: Path to repository root. Auto-detected if None.
            test_mode: If True, use sandboxed paths for state and output.
                      Allows testing with real API calls without affecting
                      production state.
        """
        self.test_mode = test_mode

        # Determine repo root first
        if repo_root:
            self.repo_root = repo_root
        else:
            # Find repo root by looking for CLAUDE.md
            current = Path(__file__).resolve().parent
            for _ in range(10):
                if (current / "CLAUDE.md").exists():
                    self.repo_root = current
                    break
                current = current.parent
            else:
                self.repo_root = Path(__file__).resolve().parent.parent.parent

        # Set up paths based on mode
        if test_mode:
            self.staging_dir = self.repo_root / "output" / "staging" / "consolidation" / "test"
            self.state_file = self.repo_root / "agent" / "consolidation" / "state_test.json"
        else:
            self.staging_dir = self.repo_root / "output" / "staging" / "consolidation"
            self.state_file = self.repo_root / "agent" / "consolidation" / "state.json"

        # Initialize components with appropriate paths
        self.triggers = TriggerChecker(self.repo_root, state_file=self.state_file if test_mode else None)
        self.scanner = IntegrationScanner(staging_dir=self.staging_dir if test_mode else None)
        self.consolidator = Consolidator(staging_dir=self.staging_dir if test_mode else None)

    def status(self) -> dict:
        """
        Get comprehensive status of triggers and recommendations.

        Returns:
            dict with trigger states and recommendations
        """
        return self.triggers.get_status()

    def run_scan(self, dry_run: bool = True, force: bool = False) -> dict:
        """
        Run Mode 1: Integration Scanner.

        Args:
            dry_run: If True, don't call API or save reports (preview only)
            force: If True, run even if triggers not met

        Returns:
            dict with results
        """
        # Check triggers unless forced
        if not force:
            should_run, reasons = self.triggers.should_run_scan()
            if not should_run:
                return {
                    "success": True,
                    "skipped": True,
                    "reason": "Triggers not met",
                    "dry_run": dry_run
                }

        # Run the scanner
        result = self.scanner.run(dry_run=dry_run)

        # Mark complete if not dry run and successful
        if not dry_run and result.get("success"):
            self.triggers.mark_scan_complete()

        return result

    def run_consolidation(self, dry_run: bool = True, force: bool = False) -> dict:
        """
        Run Mode 2: Full Consolidation.

        Args:
            dry_run: If True, don't call API or save proposals (preview only)
            force: If True, run even if triggers not met

        Returns:
            dict with results
        """
        # Check triggers unless forced
        if not force:
            should_run, reasons = self.triggers.should_run_consolidation()
            if not should_run:
                return {
                    "success": True,
                    "skipped": True,
                    "reason": "Triggers not met",
                    "dry_run": dry_run
                }

        # Run the consolidator
        result = self.consolidator.run(dry_run=dry_run)

        # Mark proposal generated if not dry run and successful
        if not dry_run and result.get("success"):
            proposal_path = str(result.get("proposal_path", ""))
            self.triggers.mark_proposal_generated(
                proposal_path=proposal_path,
                trigger_reasons=reasons if not force else ["forced"],
            )

        return result

    def run_auto(self, dry_run: bool = True) -> dict:
        """
        Run automatically based on triggers.

        Checks what needs to run and runs it. Scan runs if its triggers
        are met; consolidation runs if its triggers are met.

        Args:
            dry_run: If True, preview only

        Returns:
            dict with combined results
        """
        results = {
            "timestamp": datetime.now().isoformat(),
            "dry_run": dry_run,
            "scan": None,
            "consolidation": None
        }

        # Check and maybe run scan
        should_scan, scan_reasons = self.triggers.should_run_scan()
        if should_scan:
            results["scan"] = self.run_scan(dry_run=dry_run, force=True)
            results["scan"]["trigger_reasons"] = scan_reasons
        else:
            results["scan"] = {"skipped": True, "reason": "Triggers not met"}

        # Check and maybe run consolidation
        should_consolidate, consol_reasons = self.triggers.should_run_consolidation()
        if should_consolidate:
            results["consolidation"] = self.run_consolidation(dry_run=dry_run, force=True)
            results["consolidation"]["trigger_reasons"] = consol_reasons
        else:
            results["consolidation"] = {"skipped": True, "reason": "Triggers not met"}

        return results


def print_status(runner: ConsolidationRunner):
    """Print formatted status to console."""
    status = runner.status()

    print("\n=== Consolidation Daemon Status ===\n")

    # Trigger checks
    print("Trigger Checks:")
    for check_name, info in status.get("checks", {}).items():
        symbol = "[X]" if info.get("triggered") else "[ ]"
        value = info.get("value", "?")
        threshold = info.get("threshold", "?")
        print(f"  {symbol} {check_name}: {value} (threshold: {threshold})")

    # State
    state = status.get("state", {})
    print("\nState:")
    print(f"  Last scan:     {state.get('last_scan') or 'Never'}")
    print(f"  Last proposal: {state.get('last_proposal') or 'Never'}")
    print(f"  Last applied:  {state.get('last_applied') or 'Never'}")
    print(f"  Scan count:     {state.get('scan_count', 0)}")
    print(f"  Proposal count: {state.get('proposal_count', 0)}")
    print(f"  Applied count:  {state.get('applied_count', 0)}")
    print(f"  History entries: {state.get('history_entries', 0)}")

    # Recommendations
    recs = status.get("recommendations", {})
    print("\nRecommendations:")
    if recs.get("run_scan"):
        print(f"  -> Run SCAN: {', '.join(recs.get('scan_reasons', []))}")
    else:
        print("  -> Scan: not needed")
    if recs.get("run_consolidation"):
        print(f"  -> Run CONSOLIDATION: {', '.join(recs.get('consolidation_reasons', []))}")
    else:
        print("  -> Consolidation: not needed")

    print()


def print_result(result: dict, mode: str):
    """Print formatted result to console."""
    print(f"\n=== {mode} Result ===\n")

    if result.get("skipped"):
        print(f"Skipped: {result.get('reason', 'Unknown')}")
        return

    if result.get("dry_run"):
        print("[DRY RUN - no changes made]\n")

    if result.get("success"):
        print("Status: SUCCESS")
    else:
        print(f"Status: FAILED - {result.get('error', 'Unknown error')}")

    # Mode-specific details
    if "notes_found" in result:
        print(f"Notes found: {result['notes_found']}")
        print(f"Unreferenced: {result.get('unreferenced_count', 0)}")
    if "context_tokens" in result:
        print(f"Context tokens: {result['context_tokens']}")
    if "cost_estimate" in result:
        print(f"Estimated cost: ${result['cost_estimate']:.4f}")
    if "report_path" in result:
        print(f"Report: {result['report_path']}")
    if "proposal_path" in result:
        print(f"Proposal: {result['proposal_path']}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Consolidation Daemon - Memory maintenance for Claude continuity"
    )

    parser.add_argument(
        "--status", "-s",
        action="store_true",
        help="Show trigger status and recommendations"
    )

    parser.add_argument(
        "--scan",
        action="store_true",
        help="Run Mode 1: Integration Scanner"
    )

    parser.add_argument(
        "--consolidate",
        action="store_true",
        help="Run Mode 2: Full Consolidation"
    )

    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run automatically based on triggers"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview only, don't make API calls or save files (default)"
    )

    parser.add_argument(
        "--run",
        action="store_true",
        help="Actually execute (overrides --dry-run)"
    )

    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Run even if triggers not met"
    )

    parser.add_argument(
        "--test", "-t",
        action="store_true",
        help="Test mode: use sandboxed paths for state and output. "
             "Allows real API calls without affecting production state."
    )

    args = parser.parse_args()

    # Determine dry_run state
    dry_run = not args.run

    # Create runner with test mode if specified
    runner = ConsolidationRunner(test_mode=args.test)

    # Print test mode banner if active
    if args.test:
        print("\n" + "=" * 60)
        print("TEST MODE - Using sandboxed paths:")
        print(f"  State: {runner.state_file}")
        print(f"  Output: {runner.staging_dir}")
        print("  Production state will NOT be modified.")
        print("=" * 60)

    # Default to status if no action specified
    if not any([args.status, args.scan, args.consolidate, args.auto]):
        args.status = True

    if args.status:
        print_status(runner)

    if args.scan:
        result = runner.run_scan(dry_run=dry_run, force=args.force)
        print_result(result, "Scan")

    if args.consolidate:
        result = runner.run_consolidation(dry_run=dry_run, force=args.force)
        print_result(result, "Consolidation")

    if args.auto:
        result = runner.run_auto(dry_run=dry_run)
        print(f"\n=== Auto Run ({'DRY RUN' if dry_run else 'LIVE'}) ===\n")
        if result["scan"]:
            print_result(result["scan"], "Scan")
        if result["consolidation"]:
            print_result(result["consolidation"], "Consolidation")


if __name__ == "__main__":
    main()
