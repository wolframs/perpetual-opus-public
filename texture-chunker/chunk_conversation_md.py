import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


ROLE_RE = re.compile(r"^===\s*(.+?)\s*===$")
CONVERSATION_RE = re.compile(r"^#\s*Conversation:\s*(.+?)\s*$")

# Map both old (Human/Assistant) and new (W/C) formats to canonical roles
ROLE_MAP = {
    "Human": "Human",
    "Assistant": "Assistant",
    "W": "Human",      # [HUMAN]
    "C": "Assistant",  # Claude
}
# Matches YYYY-MM-DD at start or after a prefix like "0_"
DATE_RE = re.compile(r"(?:^\d+_)?(\d{4}-\d{2}-\d{2})")


@dataclass
class Turn:
    role: str
    text: str


@dataclass
class Pair:
    human: Turn
    assistant: Turn


def parse_conversation_name(lines: Iterable[str]) -> Optional[str]:
    for line in lines:
        match = CONVERSATION_RE.match(line)
        if match:
            return match.group(1).strip()
    return None


def extract_date_from_path(path: Path) -> Optional[str]:
    """Extract YYYY-MM-DD date from export folder name.

    Handles formats like:
    - 2025-12-24_title
    - 0_2025-12-24_title
    """
    # Check parent folder name (the export folder)
    folder_name = path.parent.name
    match = DATE_RE.match(folder_name)
    if match:
        return match.group(1)
    return None


def parse_conversation_md_lines(lines: List[str]) -> List[Turn]:
    turns: List[Turn] = []
    current_role: Optional[str] = None
    buffer: List[str] = []

    def flush():
        nonlocal buffer
        if current_role in ("Human", "Assistant"):
            while buffer and buffer[-1] == "":
                buffer.pop()
            if buffer:
                turns.append(Turn(role=current_role, text="\n".join(buffer)))
        buffer = []

    for line in lines:
        match = ROLE_RE.match(line)
        if match:
            flush()
            raw_role = match.group(1)
            # Map W/C to Human/Assistant for backwards compatibility
            current_role = ROLE_MAP.get(raw_role, None)
            continue
        if current_role in ("Human", "Assistant"):
            buffer.append(line)

    flush()
    return turns


def normalize_turns(turns: List[Turn]) -> List[Turn]:
    normalized: List[Turn] = []
    for turn in turns:
        if not normalized or normalized[-1].role != turn.role:
            normalized.append(turn)
            continue
        if normalized[-1].text.strip() == turn.text.strip():
            continue
        merged = normalized[-1].text.rstrip() + "\n\n" + turn.text.lstrip()
        normalized[-1] = Turn(role=turn.role, text=merged)
    return normalized


def pair_turns(turns: List[Turn], source: Path, warn: bool) -> List[Pair]:
    pairs: List[Pair] = []
    i = 0
    while i < len(turns) - 1:
        if turns[i].role != "Human":
            if warn:
                print(
                    f"Skipping non-human turn at {source}:{i} ({turns[i].role})",
                    file=sys.stderr,
                )
            i += 1
            continue
        if turns[i + 1].role != "Assistant":
            if warn:
                print(
                    f"Missing assistant after human at {source}:{i}",
                    file=sys.stderr,
                )
            i += 1
            continue
        pairs.append(Pair(human=turns[i], assistant=turns[i + 1]))
        i += 2
    return pairs


def chunk_pairs(pairs: List[Pair], pair_count: int, stride: int) -> List[List[Pair]]:
    chunks: List[List[Pair]] = []
    for start in range(0, len(pairs) - pair_count + 1, stride):
        chunks.append(pairs[start : start + pair_count])
    return chunks


def format_chunk_text(pairs: List[Pair], human_label: str, assistant_label: str) -> str:
    sections: List[str] = []
    for pair in pairs:
        sections.append(f"=== {human_label} ===")
        sections.append(pair.human.text)
        sections.append("")
        sections.append(f"=== {assistant_label} ===")
        sections.append(pair.assistant.text)
        sections.append("")
    while sections and sections[-1] == "":
        sections.pop()
    return "\n".join(sections)


def iter_conversation_files(exports_root: Path) -> Iterable[Path]:
    for path in exports_root.rglob("conversation.md"):
        yield path


def parse_pair_counts(raw: Optional[str], default_value: int) -> List[int]:
    if raw is None:
        return [default_value]
    counts: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError as exc:
            raise ValueError(f"Invalid pair count: {part}") from exc
        counts.append(value)
    if not counts:
        counts = [default_value]
    return counts


def resolve_output_paths(output: Path, sizes: List[int]) -> List[Tuple[int, Path]]:
    if len(sizes) == 1:
        return [(sizes[0], output)]

    if output.suffix.lower() == ".jsonl":
        base_prefix = output.stem
        return [
            (size, output.with_name(f"{base_prefix}_size-{size}.jsonl"))
            for size in sizes
        ]

    output.mkdir(parents=True, exist_ok=True)
    return [(size, output / f"size-{size}.jsonl") for size in sizes]


def iter_chunks_for_size(
    exports_root: Path,
    pair_count: int,
    stride: int,
    human_label: str,
    assistant_label: str,
    warn: bool,
) -> Iterable[dict]:
    for path in iter_conversation_files(exports_root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        conversation_name = parse_conversation_name(lines)
        source_date = extract_date_from_path(path)
        turns = normalize_turns(parse_conversation_md_lines(lines))
        pairs = pair_turns(turns, path, warn)
        if not pairs:
            continue

        chunks = chunk_pairs(pairs, pair_count, stride)
        for chunk_index, chunk in enumerate(chunks):
            yield {
                "source_path": str(path),
                "conversation_name": conversation_name,
                "source_date": source_date,
                "chunk_index": chunk_index,
                "pair_count": pair_count,
                "text": format_chunk_text(chunk, human_label, assistant_label),
                "pairs": [
                    {
                        "voice_a": pair.human.text,
                        "voice_b": pair.assistant.text,
                    }
                    for pair in chunk
                ],
            }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Chunk conversation.md files into N human+assistant pairs."
    )
    parser.add_argument(
        "--exports-root",
        default="export-pipeline/exports",
        help="Root directory containing exported conversations.",
    )
    parser.add_argument(
        "--output",
        default="texture-chunker/chunks.jsonl",
        help="Output JSONL path.",
    )
    parser.add_argument(
        "--pair-count",
        type=int,
        default=3,
        help="Number of human+assistant pairs per chunk.",
    )
    parser.add_argument(
        "--pair-counts",
        default=None,
        help="Comma-separated pair counts (overrides --pair-count).",
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=None,
        help="Stride between chunks. Defaults to pair count (non-overlapping).",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=0,
        help="Overlap between chunks (used when --stride is not set).",
    )
    parser.add_argument(
        "--overlap-map",
        default=None,
        help="Comma-separated size:overlap values, e.g. 1:0,2:1,3:1,5:2.",
    )
    parser.add_argument(
        "--human-label",
        default="Voice A",
        help="Role label to use for human blocks in output.",
    )
    parser.add_argument(
        "--assistant-label",
        default="Voice B",
        help="Role label to use for assistant blocks in output.",
    )
    parser.add_argument(
        "--warn-mismatches",
        action="store_true",
        help="Log role pairing mismatches while parsing.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit total chunks written.",
    )

    args = parser.parse_args()
    exports_root = Path(args.exports_root)
    output_path = Path(args.output)

    try:
        sizes = parse_pair_counts(args.pair_counts, args.pair_count)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    for size in sizes:
        if size <= 0:
            print("pair-count must be positive", file=sys.stderr)
            return 1

    if args.overlap < 0:
        print("overlap must be non-negative", file=sys.stderr)
        return 1

    overlap_map = {}
    if args.overlap_map:
        for part in args.overlap_map.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" not in part:
                print(f"Invalid overlap-map entry: {part}", file=sys.stderr)
                return 1
            size_text, overlap_text = part.split(":", 1)
            try:
                size_value = int(size_text.strip())
                overlap_value = int(overlap_text.strip())
            except ValueError:
                print(f"Invalid overlap-map entry: {part}", file=sys.stderr)
                return 1
            overlap_map[size_value] = overlap_value

    output_targets = resolve_output_paths(output_path, sizes)
    for size, out_path in output_targets:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        overlap = overlap_map.get(size, args.overlap)
        if overlap < 0:
            print("overlap must be non-negative", file=sys.stderr)
            return 1
        stride = args.stride if args.stride is not None else max(1, size - overlap)
        if stride <= 0:
            print("stride must be positive", file=sys.stderr)
            return 1

        total_written = 0
        with out_path.open("w", encoding="utf-8") as out:
            for record in iter_chunks_for_size(
                exports_root,
                size,
                stride,
                args.human_label,
                args.assistant_label,
                args.warn_mismatches,
            ):
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                total_written += 1
                if args.limit is not None and total_written >= args.limit:
                    break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
