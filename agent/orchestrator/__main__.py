"""
Orchestrator CLI

Usage:
    python -m agent.orchestrator post_session
    python -m agent.orchestrator post_session --run
    python -m agent.orchestrator status
    python -m agent.orchestrator run scanner
    python -m agent.orchestrator list
"""

import argparse
import json
import sys

from .orchestrator import Orchestrator


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
        description="Orchestrator - Subsystem coordination for Claude continuity"
    )

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Event trigger commands
    for event in ['post_session', 'pre_turn', 'scheduled', 'manual']:
        event_parser = subparsers.add_parser(event, help=f'Trigger {event} event')
        event_parser.add_argument('--run', action='store_true',
                                  help='Actually execute (not dry-run)')
        event_parser.add_argument('--force', '-f', action='store_true',
                                  help='Ignore subsystem trigger checks')

    # Status command
    subparsers.add_parser('status', help='Show orchestrator status')

    # List command
    subparsers.add_parser('list', help='List subsystems and events')

    # Run specific subsystem
    run_parser = subparsers.add_parser('run', help='Run specific subsystem')
    run_parser.add_argument('subsystem', help='Subsystem name')
    run_parser.add_argument('--run', action='store_true',
                            help='Actually execute (not dry-run)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    orch = Orchestrator()

    if args.command == 'status':
        print_status(orch)

    elif args.command == 'list':
        print("Subsystems:", ', '.join(orch.list_subsystems()))
        print("Events:", ', '.join(orch.list_events()))

    elif args.command == 'run':
        dry_run = not getattr(args, 'run', False)
        result = orch.run_one(args.subsystem, dry_run=dry_run)
        print(json.dumps(result, indent=2, default=str))

    elif args.command in ['post_session', 'pre_turn', 'scheduled', 'manual']:
        dry_run = not getattr(args, 'run', False)
        force = getattr(args, 'force', False)
        results = orch.trigger(args.command, dry_run=dry_run, force=force)

        print("\n=== Results ===")
        for name, result in results.items():
            success = result.get('success', False)
            print(f"  {name}: {'OK' if success else 'FAILED'}")


if __name__ == '__main__':
    main()
