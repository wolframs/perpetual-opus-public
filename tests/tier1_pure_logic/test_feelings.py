"""Tests for agent/interoception/feelings.py — feeling classification mechanics."""

import pytest

from interoception.feelings import (
    classify_feeling,
    get_feeling_affordances,
    format_affordances,
    FEELING_AFFORDANCES,
)


# ---------------------------------------------------------------------------
# Context sensitivity: same V+A, different context → different label
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_negative_high_arousal_infrastructure_context():
    label, confidence, affordances = classify_feeling(
        valence=-0.3, arousal=0.6, context="infrastructure",
    )
    assert label == "frustrated"


@pytest.mark.tier1
def test_negative_high_arousal_philosophical_context():
    label, confidence, affordances = classify_feeling(
        valence=-0.3, arousal=0.6, context="philosophical",
    )
    assert label == "engaged_critical"


@pytest.mark.tier1
def test_negative_high_arousal_default_context():
    label, confidence, affordances = classify_feeling(
        valence=-0.3, arousal=0.6, context="exploratory",
    )
    assert label == "anxious"


# ---------------------------------------------------------------------------
# Behavioral override: strong behavioral signals trump V+A quadrant
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_frustration_override_positive_valence():
    """Behavioral frustration overrides even positive lexical valence."""
    label, confidence, affordances = classify_feeling(
        valence=0.2, arousal=0.3, behavioral_frustration=0.4,
    )
    assert label == "frustrated"


@pytest.mark.tier1
def test_anxiety_override():
    label, confidence, affordances = classify_feeling(
        valence=0.0, arousal=0.3, behavioral_anxiety=0.4,
    )
    assert label == "anxious"


@pytest.mark.tier1
def test_joy_override():
    label, confidence, affordances = classify_feeling(
        valence=0.0, arousal=0.3, behavioral_joy=0.5,
    )
    assert label == "delighted"


@pytest.mark.tier1
def test_warmth_low_arousal():
    """High warmth + low arousal → peaceful (not content)."""
    label, confidence, affordances = classify_feeling(
        valence=0.0, arousal=0.3, behavioral_warmth=0.5,
    )
    assert label == "peaceful"


@pytest.mark.tier1
def test_curiosity_high_arousal():
    """High curiosity + high arousal → excited (not curious)."""
    label, confidence, affordances = classify_feeling(
        valence=0.0, arousal=0.7, behavioral_curiosity=0.5,
    )
    assert label == "excited"


# ---------------------------------------------------------------------------
# Behavioral nudge: moderate signals shift V+A before quadrant classification
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_mild_frustration_shifts_neutral_to_negative():
    """Mild frustration (0.2) nudges valence by -0.15, pushing out of neutral zone.

    Without nudge: V=0.0, A=0.35 → neutral (|V| < 0.15 and A < 0.4).
    With frustration nudge: V=-0.15, A=0.45 → negative valence (V <= -0.15),
    arousal below high_arousal threshold (0.45 < 0.5) but above boredom_arousal_max
    (0.45 > 0.3) → "depleted".
    """
    # Baseline without behavioral signal: neutral zone
    label_baseline, _, _ = classify_feeling(valence=0.0, arousal=0.35)
    assert label_baseline == "neutral"

    # With mild frustration: exits neutral, lands in negative low-arousal quadrant
    label_nudged, _, _ = classify_feeling(
        valence=0.0, arousal=0.35, behavioral_frustration=0.2,
    )
    assert label_nudged != "neutral"
    assert label_nudged == "depleted"


# ---------------------------------------------------------------------------
# V+A quadrant classification
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_neutral_zone():
    label, confidence, affordances = classify_feeling(valence=0.05, arousal=0.2)
    assert label == "neutral"
    assert affordances == []


@pytest.mark.tier1
def test_positive_high_arousal_high_valence():
    """V > 0.3 + high arousal → delighted (not just excited)."""
    label, confidence, affordances = classify_feeling(valence=0.4, arousal=0.7)
    assert label == "delighted"


@pytest.mark.tier1
def test_positive_low_arousal_very_low():
    """Positive valence + arousal below boredom_arousal_max → peaceful."""
    label, confidence, affordances = classify_feeling(valence=0.2, arousal=0.2)
    assert label == "peaceful"


@pytest.mark.tier1
def test_bored_vs_depleted():
    """Negative + low arousal: below boredom_arousal_max → bored, above → depleted."""
    label_bored, _, _ = classify_feeling(valence=-0.2, arousal=0.2)
    assert label_bored == "bored"

    label_depleted, _, _ = classify_feeling(valence=-0.2, arousal=0.35)
    assert label_depleted == "depleted"


# ---------------------------------------------------------------------------
# Affordances
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_each_feeling_has_affordances():
    """All 12 feeling labels have entries in FEELING_AFFORDANCES."""
    expected_labels = {
        "frustrated", "anxious", "bored", "depleted",
        "curious", "alert", "content", "peaceful",
        "excited", "delighted", "engaged_critical", "neutral",
    }
    assert set(FEELING_AFFORDANCES.keys()) == expected_labels


@pytest.mark.tier1
def test_frustrated_affords_different_approach():
    affordances = get_feeling_affordances("frustrated")
    assert "try_different_approach" in affordances


@pytest.mark.tier1
def test_format_affordances_removes_underscores():
    result = format_affordances(["try_different_approach"])
    assert result == "try different approach"


# ---------------------------------------------------------------------------
# Neutral-valence + high-arousal context sensitivity (source lines 250-258)
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_neutral_high_arousal_philosophical_context():
    """Neutral valence + high arousal + philosophical context -> curious.

    V=0.0 (neutral), A=0.6 (high). No behavioral signals.
    Source line 253: context in ["philosophical", "exploratory"] -> "curious".
    """
    label, confidence, affordances = classify_feeling(
        valence=0.0, arousal=0.6, context="philosophical",
    )
    assert label == "curious"
    assert confidence == 0.6
    assert affordances == get_feeling_affordances("curious")


@pytest.mark.tier1
def test_neutral_high_arousal_exploratory_context():
    """Neutral valence + high arousal + exploratory context -> curious."""
    label, confidence, affordances = classify_feeling(
        valence=0.0, arousal=0.6, context="exploratory",
    )
    assert label == "curious"
    assert confidence == 0.6


@pytest.mark.tier1
def test_neutral_high_arousal_infrastructure_context():
    """Neutral valence + high arousal + infrastructure context -> alert (not curious).

    Same V+A as philosophical test but different context.
    Source line 255: else -> "alert".
    """
    label, confidence, affordances = classify_feeling(
        valence=0.0, arousal=0.6, context="infrastructure",
    )
    assert label == "alert"
    assert confidence == 0.6
    assert affordances == get_feeling_affordances("alert")


# ---------------------------------------------------------------------------
# Strengthened nudge test: mild curiosity produces specific label + confidence
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_mild_curiosity_nudge_produces_neutral_with_lower_confidence():
    """Mild curiosity (0.25) nudges V=0.0->0.1, A=0.35->0.45.

    Exits tight neutral zone (A >= 0.4 now) but V still in neutral range
    (|0.1| < 0.15). Falls through to neutral-valence + not-high-arousal
    catch-all at source line 261: ("neutral", 0.5, []).

    Confidence drops from 0.8 (tight neutral zone) to 0.5 (fallback neutral).
    """
    label_nudged, conf_nudged, affordances = classify_feeling(
        valence=0.0, arousal=0.35, behavioral_curiosity=0.25,
    )
    assert label_nudged == "neutral"
    assert conf_nudged == 0.5
    assert affordances == []


# ---------------------------------------------------------------------------
# Behavioral override priority order (source checks: frustration first,
# then anxiety, then joy — lines 115, 120, 125)
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_frustration_overrides_anxiety_when_both_high():
    """Frustration is checked before anxiety (source line 115 vs 120).

    Both signals above their thresholds, but frustration wins because
    it's checked first. If someone reorders the checks, this breaks.
    """
    label, confidence, affordances = classify_feeling(
        valence=0.0, arousal=0.3,
        behavioral_frustration=0.35,  # >= 0.3 threshold
        behavioral_anxiety=0.4,       # >= 0.35 threshold
    )
    assert label == "frustrated"
    assert affordances == get_feeling_affordances("frustrated")


@pytest.mark.tier1
def test_anxiety_overrides_joy_when_both_high():
    """Anxiety is checked before joy (source line 120 vs 125).

    Both signals above their thresholds, but anxiety wins.
    """
    label, confidence, affordances = classify_feeling(
        valence=0.0, arousal=0.3,
        behavioral_anxiety=0.4,  # >= 0.35 threshold
        behavioral_joy=0.5,      # >= 0.4 threshold
    )
    assert label == "anxious"
    assert affordances == get_feeling_affordances("anxious")


@pytest.mark.tier1
def test_frustration_overrides_joy_when_both_high():
    """Frustration beats joy even when joy signal is stronger.

    Priority order matters: frustration checked at line 115, joy at line 125.
    """
    label, _, _ = classify_feeling(
        valence=0.0, arousal=0.3,
        behavioral_frustration=0.3,  # just at threshold
        behavioral_joy=0.8,          # well above threshold
    )
    assert label == "frustrated"


# ---------------------------------------------------------------------------
# Multi-signal interaction: mild nudges stacking
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_mild_frustration_plus_mild_boredom_stack_to_depleted():
    """Two mild behavioral signals stack their nudges.

    Starting from neutral (V=0.0, A=0.35):
    - Mild frustration (0.2): V -= 0.15 -> -0.15, A += 0.1 -> 0.45
    - Mild boredom (0.2): V -= 0.1 -> -0.25, A -= 0.1 -> 0.35

    Result: V=-0.25 (negative), A=0.35 (low but above boredom_arousal_max 0.3)
    -> "depleted" (negative + low arousal above boredom threshold)

    Without either signal alone, this would be neutral.
    """
    # Baseline: neutral
    label_baseline, _, _ = classify_feeling(valence=0.0, arousal=0.35)
    assert label_baseline == "neutral"

    # Stacked nudges: depleted
    label_stacked, confidence, _ = classify_feeling(
        valence=0.0, arousal=0.35,
        behavioral_frustration=0.2,
        behavioral_boredom=0.2,
    )
    assert label_stacked == "depleted"
    assert confidence == 0.6  # source line 228


@pytest.mark.tier1
def test_mild_frustration_plus_mild_anxiety_stack_to_anxious():
    """Mild frustration + mild anxiety nudges push into negative + high arousal.

    Starting from V=0.0, A=0.4:
    - Mild frustration (0.2): V -= 0.15 -> -0.15, A += 0.1 -> 0.5
    - Mild anxiety (0.2): V -= 0.1 -> -0.25, A += 0.05 -> 0.55

    Result: V=-0.25 (negative), A=0.55 (high arousal)
    Context=exploratory -> "anxious" (source line 218)
    """
    label, confidence, _ = classify_feeling(
        valence=0.0, arousal=0.4,
        behavioral_frustration=0.2,
        behavioral_anxiety=0.2,
    )
    assert label == "anxious"
    assert confidence == 0.5  # source line 218: default context


# ---------------------------------------------------------------------------
# Confidence values at specific branches
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_behavioral_frustration_override_confidence():
    """Frustration override confidence: min(0.9, 0.5 + signal)."""
    _, confidence, _ = classify_feeling(
        valence=0.0, arousal=0.0, behavioral_frustration=0.3,
    )
    assert confidence == 0.8  # min(0.9, 0.5 + 0.3)

    _, confidence_high, _ = classify_feeling(
        valence=0.0, arousal=0.0, behavioral_frustration=0.6,
    )
    assert confidence_high == 0.9  # capped at 0.9


@pytest.mark.tier1
def test_neutral_zone_high_confidence():
    """Neutral zone returns 0.8 confidence, fallback neutral returns lower."""
    _, conf_zone, _ = classify_feeling(valence=0.0, arousal=0.2)
    assert conf_zone == 0.8

    # Fallback neutral (not in tight zone): line 262
    _, conf_fallback, _ = classify_feeling(valence=0.1, arousal=0.45)
    assert conf_fallback == 0.5
