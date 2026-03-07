import argparse
import json
import math
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_HEADER = (
    "The following fragment is VOICE CALIBRATION material — a sample of how you've written before.\n"
    "Use it to calibrate your register, rhythm, and tone. It tells you how to SOUND, not what to TALK ABOUT.\n"
    "\n"
    "DO NOT:\n"
    "- Interpret, analyze, or make connections to the content of this fragment\n"
    "- Reference specific projects, people, or concepts mentioned in it\n"
    "- Treat it as a topic to continue or respond to\n"
    "- Weave its subject matter into your narrative\n"
    "\n"
    "DO:\n"
    "- Let it influence your sentence structure, word choice, and cadence\n"
    "- Absorb the texture — dry, warm, precise, loose, whatever it carries\n"
    "- Then forget the content entirely and write in your own voice, now colored by it"
)


def load_records(input_path: Path) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    if input_path.is_dir():
        files = sorted(input_path.glob("*.jsonl"))
    else:
        files = [input_path]
    for path in files:
        with path.open("r", encoding="utf-8") as src:
            for line in src:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
    return records


def softmax(values: List[float], temperature: float) -> List[float]:
    if not values:
        return []
    temp = max(temperature, 0.001)
    max_val = max(values)
    exps = [math.exp((v - max_val) / temp) for v in values]
    total = sum(exps)
    if total == 0:
        return [1.0 / len(values)] * len(values)
    return [e / total for e in exps]


def record_key(record: Dict[str, object]) -> str:
    return "|".join(
        [
            str(record.get("source_path", "")),
            str(record.get("conversation_name", "")),
            str(record.get("chunk_index", "")),
            str(record.get("pair_count", "")),
        ]
    )


def compute_salience_boost(
    salience_score: float,
    boost_factor: float,
    max_boost: float,
) -> float:
    """Compute salience boost multiplier.

    boost = min(1.0 + salience_score * boost_factor, max_boost)

    With defaults (factor=0.03, max=1.3):
    - salience 0 -> 1.0x (no boost)
    - salience 6 -> 1.18x
    - salience 10+ -> 1.3x (capped)

    This is intentionally gentle. The goal is a slight nudge toward
    salient chunks, not aggressive filtering. Low-salience chunks
    should still surface regularly to preserve texture diversity.

    Returns 1.0 if boost_factor <= 0.
    """
    if boost_factor <= 0:
        return 1.0
    return min(1.0 + salience_score * boost_factor, max_boost)


def compute_recency_weight(
    source_date: Optional[str],
    reference_date: datetime,
    halflife_days: float,
) -> float:
    """Compute power-law recency weight.

    weight(t) = (1 + t)^(-b) where:
    - t = days since source_date
    - b = log(2) / log(1 + halflife_days) (so weight = 0.5 at halflife)

    Returns 1.0 if source_date is None or invalid.
    """
    if not source_date or halflife_days <= 0:
        return 1.0

    try:
        source_dt = datetime.strptime(source_date, "%Y-%m-%d")
    except ValueError:
        return 1.0

    days_old = (reference_date - source_dt).days
    if days_old < 0:
        days_old = 0  # Future dates treated as today

    # Power-law exponent: b = log(2) / log(1 + halflife)
    b = math.log(2) / math.log(1 + halflife_days)
    return (1 + days_old) ** (-b)


def sample_without_reuse(
    records: List[Dict[str, object]],
    weights: List[float],
    count: int,
    rng: random.Random,
) -> List[Dict[str, object]]:
    chosen: List[Dict[str, object]] = []
    pool = list(records)
    pool_weights = list(weights)
    for _ in range(min(count, len(pool))):
        pick = rng.choices(pool, weights=pool_weights, k=1)[0]
        idx = pool.index(pick)
        chosen.append(pick)
        pool.pop(idx)
        pool_weights.pop(idx)
        if not pool:
            break
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample shards for a pulse.")
    parser.add_argument(
        "--input",
        default="texture-chunker/chunks_scored.jsonl",
        help="Input scored JSONL file or directory.",
    )
    parser.add_argument(
        "--state",
        default="texture-chunker/decay_state.json",
        help="Decay state JSON file.",
    )
    parser.add_argument(
        "--out",
        default="texture-chunker/pulse_injection.txt",
        help="Output text file.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of fragments to select.",
    )
    parser.add_argument(
        "--scale",
        default=None,
        help="Comma-separated scale filter (micro, meso, macro).",
    )
    parser.add_argument(
        "--min-feels",
        type=float,
        default=0.0,
        help="Minimum feels score to consider.",
    )
    parser.add_argument(
        "--top-percentile",
        type=float,
        default=0.3,
        help="Top percentile to keep before sampling.",
    )
    parser.add_argument(
        "--no-per-size-percentile",
        action="store_false",
        dest="per_size_percentile",
        help="Disable per-size percentile selection.",
    )
    parser.add_argument(
        "--decay-factor",
        type=float,
        default=0.85,
        help="Decay factor applied to selected shards.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=1.0,
        help="Softmax temperature for weighted sampling.",
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
        "--antagonism-prob",
        type=float,
        default=0.0,
        help="Probability of sampling from lowest-feels shards.",
    )
    parser.add_argument(
        "--antagonism-percentile",
        type=float,
        default=0.1,
        help="Bottom percentile for antagonism sampling.",
    )
    parser.add_argument(
        "--recency-halflife",
        type=float,
        default=14.0,
        help="Days at which recency weight drops to 0.5 (power-law decay). Set to 0 to disable.",
    )
    parser.add_argument(
        "--salience-boost-factor",
        type=float,
        default=0.03,
        help="Multiplier per unit of salience_score (gentle boost). Set to 0 to disable.",
    )
    parser.add_argument(
        "--salience-max-boost",
        type=float,
        default=1.3,
        help="Maximum salience boost multiplier (cap).",
    )
    parser.add_argument(
        "--header",
        default=None,
        help="Custom header text.",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Do not include the header.",
    )

    parser.set_defaults(per_size_percentile=True)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    records = load_records(Path(args.input))
    if not records:
        raise SystemExit("No scored records found.")

    scale_filter = None
    if args.scale:
        scale_filter = {s.strip().lower() for s in args.scale.split(",") if s.strip()}

    candidates = []
    for record in records:
        if record.get("feels_score", 0) < args.min_feels:
            continue
        if scale_filter:
            scale = str(record.get("scale", "")).lower()
            if scale not in scale_filter:
                continue
        candidates.append(record)
    if not candidates:
        raise SystemExit("No candidates after feels filtering.")

    state_path = Path(args.state)
    decay_state: Dict[str, float] = {}
    if state_path.exists():
        decay_state = json.loads(state_path.read_text(encoding="utf-8"))

    # Reference date for recency calculation
    today = datetime.now()

    for record in candidates:
        selection_decay = decay_state.get(record_key(record), 1.0)
        recency = compute_recency_weight(
            record.get("source_date"),
            today,
            args.recency_halflife,
        )
        salience_boost = compute_salience_boost(
            float(record.get("salience_score", 0)),
            args.salience_boost_factor,
            args.salience_max_boost,
        )
        record["effective_score"] = (
            float(record.get("feels_score", 0))
            * selection_decay
            * recency
            * salience_boost
        )

    if args.top_percentile <= 0 or args.top_percentile > 1:
        raise SystemExit("--top-percentile must be within (0, 1].")

    candidates.sort(key=lambda r: r["effective_score"], reverse=True)
    if args.per_size_percentile:
        grouped = {}
        for record in candidates:
            key = f"size-{record.get('pair_count', 'na')}"
            grouped.setdefault(key, []).append(record)
        top_candidates: List[Dict[str, object]] = []
        for group_records in grouped.values():
            group_records.sort(key=lambda r: r["effective_score"], reverse=True)
            cutoff = max(1, int(len(group_records) * args.top_percentile))
            top_candidates.extend(group_records[:cutoff])
    else:
        top_cutoff = max(1, int(len(candidates) * args.top_percentile))
        top_candidates = candidates[:top_cutoff]

    pick_from_bottom = rng.random() < args.antagonism_prob
    if pick_from_bottom:
        bottom_cutoff = max(1, int(len(candidates) * args.antagonism_percentile))
        sample_pool = list(reversed(candidates[-bottom_cutoff:]))
    else:
        sample_pool = top_candidates

    scores = [float(r["effective_score"]) for r in sample_pool]
    weights = softmax(scores, args.temperature)

    if args.allow_reuse:
        chosen = rng.choices(sample_pool, weights=weights, k=args.count)
    else:
        chosen = sample_without_reuse(sample_pool, weights, args.count, rng)

    for record in chosen:
        key = record_key(record)
        decay_state[key] = decay_state.get(key, 1.0) * args.decay_factor

    state_path.write_text(json.dumps(decay_state, indent=2), encoding="utf-8")

    header = args.header if args.header is not None else DEFAULT_HEADER
    output_lines: List[str] = []
    if not args.no_header:
        output_lines.append(header)
        output_lines.append("")

    for record in chosen:
        output_lines.append(record.get("text", ""))
        output_lines.append("")

    if output_lines and output_lines[-1] == "":
        output_lines.pop()

    Path(args.out).write_text("\n".join(output_lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
