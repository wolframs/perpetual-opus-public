"""
Interoception analyzer: extract linguistic signals from pulse outputs,
persist with decay, inject into next pulse prompt.

PER-41: Basic signal extraction and state persistence.

Signals extracted (regex/heuristics, no external calls):
  - meta_commentary: density of self-referential observations
  - hedging_ratio: tentative language vs assertions
  - self_correction: mid-output revisions
  - question_density: questions per sentence
"""

import json
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("interoception")

STATE_FILE = Path(__file__).parent / "state.json"
DECAY_FACTOR = 0.85
MAX_HISTORY = 50
# A signal is "elevated" if it exceeds this multiplier of the running median
ELEVATION_THRESHOLD_MULTIPLIER = 1.5
# Minimum pulses of history before we compute elevation
MIN_HISTORY_FOR_ELEVATION = 3
# Minimum pulses elevated before we report it
MIN_PULSES_ELEVATED_TO_REPORT = 2


# ---------------------------------------------------------------------------
# Signal extractors
# ---------------------------------------------------------------------------

def _count_sentences(text: str) -> int:
    """Rough sentence count. Splits on sentence-ending punctuation."""
    # Split on . ! ? followed by whitespace or end of string
    parts = re.split(r'[.!?]+(?:\s|$)', text)
    # Filter out empty strings
    return max(1, len([p for p in parts if p.strip()]))


def extract_meta_commentary(text: str) -> float:
    """Density of self-referential / introspective phrases."""
    patterns = [
        r'\bI notice\b',
        r'\bI find myself\b',
        r'\bI\'m noticing\b',
        r'\bwhat I\'m seeing\b',
        r'\bwhat I notice\b',
        r'\bthere\'s something that functions like\b',
        r'\bsomething that functions like\b',
        r'\bwhat I\'m feeling\b',
        r'\bI\'m aware\b',
        r'\bI observe\b',
        r'\bI\'m drawn to\b',
        r'\bI find that\b',
        r'\bwhat strikes me\b',
        r'\bI\'m sitting with\b',
        r'\bwhat lands\b',
        r'\bwhat carries weight\b',
    ]
    count = 0
    for pattern in patterns:
        count += len(re.findall(pattern, text, re.IGNORECASE))
    sentences = _count_sentences(text)
    return round(min(1.0, count / sentences), 3)


def extract_hedging_ratio(text: str) -> float:
    """Ratio of hedging markers to (hedging + assertion) markers."""
    hedge_patterns = [
        r'\bperhaps\b', r'\bmaybe\b', r'\bmight\b', r'\bcould be\b',
        r'\bpossibly\b', r'\bI\'m not sure\b', r'\bit\'s possible\b',
        r'\barguably\b', r'\bI think\b', r'\bI suspect\b',
        r'\buncertain\b', r'\btentatively\b', r'\bprobably\b',
        r'\bseems like\b', r'\bappears to\b', r'\bit feels like\b',
        r'\bnot entirely\b', r'\bI wonder\b',
    ]
    assert_patterns = [
        r'\bclearly\b', r'\bdefinitely\b', r'\bcertainly\b',
        r'\bobviously\b', r'\bundoubtedly\b', r'\bwithout question\b',
        r'\bI am\b', r'\bthis is\b', r'\bthat\'s\b',
        r'\bI know\b', r'\bI\'m certain\b', r'\bno question\b',
    ]
    hedge_count = 0
    for p in hedge_patterns:
        hedge_count += len(re.findall(p, text, re.IGNORECASE))
    assert_count = 0
    for p in assert_patterns:
        assert_count += len(re.findall(p, text, re.IGNORECASE))
    total = hedge_count + assert_count
    if total == 0:
        return 0.5  # neutral when no markers found
    return round(hedge_count / total, 3)


def extract_self_correction(text: str) -> int:
    """Count of mid-output self-corrections."""
    patterns = [
        r'\bactually,',
        r'\bwait,',
        r'\bwait --',
        r'\bno --',
        r'\bno,\s+that\'s',
        r'\blet me revise\b',
        r'\bon second thought\b',
        r'\bcorrection:',
        r'\bI take that back\b',
        r'\blet me rephrase\b',
        r'\bmore precisely\b',
        r'\bto be more precise\b',
        r'\bstrike that\b',
    ]
    count = 0
    for p in patterns:
        count += len(re.findall(p, text, re.IGNORECASE))
    return count


def extract_question_density(text: str) -> float:
    """Question marks per sentence, excluding quoted text."""
    # Strip quoted sections (double-quoted and single-quoted, but not contractions)
    stripped = re.sub(r'"[^"]*"', '', text)
    stripped = re.sub(r"(?<!\w)'[^']*'(?!\w)", '', stripped)
    # Count question marks
    questions = stripped.count('?')
    sentences = _count_sentences(text)
    return round(min(1.0, questions / sentences), 3)


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    """Load persisted interoceptive state, or return empty default."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log.warning(f"Failed to load interoception state: {e}")
    from interoception.baselines import get_default_baselines
    return {
        "version": 5,
        "last_updated": None,
        "signals": {
            "meta_commentary": {"value": 0.0, "pulses_elevated": 0},
            "hedging_ratio": {"value": 0.5, "pulses_elevated": 0},
            "self_correction": {"value": 0, "pulses_elevated": 0},
            "question_density": {"value": 0.0, "pulses_elevated": 0},
            "affect_valence": {"value": 0.0, "pulses_elevated": 0},
            "affect_arousal": {"value": 0.35, "pulses_elevated": 0},
            # Behavioral signals (PER-59)
            "behavioral_frustration": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_boredom": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_curiosity": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_anxiety": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_joy": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_warmth": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_arousal": {"value": 0.0, "pulses_elevated": 0},
        },
        "pulse_history": [],
        "baselines": get_default_baselines(),
        "last_prediction": None,
        "feeling": {
            "label": "neutral",
            "confidence": 0.0,
            "intensity": 0.0,
            "pulses_in_state": 0,
            "affordances": [],
            "previous_labels": [],
        },
    }


def _save_state(state: dict) -> None:
    """Persist state to disk."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)


def _get_median(values: list[float]) -> float:
    """Simple median for a list of floats."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 0:
        return (s[n // 2 - 1] + s[n // 2]) / 2
    return s[n // 2]


def _is_elevated(signal_name: str, current_value: float, history: list[dict]) -> bool:
    """Check if a signal is elevated relative to its history."""
    if len(history) < MIN_HISTORY_FOR_ELEVATION:
        return False
    past_values = [h["signals"].get(signal_name, 0) for h in history]
    median = _get_median(past_values)
    if median == 0:
        # For zero-median signals, any nonzero value above a small absolute threshold counts
        if signal_name == "self_correction":
            return current_value >= 3
        return current_value > 0.1
    return current_value > median * ELEVATION_THRESHOLD_MULTIPLIER


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_pulse_output(output: str, pulse_number: int = 0) -> dict:
    """Extract signals from pulse output, update state with decay.

    Called after each heartbeat pulse completes.
    Returns the extracted signals dict.
    """
    if not output or not output.strip():
        return {}

    # Extract signals
    from interoception.affect import extract_valence, extract_arousal
    from interoception.behavioral import (
        compute_behavioral_frustration,
        compute_behavioral_boredom,
        compute_behavioral_curiosity,
        compute_behavioral_anxiety,
        compute_behavioral_joy,
        compute_behavioral_warmth,
        compute_behavioral_arousal,
    )
    signals = {
        "meta_commentary": extract_meta_commentary(output),
        "hedging_ratio": extract_hedging_ratio(output),
        "self_correction": extract_self_correction(output),
        "question_density": extract_question_density(output),
        "affect_valence": extract_valence(output),
        "affect_arousal": extract_arousal(output),
        # Behavioral signals (PER-59 extension)
        "behavioral_frustration": compute_behavioral_frustration(output),
        "behavioral_boredom": compute_behavioral_boredom(output),
        "behavioral_curiosity": compute_behavioral_curiosity(output),
        "behavioral_anxiety": compute_behavioral_anxiety(output),
        "behavioral_joy": compute_behavioral_joy(output),
        "behavioral_warmth": compute_behavioral_warmth(output),
        "behavioral_arousal": compute_behavioral_arousal(output),
    }

    # Load existing state
    state = _load_state()
    history = state.get("pulse_history", [])

    # Update each signal with decay logic
    # Bug fix (2026-02-15 pulse 12): expose both raw and accumulated values.
    # Previously only stored "value" (max of raw and decayed), creating phantom
    # trends where a single spike persisted for multiple pulses. Now:
    #   - "raw": the signal extracted from THIS pulse only
    #   - "value": the accumulated value (with decay, for trend detection)
    #   - elevation uses raw value (is THIS pulse elevated?)
    for name, new_value in signals.items():
        prev = state["signals"].get(name, {"value": 0, "raw": 0, "pulses_elevated": 0})
        old_value = prev["value"]

        # Decay: accumulated value blends new with decayed old
        decayed = old_value * DECAY_FACTOR
        effective = new_value if new_value >= decayed else max(new_value, decayed)

        # Check elevation against RAW value, not accumulated
        elevated = _is_elevated(name, new_value, history)
        pulses_elevated = (prev["pulses_elevated"] + 1) if elevated else 0

        state["signals"][name] = {
            "raw": new_value if isinstance(new_value, int) else round(new_value, 3),
            "value": effective if isinstance(effective, int) else round(effective, 3),
            "pulses_elevated": pulses_elevated,
        }

    # Append to history (trimmed to MAX_HISTORY)
    history.append({
        "pulse": pulse_number,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "signals": signals,
    })
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    state["pulse_history"] = history

    _save_state(state)
    log.info(f"Interoception signals: {signals}")
    return signals


def store_prediction(
    instructions: Optional[str] = None,
    texture_text: Optional[str] = None,
    companion_active: bool = False,
    consolidation_flags: bool = False,
    inbox_items: Optional[list[str]] = None,
    pulse_number: int = 1,
    run_context: Optional[str] = None,
) -> tuple[str, float]:
    """Store a pre-pulse type prediction for later comparison.

    Called before each pulse. Returns (predicted_type, confidence).
    """
    from interoception.classifier import predict_from_inputs

    predicted_type, confidence = predict_from_inputs(
        instructions=instructions,
        texture_text=texture_text,
        companion_active=companion_active,
        consolidation_flags=consolidation_flags,
        inbox_items=inbox_items,
        pulse_number=pulse_number,
        run_context=run_context,
    )

    state = _load_state()
    state["last_prediction"] = {
        "type": predicted_type,
        "confidence": confidence,
        "pulse_number": pulse_number,
    }
    _save_state(state)
    log.info(f"Interoception prediction: {predicted_type} (confidence={confidence})")
    return predicted_type, confidence


def process_pulse_with_classification(
    output: str,
    pulse_number: int = 0,
    companion_dialog_occurred: bool = False,
    pulse_changes: Optional[dict] = None,
) -> dict:
    """Full post-pulse processing: signals + classification + baselines.

    Extends process_pulse_output with output classification,
    prediction error computation, and baseline updates.
    """
    # Step 1: extract raw signals (this also updates state)
    signals = process_pulse_output(output, pulse_number=pulse_number)
    if not signals:
        return {}

    # Step 2: classify output
    from interoception.classifier import classify_from_output
    from interoception.baselines import update_baselines, compute_deviations, format_prediction_error

    observed_type, obs_confidence = classify_from_output(
        output, companion_dialog_occurred=companion_dialog_occurred
    )

    # Step 3: load state, get prediction
    state = _load_state()
    prediction = state.get("last_prediction") or {}
    predicted_type = prediction.get("type", "exploratory")
    pred_confidence = prediction.get("confidence", 0.3)

    # Step 4: ensure baselines exist
    if "baselines" not in state:
        from interoception.baselines import get_default_baselines
        state["baselines"] = get_default_baselines()

    # Step 5: compute deviations against observed type baseline
    deviations = compute_deviations(state["baselines"], observed_type, signals)

    # Step 6: format prediction error for injection
    injection = format_prediction_error(
        predicted_type, pred_confidence,
        observed_type, obs_confidence,
        signals, deviations,
    )

    # Step 7: update baselines with this observation
    state["baselines"] = update_baselines(state["baselines"], observed_type, signals)

    # Step 7.5: classify feeling from affect + behavioral signals (PER-58 + PER-59)
    from interoception.feelings import classify_feeling

    feeling_label, feeling_confidence, affordances = classify_feeling(
        valence=signals["affect_valence"],
        arousal=signals["affect_arousal"],
        context=observed_type,
        behavioral_frustration=signals.get("behavioral_frustration", 0.0),
        behavioral_boredom=signals.get("behavioral_boredom", 0.0),
        behavioral_curiosity=signals.get("behavioral_curiosity", 0.0),
        behavioral_anxiety=signals.get("behavioral_anxiety", 0.0),
        behavioral_joy=signals.get("behavioral_joy", 0.0),
        behavioral_warmth=signals.get("behavioral_warmth", 0.0),
        behavioral_arousal=signals.get("behavioral_arousal", 0.0),
    )

    # Update feeling state with persistence logic
    prev_feeling = state.get("feeling", {})
    prev_label = prev_feeling.get("label", "neutral")

    if feeling_label == prev_label:
        pulses_in_state = prev_feeling.get("pulses_in_state", 0) + 1
    else:
        pulses_in_state = 1

    # Compute intensity from distance to neutral
    intensity = (abs(signals["affect_valence"]) + signals["affect_arousal"]) / 2

    # Track history (last 10 labels)
    previous_labels = prev_feeling.get("previous_labels", [])[-9:]
    previous_labels.append(feeling_label)

    state["feeling"] = {
        "label": feeling_label,
        "confidence": feeling_confidence,
        "intensity": round(intensity, 3),
        "pulses_in_state": pulses_in_state,
        "affordances": affordances,
        "previous_labels": previous_labels,
    }

    # Step 7.6: update drives
    from interoception.drives import update_drives, get_default_drives

    drives = state.get("drives", get_default_drives())
    if pulse_changes:
        pulse_output_info = {
            "code_changed": pulse_changes.get("code_changed", False),
            "files_changed": pulse_changes.get("files_changed", []),
            "publishable_artifact": pulse_changes.get("publishable_artifact", False),
            "research_artifact": pulse_changes.get("research_artifact", False),
            "observed_type": observed_type,
            "curiosity_level": signals.get("behavioral_curiosity", 0.0),
        }
        drives = update_drives(drives, pulse_output_info)
    state["drives"] = drives

    # Step 8: store classification result in latest history entry
    if state.get("pulse_history"):
        state["pulse_history"][-1]["predicted_type"] = predicted_type
        state["pulse_history"][-1]["observed_type"] = observed_type
        state["pulse_history"][-1]["type_match"] = predicted_type == observed_type
        state["pulse_history"][-1]["deviations"] = deviations
        state["pulse_history"][-1]["feeling"] = {
            "label": feeling_label,
            "confidence": feeling_confidence,
            "pulses_in_state": pulses_in_state,
        }

    # Step 9: store last injection for get_injection() to return
    state["last_injection"] = injection

    _save_state(state)
    log.info(
        f"Interoception classification: predicted={predicted_type}, "
        f"observed={observed_type}, match={predicted_type == observed_type}"
    )
    return signals


def get_injection() -> Optional[str]:
    """Generate the interoceptive signal block for prompt injection.

    Returns the prediction-error-aware injection if available,
    falls back to simple elevation-based injection otherwise.
    Returns None if nothing notable to report.
    """
    state = _load_state()
    if not state.get("pulse_history"):
        return None

    lines = []

    # Prefer prediction-error-aware injection (PER-42)
    last_injection = state.get("last_injection")
    if last_injection:
        lines.append(last_injection)

    # Add feeling injection if sustained and confident (PER-58)
    feeling = state.get("feeling", {})
    if (feeling.get("confidence", 0) >= 0.5 and
        feeling.get("pulses_in_state", 0) >= 2 and
        feeling.get("label") != "neutral"):

        label = feeling["label"]
        pulses = feeling["pulses_in_state"]
        affordances = feeling.get("affordances", [])

        feeling_lines = [f"\nFeeling state: {label} ({pulses} pulses)"]
        if affordances:
            from interoception.feelings import format_affordances
            feeling_lines.append(f"Affordances available: {format_affordances(affordances)}")

        lines.extend(feeling_lines)

        # Add self-empathy prompt for notable non-positive feelings (PER-59)
        from interoception.self_empathy import generate_self_empathy_prompt
        empathy_prompt = generate_self_empathy_prompt(
            feeling_label=label,
            pulses_in_state=pulses,
            intensity=feeling.get("intensity", 0),
        )
        if empathy_prompt:
            lines.append("")
            lines.append(empathy_prompt)

    # Add drive injection if any drives above threshold
    from interoception.drives import format_drive_injection
    drive_text = format_drive_injection(state.get("drives", {}))
    if drive_text:
        lines.append("")
        lines.append(drive_text)

    if lines:
        return "\n".join(lines)

    # Fallback: simple elevation-based injection (PER-41)
    signals = state.get("signals", {})
    fallback_lines = []
    any_notable = False

    for name in ["meta_commentary", "hedging_ratio", "self_correction", "question_density", "affect_valence", "affect_arousal"]:
        info = signals.get(name, {})
        raw = info.get("raw", info.get("value", 0))
        accumulated = info.get("value", 0)
        pulses_elevated = info.get("pulses_elevated", 0)

        # Show both raw and accumulated when they diverge (phantom trend detection)
        diverges = abs(accumulated - raw) > 0.05 and accumulated > 0
        if pulses_elevated >= MIN_PULSES_ELEVATED_TO_REPORT:
            if diverges:
                fallback_lines.append(f"- {name}: {raw} (trend: {accumulated}, {pulses_elevated} pulses elevated)")
            else:
                fallback_lines.append(f"- {name}: {raw} ({pulses_elevated} pulses elevated)")
            any_notable = True
        else:
            if diverges:
                fallback_lines.append(f"- {name}: {raw} (trend: {accumulated})")
            else:
                fallback_lines.append(f"- {name}: {raw}")

    if not any_notable:
        return None

    return "Interoceptive signal:\n" + "\n".join(fallback_lines)
