#!/usr/bin/env python3
"""
Add saliency scores to existing texture-chunker scored JSONL files.

This script reads the scored chunks, runs the saliency detector on each,
and adds a `salience_score` field alongside the existing `feels_score`.

By default, skips chunks that already have a salience_score. Use --force
to re-score everything (e.g., after heuristic changes).
"""

import argparse
import json
import sys
from pathlib import Path

# Add saliency module to path
sys.path.insert(0, str(Path(__file__).parent))

from saliency import analyze_conversation
from saliency.parser import parse_markdown


def score_chunk_text(text: str) -> float:
    """Run saliency detection on chunk text, return max score."""
    if not text:
        return 0.0

    segments = parse_markdown(text, include_thinking=True)
    results = analyze_conversation(segments)

    if not results:
        return 0.0

    # Use the highest-scoring segment
    return max(r.combined_score for r in results)


def process_file(input_path: Path, output_path: Path, force: bool = False) -> tuple[int, int, int]:
    """Process a single JSONL file, adding salience scores.

    Returns (scored, skipped, total).
    """
    scored = 0
    skipped = 0
    total = 0

    with open(input_path, 'r', encoding='utf-8') as infile:
        lines = infile.readlines()
        total = len(lines)

    output_lines = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue

        record = json.loads(line)

        # Skip if already has salience_score (unless --force)
        if not force and 'salience_score' in record:
            output_lines.append(json.dumps(record, ensure_ascii=False))
            skipped += 1
        else:
            text = record.get('text', '')
            salience = score_chunk_text(text)
            record['salience_score'] = round(salience, 3)
            output_lines.append(json.dumps(record, ensure_ascii=False))
            scored += 1

        if (i + 1) % 100 == 0:
            print(f"  {input_path.name}: {i + 1}/{total}...")

    with open(output_path, 'w', encoding='utf-8') as outfile:
        outfile.write('\n'.join(output_lines) + '\n')

    return scored, skipped, total


def main():
    parser = argparse.ArgumentParser(
        description="Add saliency scores to texture-chunker scored chunks."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-score all chunks, even those with existing salience_score.",
    )
    args = parser.parse_args()

    chunks_dir = Path(__file__).parent.parent / 'texture-chunker' / 'chunks_scored'

    if not chunks_dir.exists():
        print(f"Error: {chunks_dir} not found")
        return 1

    jsonl_files = list(chunks_dir.glob('*.jsonl'))
    if not jsonl_files:
        print(f"Error: No JSONL files found in {chunks_dir}")
        return 1

    print(f"Found {len(jsonl_files)} files to process")
    if args.force:
        print("(--force: re-scoring all chunks)")
    print()

    total_scored = 0
    total_skipped = 0

    for jsonl_path in sorted(jsonl_files):
        print(f"Processing {jsonl_path.name}...")
        # Write back to same file (overwrite)
        scored, skipped, total = process_file(jsonl_path, jsonl_path, force=args.force)
        total_scored += scored
        total_skipped += skipped
        print(f"  Done: {scored} scored, {skipped} skipped (of {total})")
        print()

    print(f"Complete. Scored: {total_scored}, Skipped: {total_skipped}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
