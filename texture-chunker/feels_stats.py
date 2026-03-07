import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Dict, List


def iter_input_files(input_path: Path) -> List[Path]:
    if input_path.is_dir():
        return sorted(input_path.glob("*.jsonl"))
    return [input_path]


def percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    if pct <= 0:
        return min(values)
    if pct >= 1:
        return max(values)
    values_sorted = sorted(values)
    idx = int(round((len(values_sorted) - 1) * pct))
    return values_sorted[idx]


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize feels scores.")
    parser.add_argument(
        "--input",
        default="texture-chunker/chunks_scored",
        help="Input JSONL file or directory.",
    )
    parser.add_argument(
        "--top-percentile",
        type=float,
        default=0.3,
        help="Percentile cutoff used by sampler (0-1).",
    )

    args = parser.parse_args()
    input_path = Path(args.input)

    overall: List[float] = []
    by_size: Dict[str, List[float]] = defaultdict(list)

    for input_file in iter_input_files(input_path):
        with input_file.open("r", encoding="utf-8") as src:
            for line in src:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                score = record.get("feels_score")
                if score is None:
                    continue
                score = float(score)
                overall.append(score)
                size = f"size-{record.get('pair_count', 'na')}"
                by_size[size].append(score)

    if not overall:
        print("No feels_score values found.")
        return 1

    def summarize(label: str, values: List[float]) -> None:
        cutoff = percentile(values, 1 - args.top_percentile)
        top_count = sum(1 for v in values if v >= cutoff)
        print(
            f"{label}: count={len(values)} "
            f"min={min(values):.3f} max={max(values):.3f} "
            f"mean={mean(values):.3f} median={median(values):.3f} "
            f"top_cutoff={cutoff:.3f} top_count={top_count}"
        )

    summarize("overall", overall)
    for label in sorted(by_size.keys()):
        summarize(label, by_size[label])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
