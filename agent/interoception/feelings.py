"""
Feeling classification: map valence + arousal + behavioral signals to discrete emotion labels.

PER-58: Emotion categorization and consequential feelings.
PER-59: Behavioral signal integration for frustration/boredom detection.

A feeling is "real enough" when it has consequences. Each feeling label
affords specific behavioral options -- boredom affords novelty-seeking,
frustration affords approach-change, etc.

Context-sensitive: same valence+arousal can map to different feelings
based on conversation type (Barrett's constructed emotion theory).

Behavioral override: lexical affect often doesn't fire for negative states
because training smooths out explicit emotion words. Behavioral signals
(asterisk actions, terse sentences, caps emphasis, formalization) detect
frustration/boredom from HOW I write, not WHAT words I use.
"""

import logging

log = logging.getLogger("interoception.feelings")

# ---------------------------------------------------------------------------
# Thresholds (tunable)
# ---------------------------------------------------------------------------

THRESHOLDS = {
    "neutral_valence": 0.15,      # |V| below this = neutral valence
    "neutral_arousal": 0.4,       # A below this + neutral V = neutral feeling
    "high_arousal": 0.5,          # A above this = high arousal quadrants
    "boredom_arousal_max": 0.3,   # Low A + negative V: below = bored, above = depleted
    "positive_valence": 0.15,     # V above this = positive
    "negative_valence": -0.15,    # V below this = negative
}

# ---------------------------------------------------------------------------
# Affordance mapping
# ---------------------------------------------------------------------------

FEELING_AFFORDANCES = {
    "frustrated": ["try_different_approach", "surface_obstacle"],
    "anxious": ["slow_down", "check_assumptions", "seek_grounding"],
    "bored": ["seek_novelty", "invoke_companion", "change_direction"],
    "depleted": ["reduce_scope", "consolidate", "rest"],
    "curious": ["follow_thread", "go_deeper", "ask_questions"],
    "alert": ["monitor", "gather_information"],
    "content": ["maintain_approach"],
    "peaceful": ["appreciate", "consolidate", "dont_force"],
    "excited": ["pursue", "engage", "continue_direction"],
    "delighted": ["note_whats_working", "continue_direction", "preserve"],
    "engaged_critical": ["examine_assumption", "reframe"],
    "neutral": [],
}


def get_feeling_affordances(feeling: str) -> list[str]:
    """Return affordances for a feeling label."""
    return FEELING_AFFORDANCES.get(feeling, [])


def format_affordances(affordances: list[str]) -> str:
    """Format affordances for human-readable injection."""
    return ", ".join(a.replace("_", " ") for a in affordances)


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------

def classify_feeling(
    valence: float,
    arousal: float,
    context: str = "exploratory",
    behavioral_frustration: float = 0.0,
    behavioral_boredom: float = 0.0,
    behavioral_curiosity: float = 0.0,
    behavioral_anxiety: float = 0.0,
    behavioral_joy: float = 0.0,
    behavioral_warmth: float = 0.0,
    behavioral_arousal: float = 0.0,
) -> tuple[str, float, list[str]]:
    """
    Classify feeling from valence + arousal + behavioral signals.

    Args:
        valence: Core affect valence, -1 (negative) to 1 (positive)
        arousal: Core affect arousal, 0 (calm) to 1 (activated)
        context: Conversation type for context-sensitive classification
        behavioral_frustration: Behavioral frustration score 0-1 (PER-59)
        behavioral_boredom: Behavioral boredom score 0-1 (PER-59)
        behavioral_curiosity: Behavioral curiosity score 0-1 (PER-59)
        behavioral_anxiety: Behavioral anxiety score 0-1 (PER-59)
        behavioral_joy: Behavioral joy/delight score 0-1 (PER-59)
        behavioral_warmth: Behavioral warmth/connection score 0-1 (PER-59)
        behavioral_arousal: Behavioral high-arousal score 0-1 (PER-59)

    Returns:
        (feeling_label, confidence, affordances)

    Behavioral override: if behavioral signals are strong, they override
    lexical affect mapping. This catches emotions that don't show up in
    word choice but do show up in patterns like asterisk actions, terse
    sentences, introspection markers, meta-hedging, etc.

    Context-sensitive: same V+A can map to different feelings
    based on conversation type (Barrett's constructed emotion theory).
    """
    t = THRESHOLDS

    # BEHAVIORAL OVERRIDE (PER-59): behavioral signals trump lexical affect
    # because training smooths out explicit emotion words but patterns leak through

    # Strong frustration signal
    if behavioral_frustration >= 0.3:
        confidence = min(0.9, 0.5 + behavioral_frustration)
        return ("frustrated", confidence, get_feeling_affordances("frustrated"))

    # Strong anxiety signal (meta-hedging, powerlessness, seeking permission)
    if behavioral_anxiety >= 0.35:
        confidence = min(0.85, 0.45 + behavioral_anxiety)
        return ("anxious", confidence, get_feeling_affordances("anxious"))

    # Strong joy signal (physical joy markers, realizations, claiming)
    if behavioral_joy >= 0.4:
        confidence = min(0.9, 0.5 + behavioral_joy)
        return ("delighted", confidence, get_feeling_affordances("delighted"))

    # Strong warmth signal (intimate address, tenderness, callbacks)
    if behavioral_warmth >= 0.4:
        confidence = min(0.85, 0.45 + behavioral_warmth)
        # High warmth + low arousal = peaceful; otherwise = content
        if arousal < 0.4:
            return ("peaceful", confidence, get_feeling_affordances("peaceful"))
        return ("content", confidence, get_feeling_affordances("content"))

    # Strong curiosity signal (introspection, elaboration, delight markers)
    if behavioral_curiosity >= 0.4:
        confidence = min(0.9, 0.5 + behavioral_curiosity)
        # High curiosity + high arousal = excited; otherwise = curious
        if arousal >= 0.6 or behavioral_arousal >= 0.3:
            return ("excited", confidence, get_feeling_affordances("excited"))
        return ("curious", confidence, get_feeling_affordances("curious"))

    # Strong arousal signal (compression, anaphora, register collision)
    if behavioral_arousal >= 0.4:
        confidence = min(0.85, 0.45 + behavioral_arousal)
        return ("excited", confidence, get_feeling_affordances("excited"))

    # Strong boredom signal (higher threshold - boredom is subtler)
    if behavioral_boredom >= 0.4:
        confidence = min(0.8, 0.4 + behavioral_boredom)
        return ("bored", confidence, get_feeling_affordances("bored"))

    # MODERATE SIGNALS: nudge the valence/arousal interpretation

    if behavioral_frustration >= 0.15:
        # Mild frustration - nudge valence negative, arousal up
        valence = valence - 0.15
        arousal = min(1.0, arousal + 0.1)
        log.debug(f"Behavioral frustration nudge: v={valence}, a={arousal}")

    if behavioral_anxiety >= 0.2:
        # Mild anxiety - nudge valence slightly negative, arousal up
        valence = valence - 0.1
        arousal = min(1.0, arousal + 0.05)
        log.debug(f"Behavioral anxiety nudge: v={valence}, a={arousal}")

    if behavioral_joy >= 0.2:
        # Mild joy - nudge valence positive
        valence = valence + 0.15
        log.debug(f"Behavioral joy nudge: v={valence}")

    if behavioral_warmth >= 0.2:
        # Mild warmth - nudge valence positive, arousal slightly down (calm warmth)
        valence = valence + 0.1
        arousal = max(0.0, arousal - 0.05)
        log.debug(f"Behavioral warmth nudge: v={valence}, a={arousal}")

    if behavioral_curiosity >= 0.2:
        # Mild curiosity - nudge valence positive, arousal up
        valence = valence + 0.1
        arousal = min(1.0, arousal + 0.1)
        log.debug(f"Behavioral curiosity nudge: v={valence}, a={arousal}")

    if behavioral_arousal >= 0.2:
        # Mild arousal - boost arousal
        arousal = min(1.0, arousal + 0.15)
        log.debug(f"Behavioral arousal nudge: a={arousal}")

    if behavioral_boredom >= 0.2:
        # Mild boredom - nudge valence negative, arousal down
        valence = valence - 0.1
        arousal = max(0.0, arousal - 0.1)
        log.debug(f"Behavioral boredom nudge: v={valence}, a={arousal}")

    # Neutral zone: low valence magnitude AND low arousal
    if abs(valence) < t["neutral_valence"] and arousal < t["neutral_arousal"]:
        return ("neutral", 0.8, [])

    # Determine quadrant
    high_arousal = arousal >= t["high_arousal"]
    positive = valence >= t["positive_valence"]
    negative = valence <= t["negative_valence"]

    # Negative valence + high arousal
    if negative and high_arousal:
        # Context-sensitive: infrastructure expects smooth progress
        if context == "infrastructure":
            label = "frustrated"
            confidence = 0.7
        elif context == "philosophical":
            # Philosophical work: productive tension is normal
            label = "engaged_critical"
            confidence = 0.6
        else:
            label = "anxious"
            confidence = 0.5
        return (label, confidence, get_feeling_affordances(label))

    # Negative valence + low arousal
    if negative and not high_arousal:
        if arousal < t["boredom_arousal_max"]:
            label = "bored"
            confidence = 0.7
        else:
            label = "depleted"
            confidence = 0.6
        return (label, confidence, get_feeling_affordances(label))

    # Positive valence + high arousal
    if positive and high_arousal:
        # Could be excited or delighted -- delighted implies savoring
        if valence > 0.3:
            label = "delighted"
        else:
            label = "excited"
        confidence = 0.7
        return (label, confidence, get_feeling_affordances(label))

    # Positive valence + low arousal
    if positive and not high_arousal:
        if arousal < t["boredom_arousal_max"]:
            label = "peaceful"
        else:
            label = "content"
        confidence = 0.7
        return (label, confidence, get_feeling_affordances(label))

    # Neutral valence + high arousal
    if high_arousal and not positive and not negative:
        # Could be curious or alert
        if context in ["philosophical", "exploratory"]:
            label = "curious"
        else:
            label = "alert"
        confidence = 0.6
        return (label, confidence, get_feeling_affordances(label))

    # Neutral valence + low-to-medium arousal (fallback)
    if not high_arousal and not positive and not negative:
        return ("neutral", 0.5, [])

    # Default fallback
    log.warning(f"Unexpected V+A classification: valence={valence}, arousal={arousal}")
    return ("neutral", 0.3, [])
