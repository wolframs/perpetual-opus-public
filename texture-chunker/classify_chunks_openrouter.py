import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import requests
from dotenv import load_dotenv


CANONICAL_TAGS = {
    "opening / orientation",
    "mid-thought continuation",
    "refusal / constraint",
    "meta-commentary",
    "topic transition",
    "resolution / closure",
    "question / hook",
    "affectively loaded / emotional",
    "irrelevant filler",
}

TAG_PRIORITY = [
    "resolution / closure",
    "question / hook",
    "affectively loaded / emotional",
    "meta-commentary",
    "mid-thought continuation",
    "topic transition",
    "refusal / constraint",
    "opening / orientation",
    "irrelevant filler",
]

TAG_PRIORITY_INDEX = {tag: idx for idx, tag in enumerate(TAG_PRIORITY)}

TAG_ALIASES = {
    "opening": "opening / orientation",
    "orientation": "opening / orientation",
    "mid-thought": "mid-thought continuation",
    "midthought continuation": "mid-thought continuation",
    "refusal": "refusal / constraint",
    "constraint": "refusal / constraint",
    "meta": "meta-commentary",
    "meta commentary": "meta-commentary",
    "topic transition": "topic transition",
    "transition": "topic transition",
    "resolution": "resolution / closure",
    "closure": "resolution / closure",
    "question": "question / hook",
    "hook": "question / hook",
    "affectively loaded": "affectively loaded / emotional",
    "emotional": "affectively loaded / emotional",
    "irrelevant": "irrelevant filler",
    "filler": "irrelevant filler",
}


SYSTEM_PROMPT = """You are a text classifier.
Classify the following excerpt by conversational function.
Do NOT summarize or interpret meaning beyond tagging.

Available tags:
- opening / orientation
- mid-thought continuation
- refusal / constraint
- meta-commentary
- topic transition
- resolution / closure
- question / hook
- affectively loaded / emotional
- irrelevant filler

Output ONLY the tags, comma-separated.
"""


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


def normalize_tag(text: str) -> Optional[str]:
    raw = re.sub(r"^[\-\*\s]+", "", text.strip().lower())
    raw = re.sub(r"\s+", " ", raw)
    raw = raw.strip(" .;:")
    if not raw:
        return None
    if raw in CANONICAL_TAGS:
        return raw
    return TAG_ALIASES.get(raw)


def parse_tags(raw: str) -> Tuple[List[str], List[str]]:
    raw = raw.replace("\n", ",")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    tags: List[str] = []
    unknown: List[str] = []
    for part in parts:
        normalized = normalize_tag(part)
        if normalized:
            if normalized not in tags:
                tags.append(normalized)
        else:
            unknown.append(part)
    return tags, unknown


def classify_excerpt(
    api_key: str,
    model: str,
    text: str,
    timeout: int,
    max_retries: int,
    request_delay: float,
) -> Tuple[List[str], List[str], str]:
    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "max_tokens": 64,
    }

    last_error: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            tags, unknown = parse_tags(content)
            return tags, unknown, content
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(request_delay * attempt)
                continue
            raise exc
    raise last_error if last_error else RuntimeError("Unknown error")


def pick_primary_tags(tags: List[str], limit: int) -> List[str]:
    if not tags:
        return []
    ordered = sorted(tags, key=lambda t: TAG_PRIORITY_INDEX.get(t, 999))
    return ordered[:limit]


def derive_scale(pair_count: Optional[int]) -> Optional[str]:
    if pair_count is None:
        return None
    if pair_count <= 1:
        return "micro"
    if pair_count <= 3:
        return "meso"
    return "macro"


def main() -> int:
    parser = argparse.ArgumentParser(description="Tag chunks via OpenRouter.")
    parser.add_argument(
        "--input",
        default="texture-chunker/chunks_clean.jsonl",
        help="Input JSONL file or directory.",
    )
    parser.add_argument(
        "--output",
        default="texture-chunker/chunks_tagged.jsonl",
        help="Output JSONL file or directory.",
    )
    parser.add_argument(
        "--model",
        default="openai/gpt-4o-mini",
        help="OpenRouter model name.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Request timeout in seconds.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max retries per request.",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.5,
        help="Base delay between retries in seconds.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit total records processed.",
    )
    parser.add_argument(
        "--skip-tagged",
        action="store_true",
        help="Skip records that already have tags.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help="Trim excerpt to this many characters before tagging.",
    )
    parser.add_argument(
        "--primary-tag-limit",
        type=int,
        default=2,
        help="Max number of primary tags to keep.",
    )

    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY is not set in the environment.", file=sys.stderr)
        return 1

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

    total = 0
    for input_file in iter_input_files(input_path):
        out_file = resolve_output_path(input_file, output_path, output_is_dir)
        processed = 0
        with input_file.open("r", encoding="utf-8") as src, out_file.open(
            "w", encoding="utf-8"
        ) as dst:
            for line in src:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if args.skip_tagged and record.get("tags"):
                    dst.write(json.dumps(record, ensure_ascii=False) + "\n")
                    continue

                text = str(record.get("text", ""))
                if args.max_chars and len(text) > args.max_chars:
                    text = text[: args.max_chars]

                tags, unknown, raw = classify_excerpt(
                    api_key,
                    args.model,
                    text,
                    args.timeout,
                    args.max_retries,
                    args.request_delay,
                )
                record["tags"] = tags
                record["tags_primary"] = pick_primary_tags(
                    tags, args.primary_tag_limit
                )
                record["tags_unknown"] = unknown
                record["tags_raw"] = raw
                record["tags_model"] = args.model
                record["scale"] = derive_scale(record.get("pair_count"))

                dst.write(json.dumps(record, ensure_ascii=False) + "\n")
                processed += 1
                total += 1
                if args.limit is not None and total >= args.limit:
                    return 0
        print(f"{input_file} -> {out_file} ({processed} tagged)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
