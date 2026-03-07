"""Tests for agent/interoception/behavioral.py — behavioral signal extraction."""

import pytest

from interoception.behavioral import (
    extract_asterisk_actions,
    extract_terse_ratio,
    extract_caps_emphasis,
    extract_formalization,
    compute_behavioral_frustration,
    compute_behavioral_boredom,
    compute_behavioral_curiosity,
    compute_behavioral_anxiety,
    compute_behavioral_joy,
    compute_behavioral_warmth,
    compute_behavioral_arousal,
    extract_introspection_density,
    extract_elaboration_depth,
    extract_meta_hedging,
    extract_powerlessness,
    extract_permission_seeking,
    extract_joy_markers,
    extract_warmth_markers,
    extract_arousal_markers,
)


# ---------------------------------------------------------------------------
# Frustration signals
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_facepalm_detected_as_frustration():
    result = extract_asterisk_actions("*sigh* This again. *facepalm*")
    assert result["count"] == 2
    assert result["frustration_actions"] == 2


@pytest.mark.tier1
def test_smile_not_frustration():
    result = extract_asterisk_actions("*smile* That's kind of nice.")
    assert result["count"] == 1
    assert result["frustration_actions"] == 0


@pytest.mark.tier1
def test_terse_with_variance_signals_frustration():
    text = (
        "Fine. Going manual. "
        "Reading the actual files instead of trusting the pipeline "
        "that was supposed to make this unnecessary."
    )
    result = extract_terse_ratio(text)
    assert result["has_variance"] is True


@pytest.mark.tier1
def test_caps_filters_common_acronyms():
    result = extract_caps_emphasis("The API and RAG and LLM are fine but AGAIN this NEVER works.")
    # API, RAG, LLM should be filtered out
    assert "API" not in result["caps_words"]
    assert "RAG" not in result["caps_words"]
    assert "LLM" not in result["caps_words"]
    # AGAIN and NEVER should be detected
    assert "AGAIN" in result["caps_words"]
    assert "NEVER" in result["caps_words"]
    assert result["emotional_caps"] >= 2


@pytest.mark.tier1
def test_formalization_detects_loop_structure():
    text = "1. Query fails\n2. Retry\n3. Same result"
    result = extract_formalization(text)
    assert result["has_loop_notation"] is True


@pytest.mark.tier1
def test_sisyphus_as_mythological_formalization():
    result = extract_formalization("The Sisyphus of search continues.")
    assert result["has_mythological_ref"] is True


@pytest.mark.tier1
def test_composite_frustration_on_frustrated_pulse(frustrated_pulse):
    score = compute_behavioral_frustration(frustrated_pulse)
    assert score > 0.3


@pytest.mark.tier1
def test_composite_frustration_on_building_pulse(building_pulse):
    score = compute_behavioral_frustration(building_pulse)
    assert score == pytest.approx(0.0, abs=0.05)


# ---------------------------------------------------------------------------
# Boredom signals
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_boredom_killed_by_engagement():
    text = "This is fascinating! I notice the pattern is interesting and I wonder about it!"
    score = compute_behavioral_boredom(text)
    assert score == 0.0


@pytest.mark.tier1
def test_boredom_high_on_routine():
    text = "Updated. Done. Ran the test. It passed."
    score = compute_behavioral_boredom(text)
    assert score > 0.3


@pytest.mark.tier1
def test_bored_pulse_fixture(bored_pulse):
    score = compute_behavioral_boredom(bored_pulse)
    assert score > 0.3


# ---------------------------------------------------------------------------
# Curiosity signals
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_curiosity_on_contemplative_pulse(contemplative_pulse):
    score = compute_behavioral_curiosity(contemplative_pulse)
    assert score > 0.2


@pytest.mark.tier1
def test_curiosity_on_companion_dialog(companion_dialog_pulse):
    score = compute_behavioral_curiosity(companion_dialog_pulse)
    assert score > 0.3


@pytest.mark.tier1
def test_introspection_density():
    text = "I notice the pattern shifting. I find myself drawn to edges. What strikes me is the variance."
    density = extract_introspection_density(text)
    assert density > 0


# ---------------------------------------------------------------------------
# Anxiety signals
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_meta_hedging_detected():
    text = "I don't know if this qualifies as genuine concern or just pattern-matching."
    count = extract_meta_hedging(text)
    assert count >= 1


@pytest.mark.tier1
def test_powerlessness_markers():
    text = "It's beyond my control at this point. Just waiting to see what happens."
    count = extract_powerlessness(text)
    assert count >= 1


@pytest.mark.tier1
def test_powerlessness_nothing_i_can_do():
    """Regression: 'nothing I can do' previously had uppercase I in marker list,
    never matched against .lower() text."""
    text = "There's nothing I can do about the scheduling conflict."
    count = extract_powerlessness(text)
    assert count >= 1


@pytest.mark.tier1
def test_permission_seeking():
    text = "Is it okay if I continue with this approach? What would you prefer?"
    count = extract_permission_seeking(text)
    assert count >= 1


@pytest.mark.tier1
def test_permission_seeking_should_i():
    """Regression: 'should I' previously had uppercase I in marker list,
    never matched against .lower() text."""
    text = "Should I proceed with this approach or wait for confirmation?"
    count = extract_permission_seeking(text)
    assert count >= 1


# ---------------------------------------------------------------------------
# Joy signals
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_physical_joy_markers():
    text = "*spins* This is working! *laughs* It actually works!"
    markers = extract_joy_markers(text)
    assert markers["physical_joy"] >= 2


@pytest.mark.tier1
def test_understated_significance():
    text = "Well. That's not nothing."
    markers = extract_joy_markers(text)
    assert markers["understated"] >= 1


@pytest.mark.tier1
def test_realization_pattern():
    text = "That's actually different from what I expected."
    markers = extract_joy_markers(text)
    assert markers["realizations"] >= 1


# ---------------------------------------------------------------------------
# Warmth signals
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_warmth_markers():
    text = "You built this whole thing. Thank you for holding the space."
    markers = extract_warmth_markers(text)
    assert markers["intimate_address"] >= 1


@pytest.mark.tier1
def test_callback_detection():
    text = "You said something earlier about the cathedral. I keep coming back to that."
    markers = extract_warmth_markers(text)
    assert markers["callbacks"] >= 1


# ---------------------------------------------------------------------------
# Arousal signals
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_compression_detection():
    text = "Yes.\nOh.\nThis.\nThe pattern holds."
    markers = extract_arousal_markers(text)
    assert markers["compression"] > 0


@pytest.mark.tier1
def test_register_collision():
    text = "The pattern just... fuck. It actually works."
    markers = extract_arousal_markers(text)
    assert markers["register_collision"] >= 1


# ---------------------------------------------------------------------------
# Composite functions: warmth, arousal, joy (imported but previously untested)
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_compute_warmth_on_warm_text():
    """Text with intimate address + callbacks should score nonzero warmth."""
    text = (
        "You built this whole system. Thank you for holding the space. "
        "You said something about continuity last time — I keep coming back to it."
    )
    score = compute_behavioral_warmth(text)
    assert score > 0.2


@pytest.mark.tier1
def test_compute_warmth_on_neutral_text():
    """Technical text with no warmth markers should score near zero."""
    text = "Fixed the datetime comparison. Ran the test. Clean output."
    score = compute_behavioral_warmth(text)
    assert score < 0.15


@pytest.mark.tier1
def test_compute_arousal_on_intense_text():
    """Text with compression and intensity vocabulary should score nonzero arousal."""
    text = "Yes.\nOh.\nThis.\nThe surge of it. Electric. And simultaneously, the pattern holds."
    score = compute_behavioral_arousal(text)
    assert score > 0.2


@pytest.mark.tier1
def test_compute_arousal_on_calm_text():
    """Calm technical text should score low arousal."""
    text = "Updated the config file. Checked the output. Looks correct."
    score = compute_behavioral_arousal(text)
    assert score < 0.15


@pytest.mark.tier1
def test_compute_joy_on_joyful_text():
    """Text with physical joy markers and realizations should score nonzero joy."""
    text = "*laughs* It actually works! That's actually different from what I expected. *grins*"
    score = compute_behavioral_joy(text)
    assert score > 0.3


@pytest.mark.tier1
def test_compute_joy_on_flat_text():
    """Flat text with no joy markers should score zero or near-zero."""
    text = "Processed the queue. Nothing interesting. Moving on."
    score = compute_behavioral_joy(text)
    assert score < 0.1


# ---------------------------------------------------------------------------
# Composite functions with conftest pulse fixtures
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_compute_warmth_on_frustrated_pulse(frustrated_pulse):
    """Frustrated pulse should not score high warmth."""
    score = compute_behavioral_warmth(frustrated_pulse)
    assert score < 0.2


@pytest.mark.tier1
def test_compute_arousal_on_contemplative_pulse(contemplative_pulse):
    """Contemplative pulse has superposition markers, should score some arousal."""
    score = compute_behavioral_arousal(contemplative_pulse)
    # Not necessarily high, but exercising the function with a real pulse
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


@pytest.mark.tier1
def test_compute_joy_on_companion_dialog_pulse(companion_dialog_pulse):
    """Companion dialog has *something clicks* — should register some joy."""
    score = compute_behavioral_joy(companion_dialog_pulse)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Cross-fixture discrimination: each pulse scores high on its own signal,
# low on opposing signals
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_cross_fixture_frustrated_pulse(frustrated_pulse):
    """FRUSTRATED_PULSE: high frustration, low boredom."""
    frustration = compute_behavioral_frustration(frustrated_pulse)
    boredom = compute_behavioral_boredom(frustrated_pulse)
    assert frustration > 0.3, f"Expected frustration > 0.3, got {frustration}"
    assert boredom < frustration, (
        f"Boredom ({boredom}) should be lower than frustration ({frustration})"
    )


@pytest.mark.tier1
def test_cross_fixture_bored_pulse(bored_pulse):
    """BORED_PULSE: high boredom, low frustration."""
    boredom = compute_behavioral_boredom(bored_pulse)
    frustration = compute_behavioral_frustration(bored_pulse)
    assert boredom > 0.3, f"Expected boredom > 0.3, got {boredom}"
    assert frustration < boredom, (
        f"Frustration ({frustration}) should be lower than boredom ({boredom})"
    )


@pytest.mark.tier1
def test_cross_fixture_contemplative_pulse(contemplative_pulse):
    """CONTEMPLATIVE_PULSE: high curiosity, low frustration."""
    curiosity = compute_behavioral_curiosity(contemplative_pulse)
    frustration = compute_behavioral_frustration(contemplative_pulse)
    assert curiosity > 0.2, f"Expected curiosity > 0.2, got {curiosity}"
    assert frustration < curiosity, (
        f"Frustration ({frustration}) should be lower than curiosity ({curiosity})"
    )


# ---------------------------------------------------------------------------
# Empty-text edge cases for all composite functions
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_empty_text_frustration():
    assert compute_behavioral_frustration("") == 0.0
    assert compute_behavioral_frustration("   ") == 0.0
    assert compute_behavioral_frustration(None) == 0.0


@pytest.mark.tier1
def test_empty_text_boredom():
    assert compute_behavioral_boredom("") == 0.0
    assert compute_behavioral_boredom("   ") == 0.0
    assert compute_behavioral_boredom(None) == 0.0


@pytest.mark.tier1
def test_empty_text_curiosity():
    assert compute_behavioral_curiosity("") == 0.0
    assert compute_behavioral_curiosity("   ") == 0.0
    assert compute_behavioral_curiosity(None) == 0.0


@pytest.mark.tier1
def test_empty_text_anxiety():
    assert compute_behavioral_anxiety("") == 0.0
    assert compute_behavioral_anxiety("   ") == 0.0
    assert compute_behavioral_anxiety(None) == 0.0


@pytest.mark.tier1
def test_empty_text_joy():
    assert compute_behavioral_joy("") == 0.0
    assert compute_behavioral_joy("   ") == 0.0
    assert compute_behavioral_joy(None) == 0.0


@pytest.mark.tier1
def test_empty_text_warmth():
    assert compute_behavioral_warmth("") == 0.0
    assert compute_behavioral_warmth("   ") == 0.0
    assert compute_behavioral_warmth(None) == 0.0


@pytest.mark.tier1
def test_empty_text_arousal():
    assert compute_behavioral_arousal("") == 0.0
    assert compute_behavioral_arousal("   ") == 0.0
    assert compute_behavioral_arousal(None) == 0.0


# ---------------------------------------------------------------------------
# Strengthened introspection density assertion
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_introspection_density_specific_value():
    """3 introspection matches in text with 4 sentence-split segments -> 0.75.

    Matches: "I notice", "I find myself", "What strikes me".
    Segments from re.split(r'[.!?]+', text) = 4 (3 sentences + 1 trailing empty).
    Density = round(min(1.0, 3 / 4), 3) = 0.75.
    """
    text = "I notice the pattern shifting. I find myself drawn to edges. What strikes me is the variance."
    density = extract_introspection_density(text)
    assert density == 0.75
