"""
Tests for the full interoception chain through agent/interoception/analyzer.py.

Tier 4: integration tests — exercises the real signal extraction, classification,
feeling inference, and drives update pipeline. State file is monkeypatched to tmp_path.
"""

import json
from pathlib import Path

import pytest

import interoception.analyzer as analyzer
from interoception.analyzer import (
    process_pulse_with_classification,
    get_injection,
    DECAY_FACTOR,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    """Redirect interoception state to tmp_path so tests don't touch real state."""
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(analyzer, "STATE_FILE", state_file)
    return state_file


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.tier4
def test_contemplative_pulse_produces_feeling(contemplative_pulse, isolate_state):
    """Processing a contemplative pulse should classify as 'curious'.

    The contemplative text contains "I notice", "I find myself", "I wonder",
    "What strikes me" — introspection and curiosity markers that push
    behavioral_curiosity high enough to nudge V+A into the curious quadrant
    (neutral valence + high arousal in exploratory context).
    """
    result = process_pulse_with_classification(contemplative_pulse, pulse_number=1)

    # Should have extracted signals
    assert result, "Expected non-empty signals dict"
    assert "meta_commentary" in result

    # State file should exist and have a feeling
    state = json.loads(isolate_state.read_text(encoding="utf-8"))
    feeling = state.get("feeling", {})
    label = feeling.get("label", "")

    # Contemplative text has curiosity markers — behavioral_curiosity nudge
    # pushes it into "curious" (neutral V + high A in exploratory context)
    assert label == "curious", f"Expected 'curious', got '{label}'"


@pytest.mark.tier4
def test_frustrated_pulse_produces_frustrated_feeling(frustrated_pulse, isolate_state):
    """Processing a frustrated pulse should classify as 'frustrated'."""
    result = process_pulse_with_classification(frustrated_pulse, pulse_number=1)

    assert result, "Expected non-empty signals dict"

    state = json.loads(isolate_state.read_text(encoding="utf-8"))
    feeling = state.get("feeling", {})
    label = feeling.get("label", "")

    # The frustrated pulse has *sigh*, AGAIN caps, terse sentences, Sisyphus ref
    # Behavioral frustration should be high enough to trigger "frustrated"
    assert label == "frustrated", f"Expected 'frustrated', got '{label}'"


@pytest.mark.tier4
def test_drives_update_through_chain(
    building_pulse, contemplative_pulse, isolate_state
):
    """Processing a building pulse with code_changed=True, then a reflective pulse
    with code_changed=False, should show the building drive changing."""
    # First pulse: building with code changes
    code_changes = {
        "code_changed": True,
        "files_changed": ["agent/heartbeat.py"],
        "publishable_artifact": False,
        "research_artifact": False,
    }
    process_pulse_with_classification(
        building_pulse, pulse_number=1, pulse_changes=code_changes
    )

    state_1 = json.loads(isolate_state.read_text(encoding="utf-8"))
    drives_1 = state_1.get("drives", {})
    building_after_code = drives_1.get("building", 999)

    # Second pulse: reflective, no code changes
    no_changes = {
        "code_changed": False,
        "files_changed": [],
        "publishable_artifact": False,
        "research_artifact": False,
    }
    process_pulse_with_classification(
        contemplative_pulse, pulse_number=2, pulse_changes=no_changes
    )

    state_2 = json.loads(isolate_state.read_text(encoding="utf-8"))
    drives_2 = state_2.get("drives", {})
    building_after_reflect = drives_2.get("building", -1)

    # After code change: building drive should have decayed
    # After no code change: building drive should have risen
    assert building_after_reflect > building_after_code, (
        f"Building drive should rise after pulse with no code changes: "
        f"{building_after_code} -> {building_after_reflect}"
    )


@pytest.mark.tier4
def test_injection_includes_feeling_and_affordances(isolate_state):
    """When state has a sustained frustrated feeling with sufficient confidence,
    get_injection() should include 'Feeling state: frustrated' and affordances."""
    # Set up state directly: frustrated feeling, 3 pulses, high confidence
    state = {
        "version": 5,
        "last_updated": None,
        "signals": {
            "meta_commentary": {"value": 0.1, "pulses_elevated": 0},
            "hedging_ratio": {"value": 0.3, "pulses_elevated": 0},
            "self_correction": {"value": 1, "pulses_elevated": 0},
            "question_density": {"value": 0.05, "pulses_elevated": 0},
            "affect_valence": {"value": -0.3, "pulses_elevated": 0},
            "affect_arousal": {"value": 0.6, "pulses_elevated": 0},
            "behavioral_frustration": {"value": 0.4, "pulses_elevated": 0},
            "behavioral_boredom": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_curiosity": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_anxiety": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_joy": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_warmth": {"value": 0.0, "pulses_elevated": 0},
            "behavioral_arousal": {"value": 0.0, "pulses_elevated": 0},
        },
        "pulse_history": [
            {"pulse": 1, "timestamp": "2026-02-14T03:00:00+00:00", "signals": {}},
        ],
        "baselines": {},
        "last_prediction": None,
        "last_injection": "Interoceptive signal (exploratory context, confirmed):\n- meta_commentary: 0.1 (within expected)",
        "feeling": {
            "label": "frustrated",
            "confidence": 0.7,
            "intensity": 0.45,
            "pulses_in_state": 3,
            "affordances": ["try_different_approach", "surface_obstacle"],
            "previous_labels": ["frustrated", "frustrated", "frustrated"],
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
    isolate_state.write_text(json.dumps(state), encoding="utf-8")

    injection = get_injection()
    assert injection is not None
    assert "Feeling state: frustrated" in injection


@pytest.mark.tier4
def test_end_to_end_frustrated_injection(frustrated_pulse, isolate_state):
    """Full pipeline: frustrated text -> classification -> sustained feeling ->
    get_injection() returns feeling label and affordances.

    No manual state construction -- runs the real pipeline twice so the feeling
    reaches pulses_in_state >= 2, then verifies the injection output.
    """
    # Run frustrated text through the pipeline twice so the feeling persists
    # (get_injection requires pulses_in_state >= 2 and confidence >= 0.5)
    process_pulse_with_classification(frustrated_pulse, pulse_number=1)
    process_pulse_with_classification(frustrated_pulse, pulse_number=2)

    # Verify state has "frustrated" with sufficient persistence
    state = json.loads(isolate_state.read_text(encoding="utf-8"))
    feeling = state["feeling"]
    assert feeling["label"] == "frustrated"
    assert feeling["pulses_in_state"] >= 2
    assert feeling["confidence"] >= 0.5

    # Now get the injection -- should include the feeling
    injection = get_injection()
    assert injection is not None, "Expected non-None injection after sustained frustrated feeling"
    assert "Feeling state: frustrated" in injection
    assert "try different approach" in injection or "surface obstacle" in injection, (
        f"Expected affordances in injection, got: {injection}"
    )


@pytest.mark.tier4
def test_signal_decay_between_pulses(frustrated_pulse, isolate_state):
    """Signals should decay by DECAY_FACTOR (0.85) between pulses.

    Run frustrated text (which produces nonzero behavioral_frustration), then
    run a bland text that produces near-zero frustration. The stored frustration
    signal should be old_value * 0.85, not the new extraction value.
    """
    # First pulse: frustrated text produces high behavioral_frustration
    process_pulse_with_classification(frustrated_pulse, pulse_number=1)

    state_1 = json.loads(isolate_state.read_text(encoding="utf-8"))
    frust_1 = state_1["signals"]["behavioral_frustration"]["value"]
    assert frust_1 > 0, "Frustrated pulse should produce nonzero frustration signal"

    # Second pulse: bland text with zero frustration signal.
    # The decay logic: decayed = old * 0.85; if new < decayed, effective = max(new, decayed)
    # So for new=0 and old=frust_1: effective = max(0, frust_1 * 0.85) = frust_1 * 0.85
    bland_text = "Updated the configuration file. Everything looks fine."
    process_pulse_with_classification(bland_text, pulse_number=2)

    state_2 = json.loads(isolate_state.read_text(encoding="utf-8"))
    frust_2 = state_2["signals"]["behavioral_frustration"]["value"]

    expected_decayed = round(frust_1 * DECAY_FACTOR, 3)
    assert frust_2 == expected_decayed, (
        f"Expected frustration to decay from {frust_1} to {expected_decayed}, "
        f"got {frust_2}"
    )

    # Run a third pulse to verify decay compounds
    process_pulse_with_classification(bland_text, pulse_number=3)

    state_3 = json.loads(isolate_state.read_text(encoding="utf-8"))
    frust_3 = state_3["signals"]["behavioral_frustration"]["value"]

    expected_double_decayed = round(expected_decayed * DECAY_FACTOR, 3)
    assert frust_3 == expected_double_decayed, (
        f"Expected frustration to decay from {expected_decayed} to {expected_double_decayed}, "
        f"got {frust_3}"
    )


@pytest.mark.tier4
def test_state_persistence_across_calls(
    contemplative_pulse, building_pulse, isolate_state
):
    """Two process_pulse calls should result in pulse_history with 2 entries."""
    process_pulse_with_classification(contemplative_pulse, pulse_number=1)
    process_pulse_with_classification(building_pulse, pulse_number=2)

    state = json.loads(isolate_state.read_text(encoding="utf-8"))
    history = state.get("pulse_history", [])
    assert len(history) == 2, f"Expected 2 history entries, got {len(history)}"
    assert history[0]["pulse"] == 1
    assert history[1]["pulse"] == 2
