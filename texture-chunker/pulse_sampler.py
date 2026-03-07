import argparse
import json
import random
import sys
from pathlib import Path
from typing import List


DEFAULT_HEADER = (
    "Stylistic residues. Not active topics. Not to be continued."
)


def load_shards(path: Path) -> List[str]:
    shards: List[str] = []
    with path.open("r", encoding="utf-8") as src:
        for line in src:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            text = record.get("shard_text")
            if text:
                shards.append(text)
    return shards


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample shard text for a pulse.")
    parser.add_argument(
        "--input",
        default="texture-chunker/style_shards.jsonl",
        help="Input shard JSONL file.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of shards to sample.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed.",
    )
    parser.add_argument(
        "--allow-reuse",
        action="store_true",
        help="Allow sampling with replacement.",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Do not include the header.",
    )
    parser.add_argument(
        "--header",
        default=None,
        help="Custom header text.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write output to a file instead of stdout.",
    )

    args = parser.parse_args()

    shards = load_shards(Path(args.input))
    if not shards:
        print("No shards found.", file=sys.stderr)
        return 1

    rng = random.Random(args.seed)
    if args.allow_reuse:
        picks = [rng.choice(shards) for _ in range(args.count)]
    else:
        if args.count > len(shards):
            print("Count exceeds shard pool. Use --allow-reuse.", file=sys.stderr)
            return 1
        picks = rng.sample(shards, args.count)

    header = args.header if args.header is not None else DEFAULT_HEADER
    output_lines: List[str] = []
    if not args.no_header:
        output_lines.append(header)
        output_lines.append("")

    for pick in picks:
        output_lines.append("- " + pick)
        output_lines.append("")

    if output_lines and output_lines[-1] == "":
        output_lines.pop()

    output_text = "\n".join(output_lines)
    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8")
    else:
        print(output_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
