#!/usr/bin/env python3
"""
Migration script: Update speaker labels in perpetual-opus exports

Changes:
  === Human ===     ->  === H ===
  === Assistant === ->  === C ===

This is a one-time migration to make the export format reflect
the specific relationship ([HUMAN]-Claude) rather than generic roles.

Usage:
  python migrate_speaker_labels.py --dry-run    # Preview changes
  python migrate_speaker_labels.py              # Apply changes
  python migrate_speaker_labels.py --file path  # Migrate single file
"""

import argparse
import re
from pathlib import Path


def migrate_content(content: str) -> tuple[str, int, int]:
    """
    Migrate speaker labels in content.

    Returns (new_content, human_count, assistant_count)
    """
    # Only match the exact speaker marker pattern at start of line
    # This avoids changing content that happens to contain these strings
    human_pattern = re.compile(r'^=== Human ===$', re.MULTILINE)
    assistant_pattern = re.compile(r'^=== Assistant ===$', re.MULTILINE)

    # Count occurrences
    human_count = len(human_pattern.findall(content))
    assistant_count = len(assistant_pattern.findall(content))

    # Perform replacements
    new_content = human_pattern.sub('=== H ===', content)
    new_content = assistant_pattern.sub('=== C ===', new_content)

    return new_content, human_count, assistant_count


def migrate_file(filepath: Path, dry_run: bool = False) -> tuple[int, int]:
    """
    Migrate a single file.

    Returns (human_count, assistant_count) of replacements made.
    """
    content = filepath.read_text(encoding='utf-8')
    new_content, human_count, assistant_count = migrate_content(content)

    if human_count == 0 and assistant_count == 0:
        return 0, 0

    if not dry_run:
        filepath.write_text(new_content, encoding='utf-8')

    return human_count, assistant_count


def find_export_files(exports_dir: Path) -> list[Path]:
    """Find all conversation.md files in exports directory."""
    return list(exports_dir.glob('*/conversation.md'))


def main():
    parser = argparse.ArgumentParser(
        description='Migrate speaker labels in perpetual-opus exports'
    )
    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='Preview changes without modifying files'
    )
    parser.add_argument(
        '--file', '-f',
        type=Path,
        help='Migrate a single file instead of all exports'
    )
    parser.add_argument(
        '--exports-dir',
        type=Path,
        default=Path(__file__).parent.parent / 'perpetual-opus' / 'exports',
        help='Path to exports directory'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN - no files will be modified\n")

    # Determine files to process
    if args.file:
        files = [args.file]
        if not args.file.exists():
            print(f"Error: File not found: {args.file}")
            return 1
    else:
        files = find_export_files(args.exports_dir)
        print(f"Found {len(files)} conversation files in {args.exports_dir}\n")

    total_human = 0
    total_assistant = 0
    modified_files = 0

    for filepath in sorted(files):
        human_count, assistant_count = migrate_file(filepath, dry_run=args.dry_run)

        if human_count > 0 or assistant_count > 0:
            modified_files += 1
            total_human += human_count
            total_assistant += assistant_count

            relative = filepath.relative_to(args.exports_dir) if not args.file else filepath
            print(f"  {relative}")
            print(f"    Human -> W: {human_count}")
            print(f"    Assistant -> C: {assistant_count}")

    print(f"\n{'Would modify' if args.dry_run else 'Modified'} {modified_files} files")
    print(f"Total replacements: {total_human} Human->W, {total_assistant} Assistant->C")

    if args.dry_run and modified_files > 0:
        print("\nRun without --dry-run to apply changes")

    return 0


if __name__ == '__main__':
    exit(main())
