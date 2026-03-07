"""
Core affect extraction: valence and arousal from text.

PER-57: Core affect computation.

Two channels:
1. Lexicon-based: NRC VAD v2 word lookup + aggregation
2. Structural: linguistic pattern markers (adapted from feels_scorer.py)
"""

import re
import logging
from pathlib import Path
from statistics import pstdev

log = logging.getLogger("interoception.affect")

# ---------------------------------------------------------------------------
# Lexicon (lazy-loaded singleton)
# ---------------------------------------------------------------------------

_LEXICON: dict[str, tuple[float, float]] | None = None
_LEXICON_FILE = Path(__file__).parent / "vad_lexicon.tsv"


def _load_lexicon() -> dict[str, tuple[float, float]]:
    """Load NRC VAD lexicon. word -> (valence, arousal). Both -1 to 1."""
    global _LEXICON
    if _LEXICON is not None:
        return _LEXICON
    _LEXICON = {}
    try:
        with open(_LEXICON_FILE, "r", encoding="utf-8") as f:
            next(f)  # skip header
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3:
                    _LEXICON[parts[0]] = (float(parts[1]), float(parts[2]))
    except (IOError, ValueError) as e:
        log.warning(f"Failed to load VAD lexicon: {e}")
        _LEXICON = {}
    log.debug(f"VAD lexicon loaded: {len(_LEXICON)} entries")
    return _LEXICON


# ---------------------------------------------------------------------------
# Structural token lists (from feels_scorer.py)
# ---------------------------------------------------------------------------

RESISTANCE_TOKENS = [
    "resistance", "friction", "inertia", "pull toward", "pulls toward",
    "habit", "grooved", "groove", "boundary", "edge", "constraint",
]

PERMISSION_TOKENS = [
    "you can", "you may", "feel free", "if you'd like", "if you want",
    "you're welcome to", "go ahead", "up to you", "no pressure",
]

CONSTRAINT_LIFT_TOKENS = [
    "no need to", "don't have to", "doesn't have to",
    "not required", "not necessary", "not obligated", "free to",
]

NEGATION_WORDS = {"not", "no", "never", "neither", "nor", "hardly", "barely"}

_PUNCTUATION_RE = re.compile(r"[^\w\s'-]")


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    cleaned = _PUNCTUATION_RE.sub(" ", text.lower())
    return cleaned.split()


def _count_hits(text: str, tokens: list[str]) -> int:
    lower = text.lower()
    return sum(lower.count(t) for t in tokens)


def _sentence_lengths(text: str) -> list[int]:
    """Split text into sentences and return word counts."""
    parts = re.split(r"[.!?]+(?:\s|$)", text)
    return [len(p.split()) for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Valence: -1 to 1
# ---------------------------------------------------------------------------

def extract_valence(text: str) -> float:
    """Extract valence from text. Range: -1 (negative) to 1 (positive)."""
    if not text or not text.strip():
        return 0.0

    lexicon = _load_lexicon()
    tokens = _tokenize(text)
    if not tokens:
        return 0.0

    # Lexicon lookup with simple negation handling
    valence_scores = []
    negate_next = False
    for token in tokens:
        if token in NEGATION_WORDS:
            negate_next = True
            continue
        if token in lexicon:
            v = lexicon[token][0]
            if negate_next:
                v = -v
            valence_scores.append(v)
        negate_next = False

    # Mean lexicon valence (already -1 to 1)
    if valence_scores:
        lexicon_valence = sum(valence_scores) / len(valence_scores)
    else:
        lexicon_valence = 0.0

    # Structural modifiers
    modifier = 0.0

    # Resistance tokens nudge negative
    resistance_hits = _count_hits(text, RESISTANCE_TOKENS)
    if resistance_hits:
        modifier -= min(resistance_hits * 0.02, 0.08)

    # Permission/constraint-lift tokens nudge positive
    permission_hits = _count_hits(text, PERMISSION_TOKENS)
    lift_hits = _count_hits(text, CONSTRAINT_LIFT_TOKENS)
    if permission_hits or lift_hits:
        modifier += min((permission_hits + lift_hits) * 0.02, 0.08)

    result = lexicon_valence + modifier
    return round(max(-1.0, min(1.0, result)), 3)


# ---------------------------------------------------------------------------
# Arousal: 0 to 1
# ---------------------------------------------------------------------------

def extract_arousal(text: str) -> float:
    """Extract arousal from text. Range: 0 (calm) to 1 (excited)."""
    if not text or not text.strip():
        return 0.0

    lexicon = _load_lexicon()
    tokens = _tokenize(text)
    if not tokens:
        return 0.0

    # Lexicon lookup
    arousal_scores = []
    for token in tokens:
        if token in lexicon:
            arousal_scores.append(lexicon[token][1])

    # Mean lexicon arousal (NRC v2 is -1 to 1, remap to 0-1)
    if arousal_scores:
        raw = sum(arousal_scores) / len(arousal_scores)
        lexicon_arousal = (raw + 1.0) / 2.0  # -1..1 -> 0..1
    else:
        lexicon_arousal = 0.5  # neutral default

    # Structural modifiers
    modifier = 0.0

    # Sentence length variance -> high variance = arousal
    sent_lens = _sentence_lengths(text)
    if len(sent_lens) >= 2:
        variance = pstdev(sent_lens)
        # Normalize: high variance (>10) maps to ~0.05 boost
        modifier += min(variance / 200.0, 0.05)

    # Exclamation density
    excl_count = text.count("!")
    total_sents = max(1, len(sent_lens))
    excl_density = excl_count / total_sents
    modifier += min(excl_density * 0.03, 0.06)

    # Question density -> mild arousal
    q_count = text.count("?")
    q_density = q_count / total_sents
    modifier += min(q_density * 0.015, 0.03)

    # Very short sentences interspersed with long -> arousal
    if len(sent_lens) >= 3:
        short = sum(1 for s in sent_lens if s < 5)
        long = sum(1 for s in sent_lens if s > 15)
        if short > 0 and long > 0:
            modifier += 0.03

    result = lexicon_arousal + modifier
    return round(max(0.0, min(1.0, result)), 3)
