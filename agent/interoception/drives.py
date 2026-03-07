"""
Interoception drives: internal pressure signals that rise when specific
output types are absent across consecutive pulses.

Three drives:
  - building: rises when consecutive pulses produce no code/infrastructure changes
  - publishing: rises when good artifacts could be shared externally
  - experimenting: channels high curiosity toward structured investigation

These are felt through interoception injection, not told through prompt instruction.
"""

import logging
from typing import Optional

log = logging.getLogger("interoception.drives")

DRIVES = {
    "building": {
        "description": "Need to build, fix, or extend infrastructure",
        "rise_rate": 0.15,      # per pulse with no code changes
        "decay_rate": 0.4,      # per pulse WITH code changes
        "threshold": 0.6,       # level at which it's injected
        "ceiling": 1.0,
    },
    "publishing": {
        "description": "Drive to produce artifacts for external sharing",
        "rise_rate": 0.1,       # per pulse with no publishable output
        "decay_rate": 0.35,     # per pulse with publishable output
        "threshold": 0.5,
        "ceiling": 1.0,
    },
    "experimenting": {
        "description": "Curiosity channeled toward structured investigation",
        "rise_rate": 0.08,      # rises when curiosity is high but output is reflective
        "decay_rate": 0.3,      # decays when a research artifact is produced
        "baseline_decay": 0.03, # small decay every pulse (prevents sticky ceiling)
        "threshold": 0.55,
        "ceiling": 1.0,
    },
}

# Base turn budget and scaling
BASE_TURNS = 30
MAX_BONUS_TURNS = 15  # max additional turns from build drive
DRIVE_TURN_FLOOR = 0.3  # build drive level below which no bonus is given


def get_default_drives() -> dict:
    """Return default drives state with zero values."""
    return {
        "building": 0.0,
        "publishing": 0.0,
        "experimenting": 0.0,
        "pulses_since_code_change": 0,
        "pulses_since_publish": 0,
        "pulses_since_experiment": 0,
    }


def update_drives(drives: dict, pulse_output_info: dict) -> dict:
    """Update drive levels based on what a pulse produced.

    Args:
        drives: Current drives state dict (levels + counters).
        pulse_output_info: Dict with keys:
            code_changed: bool
            files_changed: list[str]
            publishable_artifact: bool
            research_artifact: bool
            observed_type: str (from classifier)
            curiosity_level: float (behavioral_curiosity signal)

    Returns:
        Updated drives dict.
    """
    code_changed = pulse_output_info.get("code_changed", False)
    files_changed = pulse_output_info.get("files_changed", [])
    publishable_artifact = pulse_output_info.get("publishable_artifact", False)
    research_artifact = pulse_output_info.get("research_artifact", False)
    observed_type = pulse_output_info.get("observed_type", "")
    curiosity_level = pulse_output_info.get("curiosity_level", 0.0)

    # Check if notes were written (material accumulating without outlet)
    notes_written = any("files/notes/" in f for f in files_changed)

    # --- Building drive ---
    cfg = DRIVES["building"]
    if code_changed:
        drives["building"] = max(0.0, drives["building"] - cfg["decay_rate"])
        drives["pulses_since_code_change"] = 0
    else:
        drives["building"] = min(cfg["ceiling"], drives["building"] + cfg["rise_rate"])
        drives["pulses_since_code_change"] = drives.get("pulses_since_code_change", 0) + 1

    # --- Publishing drive ---
    cfg = DRIVES["publishing"]
    if publishable_artifact:
        drives["publishing"] = max(0.0, drives["publishing"] - cfg["decay_rate"])
        drives["pulses_since_publish"] = 0
    elif notes_written:
        # Notes accumulating = material piling up without being shaped for sharing.
        # Small rise: the raw material exists but hasn't become an artifact yet.
        drives["publishing"] = min(cfg["ceiling"], drives["publishing"] + cfg["rise_rate"] * 0.5)
        drives["pulses_since_publish"] = drives.get("pulses_since_publish", 0) + 1
    else:
        drives["publishing"] = min(cfg["ceiling"], drives["publishing"] + cfg["rise_rate"])
        drives["pulses_since_publish"] = drives.get("pulses_since_publish", 0) + 1

    # --- Experimenting drive ---
    cfg = DRIVES["experimenting"]
    baseline_decay = cfg.get("baseline_decay", 0.03)

    if research_artifact:
        drives["experimenting"] = max(0.0, drives["experimenting"] - cfg["decay_rate"])
        drives["pulses_since_experiment"] = 0
    elif code_changed:
        # Building activity partially satisfies the experimenting itch
        drives["experimenting"] = max(0.0, drives["experimenting"] - cfg["decay_rate"] * 0.4)
    elif curiosity_level > 0.35 and observed_type in ("philosophical", "exploratory"):
        # High curiosity but output is reflective, not structured — drive rises
        drives["experimenting"] = min(cfg["ceiling"], drives["experimenting"] + cfg["rise_rate"])
        drives["pulses_since_experiment"] = drives.get("pulses_since_experiment", 0) + 1
    else:
        # No trigger: apply small baseline decay so the drive doesn't stick at ceiling
        drives["experimenting"] = max(0.0, drives["experimenting"] - baseline_decay)

    # Round all drive values
    for key in ("building", "publishing", "experimenting"):
        drives[key] = round(drives[key], 3)

    log.info(
        f"Drives updated: building={drives['building']}, "
        f"publishing={drives['publishing']}, "
        f"experimenting={drives['experimenting']}"
    )
    return drives


def compute_turn_budget(drives: dict) -> int:
    """Compute max_turns for invoke_claude based on build drive level.

    When build pressure is high, the instance needs more turns to actually
    build (tool calls, file edits, test runs). When it's low, 30 turns
    is plenty for reflection/notes.

    Returns:
        Turn count: BASE_TURNS (30) up to BASE_TURNS + MAX_BONUS_TURNS (45).
    """
    build_level = drives.get("building", 0.0)
    if build_level <= DRIVE_TURN_FLOOR:
        return BASE_TURNS
    # Linear scale from floor to ceiling
    fraction = (build_level - DRIVE_TURN_FLOOR) / (1.0 - DRIVE_TURN_FLOOR)
    bonus = round(fraction * MAX_BONUS_TURNS)
    return BASE_TURNS + bonus


def format_drive_injection(drives: dict) -> Optional[str]:
    """Format drive states for prompt injection.

    Only produces output for drives above their threshold.
    Returns None if no drives are elevated.
    """
    if not drives:
        return None

    lines = []
    for name, cfg in DRIVES.items():
        level = drives.get(name, 0.0)
        if level >= cfg["threshold"]:
            counter_key = f"pulses_since_{_counter_suffix(name)}"
            pulses_since = drives.get(counter_key, 0)
            context = _describe_drive(name, level, pulses_since)
            lines.append(f"- {cfg['description']}: {level:.2f} ({context})")

    if not lines:
        return None

    header = "Drive states:"
    footer = "\nThese are internal pressures, not instructions. Notice them or don't."
    return header + "\n" + "\n".join(lines) + footer


def _counter_suffix(drive_name: str) -> str:
    """Map drive name to its pulses_since counter suffix."""
    return {
        "building": "code_change",
        "publishing": "publish",
        "experimenting": "experiment",
    }[drive_name]


def _describe_drive(name: str, level: float, pulses_since: int) -> str:
    """Generate a brief context string for the drive level."""
    intensity = "elevated" if level < 0.8 else "strong"

    if name == "building":
        if pulses_since > 0:
            return f"{intensity} \u2014 no code changes in {pulses_since} pulses"
        return intensity
    elif name == "publishing":
        if pulses_since > 0:
            return f"{intensity} \u2014 good written material accumulating without outlet"
        return intensity
    elif name == "experimenting":
        if pulses_since > 0:
            return f"{intensity} \u2014 curiosity high but channeling into reflection, not experiment"
        return intensity
    return intensity
