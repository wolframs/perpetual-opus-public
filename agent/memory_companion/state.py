"""
Decay state for memory companion injection tracking.

Tracks which queries/topics have been offered as pointers recently.
Decays at 0.85 per pulse to avoid repetitive suggestions.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("memory_companion.state")

STATE_FILE = Path(__file__).parent / "companion_state.json"
DECAY_FACTOR = 0.85
# Don't offer a pointer if its decay weight is above this
SUPPRESSION_THRESHOLD = 0.4


def _load_state() -> dict:
    """Load companion state from disk."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as e:
            log.warning(f"Failed to load companion state: {e}")
    return {
        "version": 1,
        "last_updated": None,
        "offered_queries": {},
        "pulse_count": 0,
    }


def _save_state(state: dict) -> None:
    """Persist state to disk."""
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def apply_decay() -> None:
    """Apply decay to all tracked queries. Called once per pulse."""
    state = _load_state()
    state["pulse_count"] = state.get("pulse_count", 0) + 1

    expired = []
    for query, info in state.get("offered_queries", {}).items():
        info["weight"] *= DECAY_FACTOR
        if info["weight"] < 0.05:
            expired.append(query)

    for q in expired:
        del state["offered_queries"][q]

    _save_state(state)


def is_suppressed(query: str) -> bool:
    """Check if a query should be suppressed (offered too recently)."""
    state = _load_state()
    info = state.get("offered_queries", {}).get(query)
    if info is None:
        return False
    return info.get("weight", 0) >= SUPPRESSION_THRESHOLD


def record_offered(queries: list[str]) -> None:
    """Record that these queries were offered as pointers."""
    state = _load_state()
    offered = state.setdefault("offered_queries", {})

    for q in queries:
        if q in offered:
            # Reinforce: set weight back to 1.0
            offered[q]["weight"] = 1.0
            offered[q]["count"] = offered[q].get("count", 0) + 1
            offered[q]["last_offered"] = datetime.now(timezone.utc).isoformat()
        else:
            offered[q] = {
                "weight": 1.0,
                "count": 1,
                "last_offered": datetime.now(timezone.utc).isoformat(),
            }

    _save_state(state)
