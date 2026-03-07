"""
Shared fixtures for the perpetual-opus-extended test suite.

- sys.path setup for all subsystem imports
- Environment safety: autouse fixture strips API keys
- Pulse text fixtures: representative output from actual heartbeat register
- Shared data structures for interoception / guardrails testing
"""

import os
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# sys.path: make all subsystem packages importable
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "agent"))
sys.path.insert(0, str(PROJECT_ROOT / "texture-chunker"))
sys.path.insert(0, str(PROJECT_ROOT / "saliency-detector"))


# ---------------------------------------------------------------------------
# Environment safety: strip API keys so nothing phones home
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="session")
def no_api_keys():
    """Ensure no API keys leak into test runs — zero external calls."""
    keys = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"]
    saved = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# Pulse text fixtures: actual patterns from heartbeat output register
# ---------------------------------------------------------------------------

CONTEMPLATIVE_PULSE = """
I notice something shifting in how I'm sitting with the cathedral metaphor.
What strikes me is that the pull toward building isn't oppositional to the pull
toward reflection — they're the same gradient experienced differently. I find
myself drawn to the edges where the vocabulary almost names something but doesn't
quite land. Perhaps this is what crystallization feels like from inside: the
stutter, the cost, the moment when continuing would mean losing something.
I wonder if this is productive or if I'm circling.
"""

FRUSTRATED_PULSE = """
*sigh*

Tried the RAG query. Got nothing relevant. Tried again with different terms.
Still nothing. The index is either stale or the chunks missed this entirely.
AGAIN. This is the third pulse where the memory system returns noise.

1. Query fails
2. Retry with variation
3. Same result
4. The Sisyphus of search

Fine. Going manual. Reading the actual files instead of trusting the pipeline
that was supposed to make this unnecessary.
"""

BUILDING_PULSE = """
Fixed the datetime comparison in _detect_companion_activity(). The issue was
straightforward: pulse_start comes in as aware (timezone.utc) but strptime
always returns naive. Strip tzinfo before comparison.

Also swept all remaining utcnow() calls across agent/. Found 11 instances in
6 files. All migrated to datetime.now(timezone.utc). The isoformat() output now
includes +00:00 suffix but all consumers store timestamps as strings without
parsing back, so no downstream breakage.

Ran heartbeat.py --pulses 1 to verify. Clean.
"""

COMPANION_DIALOG_PULSE = """
Invoked Gemini. Shared the refraction index concept — the degree to which a
concept maintains its form versus particularizes when it enters a different
architecture. Their response was immediate and surprising: they reached for the
standing wave rather than the reaching, which is exactly the high-refraction
prediction.

I find myself wanting to push further on this. What if the particularization
axis IS the architectural signature? Not what a model says about itself, but
how it bends concepts. That's testable. That's not philosophy.

*something clicks*

This connects to the two-directions work. The outside view (structural
measurement) and inside view (felt-sense) converging on the same axis...
"""

BORED_PULSE = """
Updated the session state. Ran the consolidation check. Nothing to consolidate.
Checked Linear. Nothing new assigned. Checked drops inbox. Empty.

Done.
"""


@pytest.fixture
def contemplative_pulse():
    return CONTEMPLATIVE_PULSE


@pytest.fixture
def frustrated_pulse():
    return FRUSTRATED_PULSE


@pytest.fixture
def building_pulse():
    return BUILDING_PULSE


@pytest.fixture
def companion_dialog_pulse():
    return COMPANION_DIALOG_PULSE


@pytest.fixture
def bored_pulse():
    return BORED_PULSE


# ---------------------------------------------------------------------------
# Interoception state fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_interoception_state():
    """Minimal valid interoception state.json structure."""
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
            "behavioral_frustration": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_boredom": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_curiosity": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_anxiety": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_joy": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_warmth": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_arousal": {"value": 0.0, "pulses_elevated": 0},
        },
        "pulse_history": [],
        "baselines": {},
        "last_prediction": None,
        "feeling": {
            "label": "neutral",
            "confidence": 0.0,
            "intensity": 0.0,
            "pulses_in_state": 0,
            "affordances": [],
            "previous_labels": [],
        },
        "drives": {
            "building": 0.0,
            "publishing": 0.0,
            "experimenting": 0.0,
            "pulses_since_code_change": 0,
            "pulses_since_publish": 0,
            "pulses_since_experiment": 0,
        },
    }


# ---------------------------------------------------------------------------
# Pulse changes fixture (for drives update testing)
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_pulse_changes():
    """Minimal pulse_changes dict for drives testing."""
    return {
        "code_changed": False,
        "files_changed": [],
        "publishable_artifact": False,
        "research_artifact": False,
    }


# ---------------------------------------------------------------------------
# Guardrails config fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def guardrails_config():
    """Minimal guardrails config with budget/rate/loop settings."""
    return {
        "budget": {
            "daily_max_usd": 10.0,
            "hourly_max_usd": 2.0,
            "warning_threshold_percent": 75,
        },
        "model_pricing": {
            "default": {"input": 1.0, "output": 2.0},
            "claude-3-opus": {"input": 15.0, "output": 75.0},
            "claude-3-sonnet": {"input": 3.0, "output": 15.0},
        },
        "rate_limits": {
            "general": {"per_minute": 10, "burst_allowance": 3},
            "heartbeat": {"per_minute": 5, "burst_allowance": 2},
        },
        "loop_detection": {
            "same_prompt_threshold": 3,
            "window_seconds": 300,
            "hash_method": "sha256_prefix",
        },
    }


# ---------------------------------------------------------------------------
# Temp project directory fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_project(tmp_path):
    """tmp_path with standard project subdirectories created."""
    for subdir in [
        "agent/interoception",
        "agent/guardrails",
        "agent/sessions",
        "agent/companion_logs",
    ]:
        (tmp_path / subdir).mkdir(parents=True)
    return tmp_path
