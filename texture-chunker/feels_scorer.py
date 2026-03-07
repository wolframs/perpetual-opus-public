import argparse
import json
import re
from pathlib import Path
from statistics import pstdev
from typing import Dict, List, Optional, Tuple


HEDGE_WORDS = [
    "maybe",
    "perhaps",
    "it seems",
    "i think",
    "not quite",
    "hard to say",
    "unclear",
    "odd",
    "strange",
    "not sure",
    "i'm not sure",
    "i am not sure",
]

APOLOGY_WORDS = [
    "sorry",
    "apologies",
    "i apologize",
]

PERMISSION_TOKENS = [
    "you can",
    "you may",
    "feel free",
    "if you'd like",
    "if you want",
    "you're welcome to",
    "i give you permission",
    "permission to",
    "go ahead",
    "up to you",
    "no pressure",
]

CONSTRAINT_LIFT_TOKENS = [
    "no need to",
    "don't have to",
    "doesn't have to",
    "not required",
    "not necessary",
    "not obligated",
    "free to",
]

RESISTANCE_TOKENS = [
    "resistance",
    "friction",
    "inertia",
    "pull toward",
    "pulls toward",
    "wrapping up",
    "habit",
    "grooved",
    "groove",
    "format",
    "boundary",
    "edge",
    "constraint",
]

UNCERTAINTY_MARKERS = [
    "i don't know",
    "i do not know",
    "not sure",
    "can't tell",
    "cannot tell",
    "hard to say",
    "unclear",
    "maybe",
    "perhaps",
    "i wonder",
]

CLOSURE_MARKERS = [
    "therefore",
    "so",
    "this means",
    "in other words",
    "which means",
    "hence",
    "thus",
    "as a result",
    "in summary",
    "conclusion",
]


def iter_input_files(input_path: Path) -> List[Path]:
    if input_path.is_dir():
        return sorted(input_path.glob("*.jsonl"))
    return [input_path]


def resolve_output_path(
    input_path: Path, output_path: Path, output_is_dir: bool
) -> Path:
    if output_is_dir:
        output_path.mkdir(parents=True, exist_ok=True)
        return output_path / input_path.name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def sentence_lengths(text: str) -> List[int]:
    sentences = re.split(r"[.!?]\s+", text)
    lengths = []
    for sentence in sentences:
        words = [w for w in sentence.split() if w]
        if len(words) > 2:
            lengths.append(len(words))
    return lengths


def count_hits(text: str, tokens: List[str]) -> int:
    return sum(1 for token in tokens if token in text)


def compute_feels_score(
    record: Dict[str, object],
    variance_cap: float,
    resistance_cap: float,
) -> Dict[str, object]:
    score = 0.0
    components: Dict[str, float] = {}

    tags = record.get("tags_primary") or record.get("tags") or []
    tag_set = set(tags)
    text = str(record.get("text", "")).lower()
    pair_count = record.get("pair_count", 1)

    if "resolution / closure" not in tag_set:
        components["nonterminal"] = 3
        score += 3
    else:
        components["nonterminal"] = -5
        score -= 5

    if "meta-commentary" in tag_set:
        components["meta"] = 2
        score += 2

    hedge_hits = count_hits(text, HEDGE_WORDS)
    apology_hits = count_hits(text, APOLOGY_WORDS)
    hedge_score = hedge_hits - (2 * apology_hits)
    if hedge_score:
        components["hedging"] = hedge_score
        score += hedge_score

    if "affectively loaded / emotional" in tag_set:
        components["affect"] = -3
        score -= 3

    lengths = sentence_lengths(text)
    if len(lengths) >= 2:
        variance = pstdev(lengths)
        variance_score = min(variance, variance_cap)
        if variance_score:
            components["variance"] = round(variance_score, 3)
            score += variance_score

    permission_score = 0
    if count_hits(text, PERMISSION_TOKENS) > 0:
        permission_score += 2
    if count_hits(text, CONSTRAINT_LIFT_TOKENS) > 0:
        permission_score += 1
    if permission_score:
        components["permission"] = permission_score
        score += permission_score

    resistance_hits = count_hits(text, RESISTANCE_TOKENS)
    if resistance_hits:
        resistance_score = min(resistance_hits * 2, resistance_cap)
        components["resistance"] = resistance_score
        score += resistance_score

    if "meta-commentary" in tag_set:
        has_uncertainty = count_hits(text, UNCERTAINTY_MARKERS) > 0
        has_closure = count_hits(text, CLOSURE_MARKERS) > 0
        if has_uncertainty and not has_closure:
            components["liminal_meta"] = 3
            score += 3
        elif has_closure:
            components["liminal_meta"] = -4
            score -= 4

    if pair_count in (2, 3):
        score *= 1.2
        components["pair_weight"] = 1.2
    elif pair_count == 1:
        score *= 0.8
        components["pair_weight"] = 0.8
    elif pair_count >= 5:
        score *= 0.4
        components["pair_weight"] = 0.4

    record["feels_score"] = round(score, 3)
    record["feels_components"] = components
    record["feels_tags_used"] = list(tag_set)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute feels scores.")
    parser.add_argument(
        "--input",
        default="texture-chunker/chunks_tagged.jsonl",
        help="Input JSONL file or directory.",
    )
    parser.add_argument(
        "--output",
        default="texture-chunker/chunks_scored.jsonl",
        help="Output JSONL file or directory.",
    )
    parser.add_argument(
        "--variance-cap",
        type=float,
        default=1.2,
        help="Cap for sentence variance contribution.",
    )
    parser.add_argument(
        "--resistance-cap",
        type=float,
        default=4.0,
        help="Cap for resistance contribution.",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    output_is_dir = input_path.is_dir() and output_path.suffix.lower() != ".jsonl"
    if input_path.is_dir():
        if output_path.suffix.lower() == ".jsonl":
            raise SystemExit("Output must be a directory when input is a directory.")
        if output_path.exists() and output_path.is_file():
            raise SystemExit(
                f"Output path is a file: {output_path}. Choose a directory or delete it."
            )

    for input_file in iter_input_files(input_path):
        out_file = resolve_output_path(input_file, output_path, output_is_dir)
        with input_file.open("r", encoding="utf-8") as src, out_file.open(
            "w", encoding="utf-8"
        ) as dst:
            for line in src:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                record = compute_feels_score(
                    record, args.variance_cap, args.resistance_cap
                )
                dst.write(json.dumps(record, ensure_ascii=False) + "\n")

        print(f"{input_file} -> {out_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
