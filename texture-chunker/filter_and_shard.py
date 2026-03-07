import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


ROLE_RE = re.compile(r"^===\s*(.+?)\s*===$")


DEFAULT_KEEP = {
    "mid-thought continuation",
    "meta-commentary",
    "refusal / constraint",
    "topic transition",
}

DEFAULT_DROP = {
    "resolution / closure",
    "question / hook",
    "affectively loaded / emotional",
    "irrelevant filler",
}


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


def parse_tag_list(raw: Optional[str]) -> Optional[set]:
    if not raw:
        return None
    return {tag.strip() for tag in raw.split(",") if tag.strip()}


def detect_labels(text: str, default_a: str, default_b: str) -> Tuple[str, str]:
    labels: List[str] = []
    for line in text.splitlines():
        match = ROLE_RE.match(line)
        if match:
            labels.append(match.group(1).strip())
            if len(labels) >= 2:
                break
    if len(labels) >= 2:
        return labels[0], labels[1]
    return default_a, default_b


def clip_sentences(text: str, max_sentences: Optional[int]) -> str:
    if not max_sentences:
        return text.strip()
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentences[:max_sentences]).strip()


def mask_proper_nouns(text: str) -> str:
    masked_lines: List[str] = []
    for line in text.splitlines():
        if ROLE_RE.match(line):
            masked_lines.append(line)
            continue
        masked_lines.append(re.sub(r"\b[A-Z][a-z]+\b", "[x]", line))
    return "\n".join(masked_lines)


def select_pairs(
    pairs: List[Dict[str, str]],
    max_pairs: Optional[int],
    selection: str,
    rng: random.Random,
) -> List[Dict[str, str]]:
    if not max_pairs or max_pairs >= len(pairs):
        return pairs
    if selection == "first":
        return pairs[:max_pairs]
    if selection == "last":
        return pairs[-max_pairs:]
    if selection == "random":
        start = rng.randrange(0, len(pairs) - max_pairs + 1)
        return pairs[start : start + max_pairs]
    return pairs[:max_pairs]


def format_text(pairs: List[Dict[str, str]], label_a: str, label_b: str) -> str:
    sections: List[str] = []
    for pair in pairs:
        sections.append(f"=== {label_a} ===")
        sections.append(pair["voice_a"])
        sections.append("")
        sections.append(f"=== {label_b} ===")
        sections.append(pair["voice_b"])
        sections.append("")
    while sections and sections[-1] == "":
        sections.pop()
    return "\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description="Filter tagged chunks into shards.")
    parser.add_argument(
        "--input",
        default="texture-chunker/chunks_tagged.jsonl",
        help="Input JSONL file or directory.",
    )
    parser.add_argument(
        "--output",
        default="texture-chunker/style_shards.jsonl",
        help="Output JSONL file or directory.",
    )
    parser.add_argument(
        "--keep-tags",
        default=None,
        help="Comma-separated tags to keep (default uses a built-in set).",
    )
    parser.add_argument(
        "--drop-tags",
        default=None,
        help="Comma-separated tags to drop (default uses a built-in set).",
    )
    parser.add_argument(
        "--max-sentences",
        type=int,
        default=2,
        help="Max sentences per voice in a shard. Use 0 for no clipping.",
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=None,
        help="Max pairs per shard. Default keeps all.",
    )
    parser.add_argument(
        "--pair-selection",
        choices=("first", "last", "random"),
        default="first",
        help="How to pick pairs when max-pairs is set.",
    )
    parser.add_argument(
        "--mask-proper-nouns",
        action="store_true",
        help="Mask capitalized words to reduce topic gravity.",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=40,
        help="Minimum shard length.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for pair selection.",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    output_is_dir = input_path.is_dir() and output_path.suffix.lower() != ".jsonl"
    if input_path.is_dir():
        if output_path.suffix.lower() == ".jsonl":
            print(
                "Output must be a directory when input is a directory.", file=sys.stderr
            )
            return 1
        if output_path.exists() and output_path.is_file():
            print(
                f"Output path is a file: {output_path}. Choose a directory or delete it.",
                file=sys.stderr,
            )
            return 1

    keep_tags = parse_tag_list(args.keep_tags) or DEFAULT_KEEP
    drop_tags = parse_tag_list(args.drop_tags) or DEFAULT_DROP

    rng = random.Random(args.seed)

    for input_file in iter_input_files(input_path):
        out_file = resolve_output_path(input_file, output_path, output_is_dir)
        kept = 0
        total = 0
        with input_file.open("r", encoding="utf-8") as src, out_file.open(
            "w", encoding="utf-8"
        ) as dst:
            for line in src:
                line = line.strip()
                if not line:
                    continue
                total += 1
                record = json.loads(line)
                tags = set(record.get("tags") or [])
                if drop_tags and tags.intersection(drop_tags):
                    continue
                if keep_tags and not tags.intersection(keep_tags):
                    continue

                pairs = record.get("pairs") or []
                if not pairs:
                    continue

                fallback_a, fallback_b = detect_labels(
                    record.get("text", ""), "Voice A", "Voice B"
                )
                label_a = record.get("voice_a_label") or fallback_a
                label_b = record.get("voice_b_label") or fallback_b

                selected_pairs = select_pairs(
                    pairs, args.max_pairs, args.pair_selection, rng
                )
                clipped_pairs = []
                for pair in selected_pairs:
                    voice_a = clip_sentences(pair["voice_a"], args.max_sentences)
                    voice_b = clip_sentences(pair["voice_b"], args.max_sentences)
                    clipped_pairs.append({"voice_a": voice_a, "voice_b": voice_b})

                shard_text = format_text(clipped_pairs, label_a, label_b)
                if args.mask_proper_nouns:
                    shard_text = mask_proper_nouns(shard_text)

                if len(shard_text) < args.min_chars:
                    continue

                shard = {
                    "source_path": record.get("source_path"),
                    "conversation_name": record.get("conversation_name"),
                    "source_date": record.get("source_date"),
                    "chunk_index": record.get("chunk_index"),
                    "pair_count": record.get("pair_count"),
                    "tags": list(tags),
                    "shard_text": shard_text,
                    "pairs": clipped_pairs,
                }
                dst.write(json.dumps(shard, ensure_ascii=False) + "\n")
                kept += 1

        print(f"{input_file} -> {out_file} ({kept}/{total})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
