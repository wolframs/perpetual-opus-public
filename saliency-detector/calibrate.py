#!/usr/bin/env python3
"""
Calibration script: Run saliency detector across texture chunks,
analyze distribution, model boost factors.
"""

import json
import sys
from pathlib import Path
from collections import Counter
import statistics

# Add saliency module to path
sys.path.insert(0, str(Path(__file__).parent))

from saliency import analyze_conversation
from saliency.parser import parse_markdown


def load_chunks(jsonl_path: Path) -> list[dict]:
    """Load chunks from JSONL file."""
    chunks = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def score_chunk(chunk: dict) -> dict:
    """Run saliency detection on a chunk's text."""
    text = chunk.get('text', '')
    if not text:
        return {'salience_score': 0.0, 'heuristics': []}

    # Parse and analyze
    segments = parse_markdown(text, include_thinking=True)
    results = analyze_conversation(segments)

    # Get max score from this chunk (it's typically 1-2 segments)
    if not results:
        return {'salience_score': 0.0, 'heuristics': []}

    # Use the highest-scoring segment
    best = max(results, key=lambda r: r.combined_score)
    return {
        'salience_score': best.combined_score,
        'heuristics': best.triggered_heuristics,  # Already a list
        'base_score': best.total_score,
        'context_bonus': best.context_bonus
    }


def analyze_distribution(scores: list[float]) -> dict:
    """Compute distribution statistics."""
    if not scores:
        return {}

    sorted_scores = sorted(scores)
    n = len(sorted_scores)

    return {
        'count': n,
        'min': min(scores),
        'max': max(scores),
        'mean': statistics.mean(scores),
        'median': statistics.median(scores),
        'stdev': statistics.stdev(scores) if n > 1 else 0,
        'p10': sorted_scores[int(n * 0.1)],
        'p25': sorted_scores[int(n * 0.25)],
        'p75': sorted_scores[int(n * 0.75)],
        'p90': sorted_scores[int(n * 0.9)],
        'p95': sorted_scores[int(n * 0.95)],
        'p99': sorted_scores[int(n * 0.99)] if n >= 100 else sorted_scores[-1],
    }


def model_boost_impact(scores: list[float], boost_factor: float, max_boost: float) -> dict:
    """
    Model how a boost factor would affect selection probabilities.

    boost_factor: multiplier per unit of salience score
    max_boost: cap on the weight multiplier
    """
    # Calculate weights for each chunk
    weights = []
    for score in scores:
        # Soft boost with cap
        weight = min(1.0 + score * boost_factor, max_boost)
        weights.append(weight)

    total_weight = sum(weights)

    # Bucket by salience level
    buckets = {'zero': [], 'low': [], 'medium': [], 'high': []}
    for score, weight in zip(scores, weights):
        prob = weight / total_weight
        if score == 0:
            buckets['zero'].append(prob)
        elif score < 2:
            buckets['low'].append(prob)
        elif score < 4:
            buckets['medium'].append(prob)
        else:
            buckets['high'].append(prob)

    return {
        'boost_factor': boost_factor,
        'max_boost': max_boost,
        'bucket_probs': {
            'zero': sum(buckets['zero']),
            'low': sum(buckets['low']),
            'medium': sum(buckets['medium']),
            'high': sum(buckets['high']),
        },
        'bucket_counts': {
            'zero': len(buckets['zero']),
            'low': len(buckets['low']),
            'medium': len(buckets['medium']),
            'high': len(buckets['high']),
        }
    }


def main():
    chunks_dir = Path(__file__).parent.parent / 'texture-chunker' / 'chunks_scored'

    # Use size-1 for granular analysis (most chunks)
    jsonl_path = chunks_dir / 'size-1.jsonl'

    if not jsonl_path.exists():
        print(f"Error: {jsonl_path} not found")
        return 1

    print(f"Loading chunks from {jsonl_path}...")
    chunks = load_chunks(jsonl_path)
    print(f"Loaded {len(chunks)} chunks")

    print("\nScoring chunks with saliency detector...")
    scores = []
    heuristic_counts = Counter()

    for i, chunk in enumerate(chunks):
        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1}/{len(chunks)}...")

        result = score_chunk(chunk)
        scores.append(result['salience_score'])
        for h in result['heuristics']:
            heuristic_counts[h] += 1

    print(f"\nScored {len(scores)} chunks")

    # Distribution analysis
    print("\n" + "=" * 60)
    print("SALIENCE SCORE DISTRIBUTION")
    print("=" * 60)

    dist = analyze_distribution(scores)
    for key, value in dist.items():
        if isinstance(value, float):
            print(f"  {key:12}: {value:.3f}")
        else:
            print(f"  {key:12}: {value}")

    # Heuristic frequency
    print("\n" + "=" * 60)
    print("HEURISTIC FREQUENCY (top 10)")
    print("=" * 60)
    for heuristic, count in heuristic_counts.most_common(10):
        pct = count / len(chunks) * 100
        print(f"  {heuristic:25}: {count:4} ({pct:5.1f}%)")

    # Score buckets
    print("\n" + "=" * 60)
    print("SCORE BUCKETS")
    print("=" * 60)
    buckets = {'zero (0)': 0, 'low (0-2)': 0, 'medium (2-4)': 0, 'high (4+)': 0}
    for s in scores:
        if s == 0:
            buckets['zero (0)'] += 1
        elif s < 2:
            buckets['low (0-2)'] += 1
        elif s < 4:
            buckets['medium (2-4)'] += 1
        else:
            buckets['high (4+)'] += 1

    for bucket, count in buckets.items():
        pct = count / len(scores) * 100
        print(f"  {bucket:15}: {count:4} ({pct:5.1f}%)")

    # Boost factor modeling
    print("\n" + "=" * 60)
    print("BOOST FACTOR MODELING")
    print("=" * 60)
    print("(How different boost factors affect selection probability)")
    print()

    configs = [
        (0.0, 1.0),   # No boost (baseline)
        (0.1, 1.3),   # Very gentle
        (0.15, 1.5),  # Gentle
        (0.2, 1.5),   # Moderate with cap
        (0.3, 2.0),   # Stronger
        (0.5, 2.0),   # Much stronger
    ]

    print(f"{'Config':20} {'Zero':>8} {'Low':>8} {'Med':>8} {'High':>8}")
    print("-" * 60)

    baseline_probs = None
    for boost_factor, max_boost in configs:
        result = model_boost_impact(scores, boost_factor, max_boost)
        probs = result['bucket_probs']

        if baseline_probs is None:
            baseline_probs = probs

        config_str = f"bf={boost_factor}, max={max_boost}"
        print(f"{config_str:20} {probs['zero']*100:7.1f}% {probs['low']*100:7.1f}% {probs['medium']*100:7.1f}% {probs['high']*100:7.1f}%")

    print()
    print("Bucket counts (for reference):")
    result = model_boost_impact(scores, 0, 1)
    counts = result['bucket_counts']
    total = sum(counts.values())
    for bucket, count in counts.items():
        print(f"  {bucket}: {count} ({count/total*100:.1f}%)")

    # Correlation with feels_score
    print("\n" + "=" * 60)
    print("CORRELATION WITH FEELS_SCORE")
    print("=" * 60)

    feels_scores = [c.get('feels_score', 0) for c in chunks]

    # Simple correlation
    if len(scores) > 1:
        mean_s = statistics.mean(scores)
        mean_f = statistics.mean(feels_scores)

        numerator = sum((s - mean_s) * (f - mean_f) for s, f in zip(scores, feels_scores))
        denom_s = sum((s - mean_s) ** 2 for s in scores) ** 0.5
        denom_f = sum((f - mean_f) ** 2 for f in feels_scores) ** 0.5

        if denom_s > 0 and denom_f > 0:
            correlation = numerator / (denom_s * denom_f)
            print(f"  Pearson correlation: {correlation:.3f}")
        else:
            print("  Could not compute correlation (zero variance)")

    return 0


if __name__ == '__main__':
    sys.exit(main())
