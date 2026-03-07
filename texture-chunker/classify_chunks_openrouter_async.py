import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiofiles
import aiohttp
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


async def classify_excerpt(
    session: aiohttp.ClientSession,
    api_key: str,
    model: str,
    text: str,
    timeout: aiohttp.ClientTimeout,
    max_retries: int,
    request_delay: float,
) -> Tuple[List[str], List[str], str]:
    """Classify an excerpt with retry logic and proper error handling."""
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
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_error: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            async with session.post(
                url, headers=headers, json=payload, timeout=timeout
            ) as response:
                # Check status before raising to access headers
                status = response.status
                
                # Handle rate limiting and retryable errors
                if status in (408, 429):
                    if attempt < max_retries:
                        # Try to use Retry-After header if present
                        retry_after = None
                        retry_after_str = response.headers.get("Retry-After")
                        if retry_after_str:
                            try:
                                retry_after = float(retry_after_str)
                            except (ValueError, TypeError):
                                pass
                        
                        # Use Retry-After if available, otherwise exponential backoff
                        delay = retry_after if retry_after is not None else (request_delay * (2 ** (attempt - 1)))
                        await asyncio.sleep(delay)
                        continue
                    response.raise_for_status()
                
                # Raise for other status codes
                response.raise_for_status()
                data = await response.json()
                content = data["choices"][0]["message"]["content"]
                tags, unknown = parse_tags(content)
                return tags, unknown, content
        except asyncio.TimeoutError as exc:
            last_error = exc
            if attempt < max_retries:
                await asyncio.sleep(request_delay * attempt)
                continue
            raise exc
        except aiohttp.ClientResponseError as exc:
            last_error = exc
            status = exc.status
            
            # Don't retry on other 4xx errors (client errors like 400, 401, 403)
            # 408 and 429 are handled above before raise_for_status
            if 400 <= status < 500:
                raise exc
            
            # Retry 5xx errors
            if attempt < max_retries:
                await asyncio.sleep(request_delay * attempt)
                continue
            raise exc
        except aiohttp.ClientError as exc:
            last_error = exc
            if attempt < max_retries:
                await asyncio.sleep(request_delay * attempt)
                continue
            raise exc
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                await asyncio.sleep(request_delay * attempt)
                continue
            raise exc

    raise last_error if last_error else RuntimeError("Unknown error")


class RecordProcessor:
    """Handles processing of records with concurrency control and safe file writing."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        model: str,
        timeout: aiohttp.ClientTimeout,
        max_retries: int,
        request_delay: float,
        max_chars: Optional[int],
        primary_tag_limit: int,
        skip_tagged: bool,
        write_lock: asyncio.Lock,
        stats_lock: asyncio.Lock,
        output_file: Any,  # aiofiles.threadpool.AsyncTextIOWrapper
        stats: Dict[str, int],
        error_logger: Optional[Any] = None,  # Optional error log file handle
        preserve_order: bool = False,
    ):
        self.session = session
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.request_delay = request_delay
        self.max_chars = max_chars
        self.primary_tag_limit = primary_tag_limit
        self.skip_tagged = skip_tagged
        self.write_lock = write_lock
        self.stats_lock = stats_lock
        self.output_file = output_file
        self.stats = stats
        self.error_logger = error_logger
        self.preserve_order = preserve_order
        self._buffer: Dict[int, str] = {}
        self._next_line = 1
        self._failed_lines: set[int] = set()

    async def _increment_stat(self, key: str) -> None:
        """Thread-safe stat increment."""
        async with self.stats_lock:
            self.stats[key] = self.stats.get(key, 0) + 1

    async def _log_error(self, line_number: int, record: dict, error: Exception) -> None:
        """Log error with context."""
        error_msg = (
            f"Line {line_number}: {type(error).__name__}: {error}\n"
            f"  Record keys: {list(record.keys())}\n"
            f"  Text preview: {str(record.get('text', ''))[:100]}...\n"
        )
        print(error_msg, file=sys.stderr)
        
        # Optionally write to error log file
        if self.error_logger:
            error_record = {
                "line_number": line_number,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "record": record,
            }
            async with self.write_lock:
                await self.error_logger.write(
                    json.dumps(error_record, ensure_ascii=False) + "\n"
                )
                await self.error_logger.flush()

    async def _mark_failed(self, line_number: int) -> None:
        if not self.preserve_order:
            return
        async with self.write_lock:
            self._failed_lines.add(line_number)
            while self._next_line in self._failed_lines:
                self._next_line += 1

    async def _write_record(self, record: dict, line_number: int) -> None:
        payload = json.dumps(record, ensure_ascii=False) + "\n"
        if not self.preserve_order:
            async with self.write_lock:
                await self.output_file.write(payload)
                await self.output_file.flush()
            return

        async with self.write_lock:
            self._buffer[line_number] = payload
            while self._next_line in self._buffer:
                await self.output_file.write(self._buffer.pop(self._next_line))
                await self.output_file.flush()
                self._next_line += 1

    async def process_record(
        self, record: dict, line_number: int
    ) -> Tuple[Optional[dict], Optional[Exception]]:
        """Process a single record and return the updated record or error."""
        try:
            # Skip if already tagged, but ensure missing fields are computed
            if self.skip_tagged and record.get("tags"):
                # Compute missing fields if absent
                if "tags_primary" not in record and record.get("tags"):
                    record["tags_primary"] = pick_primary_tags(
                        record["tags"], self.primary_tag_limit
                    )
                if "scale" not in record:
                    record["scale"] = derive_scale(record.get("pair_count"))
                
                await self._write_record(record, line_number)
                await self._increment_stat("skipped")
                return record, None

            # Prepare text
            text = str(record.get("text", ""))
            if self.max_chars and len(text) > self.max_chars:
                text = text[: self.max_chars]

            # Classify
            tags, unknown, raw = await classify_excerpt(
                self.session,
                self.api_key,
                self.model,
                text,
                self.timeout,
                self.max_retries,
                self.request_delay,
            )

            # Update record
            record["tags"] = tags
            record["tags_primary"] = pick_primary_tags(tags, self.primary_tag_limit)
            record["tags_unknown"] = unknown
            record["tags_raw"] = raw
            record["tags_model"] = self.model
            record["scale"] = derive_scale(record.get("pair_count"))

            # Write with lock to ensure thread safety and order
            await self._write_record(record, line_number)

            await self._increment_stat("processed")
            return record, None

        except Exception as exc:
            await self._increment_stat("errors")
            await self._log_error(line_number, record, exc)
            await self._mark_failed(line_number)
            return None, exc

    async def flush_buffered(self) -> None:
        if not self.preserve_order:
            return
        async with self.write_lock:
            for line_number in sorted(self._buffer.keys()):
                await self.output_file.write(self._buffer[line_number])
                await self.output_file.flush()
                self._next_line = max(self._next_line, line_number + 1)
            self._buffer.clear()


async def worker(
    worker_id: int,
    queue: asyncio.Queue,
    processor: RecordProcessor,
    semaphore: asyncio.Semaphore,
) -> None:
    """Worker coroutine that processes records from the queue."""
    while True:
        item = await queue.get()
        if item is None:  # Poison pill to signal shutdown
            queue.task_done()
            break

        record, line_number = item
        async with semaphore:
            result, error = await processor.process_record(record, line_number)
            # Error is already logged in process_record, but we can add worker context if needed
            if error is not None:
                print(
                    f"Worker {worker_id}: Failed to process line {line_number}",
                    file=sys.stderr,
                )

        queue.task_done()


async def process_file_async(
    input_file: Path,
    output_file: Path,
    processor_config: dict,
    workers: int,
    limit: Optional[int],
    error_log_file: Optional[Path] = None,
    preserve_order: bool = False,
) -> Tuple[int, Dict[str, int]]:
    """Process a single file asynchronously with multiple workers."""
    stats = defaultdict(int)
    write_lock = asyncio.Lock()
    stats_lock = asyncio.Lock()

    # Open output file asynchronously
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Open error log file if specified
    if error_log_file:
        error_log_file.parent.mkdir(parents=True, exist_ok=True)
    
    async with aiofiles.open(output_file, "w", encoding="utf-8") as output_handle:
        if error_log_file:
            error_log_handle = await aiofiles.open(
                error_log_file, "w", encoding="utf-8"
            )
        else:
            error_log_handle = None
        
        # Create processor
        processor = RecordProcessor(
            write_lock=write_lock,
            stats_lock=stats_lock,
            output_file=output_handle,
            stats=stats,
            error_logger=error_log_handle,
            preserve_order=preserve_order,
            **processor_config,
        )

        # Create queue and semaphore for rate limiting
        queue: asyncio.Queue = asyncio.Queue(maxsize=workers * 2)
        semaphore = asyncio.Semaphore(workers)

        # Start workers
        worker_tasks = [
            asyncio.create_task(worker(i, queue, processor, semaphore))
            for i in range(workers)
        ]

        # Read and enqueue records
        processed_count = 0
        async with aiofiles.open(input_file, "r", encoding="utf-8") as src:
            line_number = 0
            async for line in src:
                line_number += 1
                line = line.strip()
                if not line:
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    print(
                        f"Error parsing JSON on line {line_number} of {input_file}: {exc}",
                        file=sys.stderr,
                    )
                    async with stats_lock:
                        stats["errors"] += 1
                    continue

                await queue.put((record, line_number))
                processed_count += 1

                if limit is not None and processed_count >= limit:
                    break

        # Signal workers to shutdown
        for _ in range(workers):
            await queue.put(None)

        # Wait for all workers to finish
        await queue.join()
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        await processor.flush_buffered()

        if error_log_handle:
            await error_log_handle.close()

    return stats["processed"], dict(stats)


async def main_async(args) -> int:
    """Main async function."""
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

    # Create aiohttp session with connection pooling
    timeout = aiohttp.ClientTimeout(total=args.timeout)
    connector = aiohttp.TCPConnector(limit=args.workers * 2, limit_per_host=args.workers)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        processor_config = {
            "session": session,
            "api_key": api_key,
            "model": args.model,
            "timeout": timeout,
            "max_retries": args.max_retries,
            "request_delay": args.request_delay,
            "max_chars": args.max_chars,
            "primary_tag_limit": args.primary_tag_limit,
            "skip_tagged": args.skip_tagged,
        }

        total_processed = 0
        total_stats = defaultdict(int)

        for input_file in iter_input_files(input_path):
            out_file = resolve_output_path(input_file, output_path, output_is_dir)
            
            # Resolve error log path if specified
            error_log_file = None
            if args.error_log:
                error_log_base = Path(args.error_log)
                if error_log_base.exists() and error_log_base.is_dir():
                    error_log_file = error_log_base / (
                        input_file.stem + ".errors.jsonl"
                    )
                elif output_is_dir:
                    error_log_file = error_log_base / (
                        input_file.stem + ".errors.jsonl"
                    )
                else:
                    error_log_file = error_log_base

            try:
                processed, file_stats = await process_file_async(
                    input_file,
                    out_file,
                    processor_config,
                    args.workers,
                    args.limit - total_processed if args.limit else None,
                    error_log_file,
                    args.preserve_order,
                )

                total_processed += processed
                for key, value in file_stats.items():
                    total_stats[key] += value

                print(
                    f"{input_file} -> {out_file} ({processed} processed, "
                    f"skipped: {file_stats.get('skipped', 0)}, "
                    f"errors: {file_stats.get('errors', 0)})"
                )

                if args.limit is not None and total_processed >= args.limit:
                    break

            except Exception as exc:
                print(
                    f"Error processing {input_file}: {exc}",
                    file=sys.stderr,
                )
                return 1

    if total_stats.get("errors", 0) > 0:
        print(
            f"\nCompleted with {total_stats['errors']} errors.",
            file=sys.stderr,
        )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Tag chunks via OpenRouter (async).")
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
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of concurrent workers for parallel processing.",
    )
    parser.add_argument(
        "--error-log",
        type=str,
        default=None,
        help="Optional path to write error log JSONL file with failed records.",
    )
    parser.add_argument(
        "--preserve-order",
        action="store_true",
        help="Preserve input order in output (slower, buffered).",
    )

    args = parser.parse_args()

    if args.workers < 1:
        print("--workers must be at least 1.", file=sys.stderr)
        return 1

    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

