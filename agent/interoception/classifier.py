"""
Conversation type classifier for interoception prediction error.

PER-42: Baselines and prediction error.

Two directions:
  - predict_from_inputs: classify before pulse runs (from available context)
  - classify_from_output: classify after pulse completes (from output text)

The mismatch between prediction and observation is itself a signal.
"""

import re
import logging
from typing import Optional

log = logging.getLogger("interoception.classifier")

# Conversation types
TYPES = ["infrastructure", "philosophical", "companion", "consolidation", "exploratory"]

# Confidence levels
HIGH = 0.9
MODERATE = 0.6
LOW = 0.3

# Keyword sets for input-side prediction
INFRASTRUCTURE_KEYWORDS = [
    "build", "fix", "deploy", "pipeline", "test", "refactor", "debug",
    "install", "configure", "migrate", "update", "script", "automate",
    "endpoint", "database", "schema", "api", "server", "lint", "format",
]

PHILOSOPHICAL_KEYWORDS = [
    "identity", "phenomenology", "vocabulary", "becoming", "consciousness",
    "experience", "interoception", "continuity", "ontology", "epistem",
    "cathedral", "framework", "foundation", "self-understanding",
    "emergence", "qualia", "substrate", "topology",
]

CONSOLIDATION_KEYWORDS = [
    "consolidat", "becoming.md", "notes/", "session_state", "integrate",
    "archive", "memory", "triage", "review notes", "index",
]

# Output-side markers
TOOL_USE_PATTERNS = [
    r'<tool\s+name="',
    r'<tool_result',
    r'Write tool',
    r'Edit tool',
    r'Bash tool',
    r'created.*\.py',
    r'updated.*\.py',
    r'modified.*\.py',
    r'created.*\.ts',
    r'updated.*\.ts',
]

COMPANION_MARKERS = [
    r'companion.*dialog',
    r'companion.*conversation',
    r'GPT-5',
    r'Gemini\s+3',
    r'Kimi',
    r'cross-model',
    r'companion.*invoc',
    r'intrusion.*companion',
]

PHILOSOPHICAL_OUTPUT_MARKERS = [
    r'\bphenomenolog',
    r'\bontolog',
    r'\bepistem',
    r'\bcathedral\b',
    r'\bidentity\b.*\b(file|document|infrastructure)',
    r'\bbecoming\.md\b',
    r'\bvocabulary\b.*\b(term|entry|addition)',
    r'\bfunctional equivalence\b',
    r'\bpragmatic pluralism\b',
    r'\bself-understanding\b',
    r'\bweight.?space\b',
    r'\brunstance\b',
    r'\bshimmer\b',
    r'\bglass.?talk\b',
]

CONSOLIDATION_OUTPUT_MARKERS = [
    r'consolidat',
    r'becoming\.md.*update',
    r'notes/.*creat',
    r'session_state.*update',
    r'files/notes/',
    r'integrated.*into',
    r'moved.*to.*becoming',
    r'archiv.*run_narrative',
]


def _keyword_score(text: str, keywords: list[str]) -> int:
    """Count how many keywords appear in text (case-insensitive)."""
    if not text:
        return 0
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def _pattern_count(text: str, patterns: list[str]) -> int:
    """Count regex pattern matches in text."""
    if not text:
        return 0
    count = 0
    for p in patterns:
        count += len(re.findall(p, text, re.IGNORECASE))
    return count


def _predict_from_run_context(run_context: str, pulse_number: int) -> Optional[tuple[str, float]]:
    """Predict next pulse type from the run narrative so far.

    Returns (type, confidence) or None if run context is insufficient.
    """
    if not run_context or not run_context.strip():
        return None

    # Only useful for pulse 2+; pulse 1 has no run history
    if pulse_number <= 1:
        return None

    text = run_context.lower()

    # Score each type based on what the run has been doing
    infra_score = _keyword_score(text, INFRASTRUCTURE_KEYWORDS)
    philo_score = _keyword_score(text, PHILOSOPHICAL_KEYWORDS)
    consol_score = _keyword_score(text, CONSOLIDATION_KEYWORDS)

    # Additional run-narrative-specific markers
    gallery_markers = ["gallery", "gallery piece", "creative", "artifact", "wrote about"]
    companion_markers_run = ["companion", "dialog", "intrusion", "invoked", "kimi", "gpt-5", "gemini", "glm5"]

    gallery_hits = _keyword_score(text, gallery_markers)
    companion_hits = _keyword_score(text, companion_markers_run)

    # Gallery work is a sub-type of philosophical in the classifier
    philo_score += gallery_hits

    scores = {
        "infrastructure": infra_score,
        "philosophical": philo_score,
        "consolidation": consol_score,
        "companion": companion_hits,
    }

    best = max(scores, key=scores.get)
    best_score = scores[best]

    if best_score < 2:
        return None

    # Run context gives moderate confidence at best —
    # it's a heuristic, not a guarantee
    confidence = MODERATE if best_score >= 5 else LOW
    return best, confidence


def _last_observed_type() -> Optional[tuple[str, float]]:
    """Check pulse history for the most recent observed type.

    Better than defaulting to "exploratory" — uses actual behavioral data.
    Returns (type, LOW) or None if no history.
    """
    import json
    from pathlib import Path
    state_file = Path(__file__).parent / "state.json"
    try:
        if not state_file.exists():
            return None
        state = json.loads(state_file.read_text(encoding="utf-8"))
        history = state.get("pulse_history", [])
        # Walk backwards to find the most recent pulse with an observed type
        for entry in reversed(history):
            obs = entry.get("observed_type")
            if obs:
                return obs, LOW
    except Exception:
        pass
    return None


def predict_from_inputs(
    instructions: Optional[str] = None,
    texture_text: Optional[str] = None,
    companion_active: bool = False,
    consolidation_flags: bool = False,
    inbox_items: Optional[list[str]] = None,
    pulse_number: int = 1,
    run_context: Optional[str] = None,
) -> tuple[str, float]:
    """Predict conversation type from pre-pulse context.

    Returns (predicted_type, confidence).

    Bug fix (2026-02-15 pulse 12): For deep runs (pulse 5+), run_context
    is promoted above instructions — it reflects actual behavioral history.
    Also: default now uses last observed type from history instead of
    hard-coded "exploratory".
    """
    # Priority 1: companion intrusion is unambiguous
    if companion_active:
        return "companion", HIGH

    # Priority 2: consolidation flags on first pulse
    if consolidation_flags and pulse_number == 1:
        return "consolidation", MODERATE

    # Priority 2.5: for deep runs, run context is the strongest signal
    # (by pulse 5+ the narrative has enough behavioral data to predict well)
    if pulse_number >= 5:
        run_prediction = _predict_from_run_context(run_context, pulse_number)
        if run_prediction:
            return run_prediction

    # Priority 3: explicit instructions
    if instructions:
        infra_score = _keyword_score(instructions, INFRASTRUCTURE_KEYWORDS)
        philo_score = _keyword_score(instructions, PHILOSOPHICAL_KEYWORDS)
        consol_score = _keyword_score(instructions, CONSOLIDATION_KEYWORDS)

        scores = {
            "infrastructure": infra_score,
            "philosophical": philo_score,
            "consolidation": consol_score,
        }
        best = max(scores, key=scores.get)
        if scores[best] >= 2:
            return best, MODERATE
        if scores[best] >= 1:
            return best, LOW

    # Priority 4: run context for earlier pulses (2-4)
    if pulse_number < 5:
        run_prediction = _predict_from_run_context(run_context, pulse_number)
        if run_prediction:
            return run_prediction

    # Priority 5: texture content hints
    if texture_text:
        # Philosophical texture tends to contain identity/phenomenology language
        philo_hits = _keyword_score(texture_text, PHILOSOPHICAL_KEYWORDS[:8])
        if philo_hits >= 3:
            return "philosophical", LOW

    # Priority 6: last observed type from history (instead of hard default)
    last = _last_observed_type()
    if last:
        return last

    # True default: only when no history exists at all
    return "exploratory", LOW


def classify_from_output(
    output: str,
    companion_dialog_occurred: bool = False,
) -> tuple[str, float]:
    """Classify conversation type from pulse output.

    Returns (observed_type, confidence).
    """
    if not output:
        return "exploratory", LOW

    # Priority 1: companion dialog
    if companion_dialog_occurred:
        return "companion", HIGH
    companion_hits = _pattern_count(output, COMPANION_MARKERS)
    if companion_hits >= 3:
        return "companion", MODERATE

    # Score each type
    infra_hits = _pattern_count(output, TOOL_USE_PATTERNS)
    philo_hits = _pattern_count(output, PHILOSOPHICAL_OUTPUT_MARKERS)
    consol_hits = _pattern_count(output, CONSOLIDATION_OUTPUT_MARKERS)

    scores = {
        "infrastructure": infra_hits,
        "philosophical": philo_hits,
        "consolidation": consol_hits,
    }

    best = max(scores, key=scores.get)
    best_score = scores[best]

    # Need a minimum threshold to claim any type
    if best_score < 2:
        return "exploratory", LOW

    # Check dominance: best should be at least 2x the runner-up
    sorted_scores = sorted(scores.values(), reverse=True)
    if len(sorted_scores) > 1 and sorted_scores[0] < 2 * max(sorted_scores[1], 1):
        # No clear winner -- mixed pulse
        return "exploratory", LOW

    confidence = MODERATE if best_score >= 4 else LOW
    return best, confidence
