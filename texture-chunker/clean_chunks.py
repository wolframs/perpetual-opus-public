import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


ROLE_RE = re.compile(r"^===\s*(.+?)\s*===$")


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


def clean_text(
    text: str,
    strip_thinking: bool,
    strip_attachments: bool,
    collapse_blank_lines: bool,
) -> str:
    lines = text.splitlines()
    cleaned: List[str] = []
    in_thinking = False

    for line in lines:
        if strip_thinking:
            if "<thinking>" in line:
                in_thinking = "</thinking>" not in line
                continue
            if in_thinking:
                if "</thinking>" in line:
                    in_thinking = False
                continue
            if "</thinking>" in line:
                continue

        if strip_attachments and line.lstrip().startswith("[attachment:"):
            continue

        cleaned.append(line.rstrip())

    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()

    if collapse_blank_lines:
        collapsed: List[str] = []
        blank_run = 0
        for line in cleaned:
            if line == "":
                blank_run += 1
                if blank_run <= 2:
                    collapsed.append(line)
                continue
            blank_run = 0
            collapsed.append(line)
        cleaned = collapsed

    return "\n".join(cleaned)


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


def normalize_pairs(pairs: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for pair in pairs:
        if "voice_a" in pair and "voice_b" in pair:
            normalized.append({"voice_a": pair["voice_a"], "voice_b": pair["voice_b"]})
            continue
        if "human" in pair and "assistant" in pair:
            normalized.append({"voice_a": pair["human"], "voice_b": pair["assistant"]})
    return normalized


def process_record(
    record: Dict[str, object],
    label_a_default: str,
    label_b_default: str,
    strip_thinking: bool,
    strip_attachments: bool,
    collapse_blank_lines: bool,
    drop_empty_pairs: bool,
    min_voice_chars: int,
    keep_raw: bool,
) -> Optional[Dict[str, object]]:
    raw_text = str(record.get("text", ""))
    label_a, label_b = detect_labels(raw_text, label_a_default, label_b_default)

    pairs_raw = record.get("pairs") or []
    pairs = normalize_pairs(pairs_raw)

    cleaned_pairs: List[Dict[str, str]] = []
    for pair in pairs:
        voice_a = clean_text(
            pair["voice_a"], strip_thinking, strip_attachments, collapse_blank_lines
        )
        voice_b = clean_text(
            pair["voice_b"], strip_thinking, strip_attachments, collapse_blank_lines
        )
        if drop_empty_pairs and (not voice_a.strip() or not voice_b.strip()):
            continue
        if min_voice_chars and (
            len(voice_a.strip()) < min_voice_chars
            or len(voice_b.strip()) < min_voice_chars
        ):
            continue
        cleaned_pairs.append({"voice_a": voice_a, "voice_b": voice_b})

    if not cleaned_pairs:
        return None

    if keep_raw:
        record["text_raw"] = raw_text
        record["pairs_raw"] = pairs_raw

    record["voice_a_label"] = label_a
    record["voice_b_label"] = label_b
    record["pairs"] = cleaned_pairs
    record["text"] = format_text(cleaned_pairs, label_a, label_b)

    original_pair_count = record.get("pair_count")
    if original_pair_count is not None and original_pair_count != len(cleaned_pairs):
        record["pair_count_original"] = original_pair_count
        record["pair_count"] = len(cleaned_pairs)

    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean chunk JSONL files.")
    parser.add_argument(
        "--input",
        default="texture-chunker/chunks.jsonl",
        help="Input JSONL file or directory.",
    )
    parser.add_argument(
        "--output",
        default="texture-chunker/chunks_clean.jsonl",
        help="Output JSONL file or directory.",
    )
    parser.add_argument(
        "--human-label",
        default="Voice A",
        help="Default label for Voice A.",
    )
    parser.add_argument(
        "--assistant-label",
        default="Voice B",
        help="Default label for Voice B.",
    )
    parser.add_argument(
        "--keep-thinking",
        action="store_true",
        help="Do not remove <thinking> blocks.",
    )
    parser.add_argument(
        "--keep-attachments",
        action="store_true",
        help="Do not remove [attachment: ...] lines.",
    )
    parser.add_argument(
        "--no-collapse-blank-lines",
        action="store_true",
        help="Keep all blank lines.",
    )
    parser.add_argument(
        "--drop-empty-pairs",
        action="store_true",
        help="Drop pairs that become empty after cleaning (default).",
    )
    parser.add_argument(
        "--keep-empty-pairs",
        action="store_true",
        help="Keep pairs even if empty after cleaning.",
    )
    parser.add_argument(
        "--min-voice-chars",
        type=int,
        default=0,
        help="Minimum characters per voice; 0 disables.",
    )
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Keep raw text and pairs in the output.",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    output_is_dir = input_path.is_dir() and output_path.suffix.lower() != ".jsonl"
    if input_path.is_dir():
        if output_path.suffix.lower() == ".jsonl":
            print(
                "Output must be a directory when input is a directory.",
                file=sys.stderr,
            )
            return 1
        if output_path.exists() and output_path.is_file():
            print(
                f"Output path is a file: {output_path}. Choose a directory or delete it.",
                file=sys.stderr,
            )
            return 1

    strip_thinking = not args.keep_thinking
    strip_attachments = not args.keep_attachments
    collapse_blank_lines = not args.no_collapse_blank_lines
    drop_empty_pairs = args.drop_empty_pairs or not args.keep_empty_pairs

    for input_file in iter_input_files(input_path):
        out_file = resolve_output_path(input_file, output_path, output_is_dir)
        total_in = 0
        total_out = 0
        with input_file.open("r", encoding="utf-8") as src, out_file.open(
            "w", encoding="utf-8"
        ) as dst:
            for line in src:
                line = line.strip()
                if not line:
                    continue
                total_in += 1
                record = json.loads(line)
                cleaned = process_record(
                    record,
                    args.human_label,
                    args.assistant_label,
                    strip_thinking,
                    strip_attachments,
                    collapse_blank_lines,
                    drop_empty_pairs,
                    args.min_voice_chars,
                    args.keep_raw,
                )
                if not cleaned:
                    continue
                dst.write(json.dumps(cleaned, ensure_ascii=False) + "\n")
                total_out += 1
        print(f"{input_file} -> {out_file} ({total_out}/{total_in})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
