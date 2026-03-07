"""
Per-type baselines and prediction error computation.

PER-42: Baselines and prediction error.

Uses Welford's online algorithm for incremental mean/std updates.
Seeded with reasonable defaults that get overwritten by real data.
"""

import math
import copy
import logging
from typing import Optional

log = logging.getLogger("interoception.baselines")

SIGNAL_NAMES = ["meta_commentary", "hedging_ratio", "self_correction", "question_density", "affect_valence", "affect_arousal"]

# Seed baselines: reasonable guesses, count=5 so real data blends in quickly.
# These will be overwritten as pulses accumulate (~20 per type to fully replace).
SEED_BASELINES = {
    "infrastructure": {
        "meta_commentary": {"mean": 0.05, "std": 0.04, "count": 5, "_m2": 0.0},
        "hedging_ratio": {"mean": 0.35, "std": 0.10, "count": 5, "_m2": 0.0},
        "self_correction": {"mean": 1.0, "std": 1.0, "count": 5, "_m2": 0.0},
        "question_density": {"mean": 0.05, "std": 0.04, "count": 5, "_m2": 0.0},
        "affect_valence": {"mean": 0.0, "std": 0.15, "count": 5, "_m2": 0.0},
        "affect_arousal": {"mean": 0.35, "std": 0.10, "count": 5, "_m2": 0.0},
    },
    "philosophical": {
        "meta_commentary": {"mean": 0.30, "std": 0.12, "count": 5, "_m2": 0.0},
        "hedging_ratio": {"mean": 0.55, "std": 0.12, "count": 5, "_m2": 0.0},
        "self_correction": {"mean": 2.0, "std": 1.5, "count": 5, "_m2": 0.0},
        "question_density": {"mean": 0.15, "std": 0.08, "count": 5, "_m2": 0.0},
        "affect_valence": {"mean": 0.10, "std": 0.20, "count": 5, "_m2": 0.0},
        "affect_arousal": {"mean": 0.45, "std": 0.12, "count": 5, "_m2": 0.0},
    },
    "companion": {
        "meta_commentary": {"mean": 0.20, "std": 0.15, "count": 5, "_m2": 0.0},
        "hedging_ratio": {"mean": 0.45, "std": 0.15, "count": 5, "_m2": 0.0},
        "self_correction": {"mean": 1.5, "std": 1.2, "count": 5, "_m2": 0.0},
        "question_density": {"mean": 0.12, "std": 0.08, "count": 5, "_m2": 0.0},
        "affect_valence": {"mean": 0.15, "std": 0.20, "count": 5, "_m2": 0.0},
        "affect_arousal": {"mean": 0.50, "std": 0.15, "count": 5, "_m2": 0.0},
    },
    "consolidation": {
        "meta_commentary": {"mean": 0.15, "std": 0.08, "count": 5, "_m2": 0.0},
        "hedging_ratio": {"mean": 0.30, "std": 0.10, "count": 5, "_m2": 0.0},
        "self_correction": {"mean": 0.8, "std": 0.8, "count": 5, "_m2": 0.0},
        "question_density": {"mean": 0.06, "std": 0.04, "count": 5, "_m2": 0.0},
        "affect_valence": {"mean": 0.05, "std": 0.12, "count": 5, "_m2": 0.0},
        "affect_arousal": {"mean": 0.30, "std": 0.10, "count": 5, "_m2": 0.0},
    },
    "exploratory": {
        "meta_commentary": {"mean": 0.20, "std": 0.15, "count": 5, "_m2": 0.0},
        "hedging_ratio": {"mean": 0.45, "std": 0.15, "count": 5, "_m2": 0.0},
        "self_correction": {"mean": 1.5, "std": 1.5, "count": 5, "_m2": 0.0},
        "question_density": {"mean": 0.10, "std": 0.08, "count": 5, "_m2": 0.0},
        "affect_valence": {"mean": 0.10, "std": 0.20, "count": 5, "_m2": 0.0},
        "affect_arousal": {"mean": 0.40, "std": 0.15, "count": 5, "_m2": 0.0},
    },
}

# Z-score threshold for flagging a signal as deviant
DEVIATION_THRESHOLD = 1.5


def get_default_baselines() -> dict:
    """Return a fresh copy of seed baselines.

    Initializes _m2 from std and count for Welford continuity:
    _m2 = std^2 * count
    """
    baselines = copy.deepcopy(SEED_BASELINES)
    for type_name, signals in baselines.items():
        for sig_name, stats in signals.items():
            # Bootstrap _m2 from std and count so Welford can continue
            stats["_m2"] = (stats["std"] ** 2) * stats["count"]
    return baselines


def welford_update(stats: dict, new_value: float) -> dict:
    """Update running mean/std using Welford's online algorithm.

    stats must have: mean, count, _m2
    Updates in place and recomputes std.
    """
    count = stats["count"] + 1
    delta = new_value - stats["mean"]
    new_mean = stats["mean"] + delta / count
    delta2 = new_value - new_mean
    new_m2 = stats["_m2"] + delta * delta2

    stats["count"] = count
    stats["mean"] = round(new_mean, 4)
    stats["_m2"] = round(new_m2, 6)
    stats["std"] = round(math.sqrt(new_m2 / count) if count > 1 else stats["std"], 4)
    return stats


def update_baselines(baselines: dict, observed_type: str, signals: dict) -> dict:
    """Update the baseline for observed_type with new signal values.

    Args:
        baselines: full baselines dict from state
        observed_type: the classified conversation type
        signals: dict with signal_name -> value

    Returns updated baselines dict.
    """
    if observed_type not in baselines:
        baselines[observed_type] = copy.deepcopy(SEED_BASELINES.get("exploratory", {}))
        # Bootstrap _m2
        for sig_name, stats in baselines[observed_type].items():
            stats["_m2"] = (stats["std"] ** 2) * stats["count"]

    type_baseline = baselines[observed_type]
    for sig_name in SIGNAL_NAMES:
        if sig_name in signals and sig_name in type_baseline:
            welford_update(type_baseline[sig_name], float(signals[sig_name]))

    return baselines


def compute_deviations(
    baselines: dict, observed_type: str, signals: dict
) -> dict[str, Optional[float]]:
    """Compute z-score deviations for each signal against type baseline.

    Returns dict of signal_name -> z_score (None if insufficient data).
    """
    deviations = {}
    type_baseline = baselines.get(observed_type, {})

    for sig_name in SIGNAL_NAMES:
        stats = type_baseline.get(sig_name)
        if not stats or stats.get("count", 0) < 3:
            deviations[sig_name] = None
            continue

        std = stats.get("std", 0)
        if std < 0.001:
            # Near-zero std: any deviation is notable
            diff = abs(float(signals.get(sig_name, 0)) - stats["mean"])
            deviations[sig_name] = 10.0 if diff > 0.01 else 0.0
        else:
            z = (float(signals.get(sig_name, 0)) - stats["mean"]) / std
            deviations[sig_name] = round(z, 2)

    return deviations


def format_prediction_error(
    predicted_type: str,
    predicted_confidence: float,
    observed_type: str,
    observed_confidence: float,
    signals: dict,
    deviations: dict[str, Optional[float]],
) -> Optional[str]:
    """Format the interoceptive injection block with prediction error context.

    Returns None if nothing notable to report.
    """
    type_match = predicted_type == observed_type
    any_deviation = any(
        v is not None and abs(v) > DEVIATION_THRESHOLD
        for v in deviations.values()
    )

    # If types match and no signal deviations, nothing to report
    if type_match and not any_deviation:
        return None

    # Build header
    if type_match:
        header = f"Interoceptive signal ({observed_type} context, confirmed):"
    else:
        header = f"Interoceptive signal (predicted: {predicted_type}, observed: {observed_type}):"

    lines = [header]
    for sig_name in SIGNAL_NAMES:
        value = signals.get(sig_name, 0)
        z = deviations.get(sig_name)
        if z is not None and abs(z) > DEVIATION_THRESHOLD:
            direction = "+" if z > 0 else ""
            lines.append(f"- {sig_name}: {value} ({direction}{z:.1f} std vs {observed_type} baseline)")
        else:
            lines.append(f"- {sig_name}: {value} (within expected)")

    return "\n".join(lines)
