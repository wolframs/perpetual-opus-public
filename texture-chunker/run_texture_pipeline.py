import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


ROLE_RE = re.compile(r"^===\s*(.+?)\s*===$")
CONVERSATION_RE = re.compile(r"^#\s*Conversation:\s*(.+?)\s*$")
# Matches YYYY-MM-DD at start or after a prefix like "0_"
DATE_RE = re.compile(r"(?:^\d+_)?(\d{4}-\d{2}-\d{2})")
VALID_ROLES = ("Human", "Assistant")
# Alias short role labels to canonical names
ROLE_ALIAS = {
    "W": "Human",
    "C": "Assistant",
    "Human": "Human",
    "Assistant": "Assistant",
}


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
        if current_role in VALID_ROLES:
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
            # Map aliased roles (W/C) to canonical names (Human/Assistant)
            role = ROLE_ALIAS.get(raw_role, raw_role)
            current_role = role if role in VALID_ROLES else None
            continue
        if current_role in VALID_ROLES:
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


def pair_turns(turns: List[Turn]) -> List[Pair]:
    pairs: List[Pair] = []
    i = 0
    while i < len(turns) - 1:
        if turns[i].role != "Human":
            i += 1
            continue
        if turns[i + 1].role != "Assistant":
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


def load_state(state_path: Path) -> Dict[str, Dict[str, object]]:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"State file is invalid JSON: {state_path}") from exc


def save_state(state_path: Path, state: Dict[str, Dict[str, object]]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def file_signature(path: Path) -> Dict[str, object]:
    stat = path.stat()
    return {"mtime": stat.st_mtime, "size": stat.st_size}


def record_chunk(chunks_dir: Path, size: int, record: Dict[str, object]) -> None:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    out_file = chunks_dir / f"size-{size}.jsonl"
    with out_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_dir(delta_dir: Path, master_dir: Path) -> None:
    master_dir.mkdir(parents=True, exist_ok=True)
    for path in delta_dir.glob("*.jsonl"):
        out_file = master_dir / path.name
        with path.open("r", encoding="utf-8") as src, out_file.open(
            "a", encoding="utf-8"
        ) as dst:
            for line in src:
                dst.write(line)


def run_step(cmd: List[str], cwd: Path) -> None:
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n{result.stdout}\n{result.stderr}"
        )


def validate_pair_counts(pair_counts: List[int]) -> None:
    if not pair_counts:
        raise ValueError("pair-counts cannot be empty.")
    for value in pair_counts:
        if value <= 0:
            raise ValueError("pair-counts must be positive integers.")


def parse_overlap_map(raw: str) -> Dict[int, int]:
    overlap_map: Dict[int, int] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ValueError(f"Invalid overlap-map entry: {entry}")
        size_text, overlap_text = entry.split(":", 1)
        size_value = int(size_text.strip())
        overlap_value = int(overlap_text.strip())
        overlap_map[size_value] = overlap_value
    return overlap_map


def validate_overlaps(pair_counts: List[int], overlap_map: Dict[int, int]) -> None:
    for size in pair_counts:
        overlap = overlap_map.get(size, 0)
        if overlap < 0:
            raise ValueError(f"overlap for size {size} must be non-negative.")
        if overlap >= size:
            raise ValueError(
                f"overlap for size {size} must be < size (got {overlap})."
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run texture pipeline incrementally.")
    parser.add_argument(
        "--exports-root",
        default="export-pipeline/exports",
        help="Root directory containing exported conversations.",
    )
    parser.add_argument(
        "--state-file",
        default="texture-chunker/pipeline_state.json",
        help="State file tracking processed conversations.",
    )
    parser.add_argument(
        "--pair-counts",
        default="1,2,3,5",
        help="Comma-separated pair counts.",
    )
    parser.add_argument(
        "--overlap-map",
        default="1:0,2:1,3:1,5:2",
        help="Comma-separated size:overlap values (e.g. 1:0,2:1,3:1).",
    )
    parser.add_argument(
        "--human-label",
        default="Voice A",
        help="Human label for chunk output.",
    )
    parser.add_argument(
        "--assistant-label",
        default="Voice B",
        help="Assistant label for chunk output.",
    )
    parser.add_argument(
        "--model",
        default="openai/gpt-4o-mini",
        help="OpenRouter model name.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Async classifier worker count.",
    )
    parser.add_argument(
        "--error-log-dir",
        default="texture-chunker/error_logs",
        help="Directory for async classifier error logs.",
    )
    parser.add_argument(
        "--preserve-order",
        action="store_true",
        help="Preserve order in async classifier output.",
    )
    parser.add_argument(
        "--keep-delta",
        action="store_true",
        help="Keep delta directories after merging.",
    )
    parser.add_argument(
        "--reprocess-changed",
        action="store_true",
        help="Reprocess conversations whose source files changed.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Wipe outputs/state and rebuild from all exports.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List conversations that would be processed and exit.",
    )

    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    exports_root = (repo_root / args.exports_root).resolve()
    state_path = (repo_root / args.state_file).resolve()
    base_dir = Path(__file__).resolve().parent

    try:
        pair_counts = [int(x.strip()) for x in args.pair_counts.split(",") if x.strip()]
        validate_pair_counts(pair_counts)
        overlap_map = parse_overlap_map(args.overlap_map)
        validate_overlaps(pair_counts, overlap_map)
    except ValueError as exc:
        print(f"Invalid configuration: {exc}", file=sys.stderr)
        return 1

    if args.rebuild:
        for path in [
            base_dir / "chunks",
            base_dir / "chunks_clean",
            base_dir / "chunks_tagged",
            base_dir / "chunks_scored",
        ]:
            if path.exists():
                for item in sorted(path.rglob("*"), reverse=True):
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        item.rmdir()
                path.rmdir()
        if state_path.exists():
            state_path.unlink()

    state = load_state(state_path)
    processed = state.get("processed", {})
    new_files: List[Path] = []
    processed_updates: Dict[str, Dict[str, object]] = {}
    processed_zero: List[Path] = []

    for path in iter_conversation_files(exports_root):
        signature = file_signature(path)
        stored = processed.get(str(path))
        if not stored:
            new_files.append(path)
            continue
        if stored.get("mtime") != signature["mtime"] or stored.get("size") != signature["size"]:
            if args.reprocess_changed:
                new_files.append(path)
            else:
                print(f"Skipping changed file (use --reprocess-changed): {path}")

    if not new_files:
        print("No new conversations to process.")
        return 0

    if args.dry_run:
        for path in new_files:
            print(path)
        print(f"Dry run: {len(new_files)} conversation(s) would be processed.")
        return 0

    delta_root = base_dir / "_delta"
    delta_chunks = delta_root / "chunks"
    delta_clean = delta_root / "chunks_clean"
    delta_tagged = delta_root / "chunks_tagged"
    delta_scored = delta_root / "chunks_scored"

    if delta_root.exists():
        # Avoid accidental mixing of runs
        raise RuntimeError(f"Delta directory exists: {delta_root}")

    delta_root.mkdir(parents=True, exist_ok=True)

    delta_has_chunks = False
    for path in new_files:
        raw = path.read_text(encoding="utf-8", errors="replace")
        if "\ufffd" in raw:
            print(f"Warning: replacement characters found in {path}", file=sys.stderr)
        lines = raw.splitlines()
        conversation_name = parse_conversation_name(lines)
        source_date = extract_date_from_path(path)
        turns = normalize_turns(parse_conversation_md_lines(lines))
        pairs = pair_turns(turns)
        if not pairs:
            processed_zero.append(path)
            processed[str(path)] = file_signature(path)
            continue

        for size in pair_counts:
            overlap = overlap_map.get(size, 0)
            stride = max(1, size - overlap)
            for chunk_index, chunk in enumerate(chunk_pairs(pairs, size, stride)):
                chunk_id_raw = f"{path}|{size}|{chunk_index}"
                chunk_id = hashlib.sha1(chunk_id_raw.encode("utf-8")).hexdigest()
                record = {
                    "chunk_id": chunk_id,
                    "source_path": str(path),
                    "conversation_name": conversation_name,
                    "source_date": source_date,
                    "chunk_index": chunk_index,
                    "pair_count": size,
                    "text": format_chunk_text(
                        chunk, args.human_label, args.assistant_label
                    ),
                    "pairs": [
                        {
                            "voice_a": pair.human.text,
                            "voice_b": pair.assistant.text,
                        }
                        for pair in chunk
                    ],
                }
                record_chunk(delta_chunks, size, record)
                delta_has_chunks = True

        processed_updates[str(path)] = file_signature(path)

    if processed_zero:
        save_state(state_path, {"processed": processed})

    if not delta_has_chunks:
        if processed_updates:
            raise RuntimeError(
                "No chunks created for non-empty conversations. Check pair-counts."
            )
        print(f"Processed {len(new_files)} new conversation(s).")
        return 0

    try:
        run_step(
            [
                sys.executable,
                str(base_dir / "clean_chunks.py"),
                "--input",
                str(delta_chunks),
                "--output",
                str(delta_clean),
            ],
            cwd=repo_root,
        )

        run_step(
            [
                sys.executable,
                str(base_dir / "classify_chunks_openrouter_async.py"),
                "--input",
                str(delta_clean),
                "--output",
                str(delta_tagged),
                "--model",
                args.model,
                "--workers",
                str(args.workers),
                "--error-log",
                str((repo_root / args.error_log_dir).resolve()),
            ]
            + (["--preserve-order"] if args.preserve_order else []),
            cwd=repo_root,
        )

        run_step(
            [
                sys.executable,
                str(base_dir / "feels_scorer.py"),
                "--input",
                str(delta_tagged),
                "--output",
                str(delta_scored),
            ],
            cwd=repo_root,
        )

        append_dir(delta_chunks, base_dir / "chunks")
        append_dir(delta_clean, base_dir / "chunks_clean")
        append_dir(delta_tagged, base_dir / "chunks_tagged")
        append_dir(delta_scored, base_dir / "chunks_scored")

        # Add saliency scores to the merged chunks_scored files
        saliency_script = repo_root / "saliency-detector" / "add_salience_to_chunks.py"
        if saliency_script.exists():
            run_step(
                [sys.executable, str(saliency_script)],
                cwd=repo_root,
            )
        else:
            print(f"Warning: saliency script not found: {saliency_script}", file=sys.stderr)

        if processed_updates:
            processed.update(processed_updates)
            save_state(state_path, {"processed": processed})

    except Exception:
        # Do not advance state on failure to avoid gaps.
        raise

    if not args.keep_delta:
        for path in sorted(delta_root.rglob("*"), reverse=True):
            if path.is_file():
                try:
                    path.unlink()
                except OSError as exc:
                    print(f"Cleanup failed for file {path}: {exc}", file=sys.stderr)
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError as exc:
                    print(f"Cleanup failed for dir {path}: {exc}", file=sys.stderr)

    print(f"Processed {len(new_files)} new conversation(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
