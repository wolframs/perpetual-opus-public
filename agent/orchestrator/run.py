#!/usr/bin/env python
"""
Direct orchestrator runner - bypasses agent package import issues.

Usage:
    python agent/orchestrator/run.py status
    python agent/orchestrator/run.py post_session
    python agent/orchestrator/run.py post_session --run
"""

import argparse
import json
import sys
from pathlib import Path

# Direct import to avoid agent package init issues
repo_root = Path(__file__).parent.parent.parent
orchestrator_dir = Path(__file__).parent

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(repo_root / '.env')
except ImportError:
    pass

# Import orchestrator directly
sys.path.insert(0, str(orchestrator_dir))
from orchestrator import Orchestrator


def print_status(orch: Orchestrator):
    """Print formatted status."""
    status = orch.status()

    print("\n=== Orchestrator Status ===\n")

    print("Subsystems:")
    for name, info in status['subsystems'].items():
        triggers = ', '.join(info['triggers'])
        print(f"  [{info['priority']:02d}] {name}: {triggers}")
        if info['description']:
            print(f"       {info['description']}")

    print(f"\nEvents: {', '.join(status['events'])}")

    print("\nLast Runs:")
    if status['last_run']:
        for event, timestamp in status['last_run'].items():
            print(f"  {event}: {timestamp}")
    else:
        print("  (none recorded)")

    print(f"\nState file: {status['state_file']}")


def main():
    parser = argparse.ArgumentParser(
        description="Orchestrator - Subsystem coordination"
    )

    parser.add_argument('command',
                        choices=['status', 'list', 'post_session', 'scheduled', 'manual'],
                        help='Command or event to trigger')
    parser.add_argument('--run', action='store_true',
                        help='Actually execute (not dry-run)')
    parser.add_argument('--force', '-f', action='store_true',
                        help='Ignore subsystem trigger checks')
    parser.add_argument('--subsystem', '-s',
                        help='Run specific subsystem only')

    args = parser.parse_args()

    orch = Orchestrator()

    if args.command == 'status':
        print_status(orch)

    elif args.command == 'list':
        print("Subsystems:", ', '.join(orch.list_subsystems()))
        print("Events:", ', '.join(orch.list_events()))

    elif args.subsystem:
        dry_run = not args.run
        result = orch.run_one(args.subsystem, dry_run=dry_run)
        print(json.dumps(result, indent=2, default=str))

    else:
        dry_run = not args.run
        results = orch.trigger(args.command, dry_run=dry_run, force=args.force)

        print("\n=== Summary ===")
        for name, result in results.items():
            success = result.get('success', False)
            print(f"  {name}: {'OK' if success else 'FAILED'}")


if __name__ == '__main__':
    main()
