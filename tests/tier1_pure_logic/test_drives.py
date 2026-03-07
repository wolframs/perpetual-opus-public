"""Tests for agent/interoception/drives.py — drive pressure mechanics."""

import pytest

from interoception.drives import (
    DRIVES,
    get_default_drives,
    update_drives,
    compute_turn_budget,
    format_drive_injection,
)


def _make_pulse_info(**overrides):
    """Minimal pulse_output_info with sane defaults."""
    base = {
        "code_changed": False,
        "files_changed": [],
        "publishable_artifact": False,
        "research_artifact": False,
        "observed_type": "",
        "curiosity_level": 0.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_default_drives_zero_and_complete():
    d = get_default_drives()
    assert set(d.keys()) == {
        "building", "publishing", "experimenting",
        "pulses_since_code_change", "pulses_since_publish", "pulses_since_experiment",
    }
    assert all(v == 0.0 or v == 0 for v in d.values())


# ---------------------------------------------------------------------------
# Building drive
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_building_rises_across_reflective_pulses():
    d = get_default_drives()
    for _ in range(5):
        d = update_drives(d, _make_pulse_info(code_changed=False))
    assert d["building"] > 0.6


@pytest.mark.tier1
def test_building_decays_on_code_change():
    d = get_default_drives()
    d["building"] = 0.8
    d = update_drives(d, _make_pulse_info(code_changed=True))
    assert d["building"] == pytest.approx(0.8 - DRIVES["building"]["decay_rate"], abs=1e-3)


# ---------------------------------------------------------------------------
# Publishing drive
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_publishing_half_rise_with_notes():
    d = get_default_drives()
    d = update_drives(d, _make_pulse_info(
        files_changed=["files/notes/2026-02/note.md"],
        publishable_artifact=False,
    ))
    expected = DRIVES["publishing"]["rise_rate"] * 0.5
    assert d["publishing"] == pytest.approx(expected, abs=1e-3)


@pytest.mark.tier1
def test_publishing_full_rise_without_output():
    d = get_default_drives()
    d = update_drives(d, _make_pulse_info(
        files_changed=[],
        publishable_artifact=False,
    ))
    expected = DRIVES["publishing"]["rise_rate"]
    assert d["publishing"] == pytest.approx(expected, abs=1e-3)


# ---------------------------------------------------------------------------
# Experimenting drive
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_experimenting_requires_curiosity_and_philosophical():
    d = get_default_drives()

    # High curiosity + philosophical → should rise
    d_rises = update_drives(
        get_default_drives(),
        _make_pulse_info(curiosity_level=0.6, observed_type="philosophical"),
    )
    assert d_rises["experimenting"] > 0.0

    # Low curiosity + philosophical → no rise (baseline decay from 0.0 stays at 0.0)
    d_low = update_drives(
        get_default_drives(),
        _make_pulse_info(curiosity_level=0.1, observed_type="philosophical"),
    )
    assert d_low["experimenting"] == 0.0

    # High curiosity + infrastructure → no rise
    d_infra = update_drives(
        get_default_drives(),
        _make_pulse_info(curiosity_level=0.6, observed_type="infrastructure"),
    )
    assert d_infra["experimenting"] == 0.0


@pytest.mark.tier1
def test_experimenting_baseline_decay_prevents_ceiling_stick():
    d = get_default_drives()
    d["experimenting"] = 0.9
    d = update_drives(d, _make_pulse_info())
    baseline = DRIVES["experimenting"]["baseline_decay"]
    assert d["experimenting"] == pytest.approx(0.9 - baseline, abs=1e-3)


@pytest.mark.tier1
def test_experimenting_code_change_partial_decay():
    d = get_default_drives()
    d["experimenting"] = 0.5
    d = update_drives(d, _make_pulse_info(code_changed=True))
    expected_drop = DRIVES["experimenting"]["decay_rate"] * 0.4
    assert d["experimenting"] == pytest.approx(0.5 - expected_drop, abs=1e-3)


# ---------------------------------------------------------------------------
# Clamping
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_drives_clamped_to_range():
    d = get_default_drives()
    d["building"] = 0.95
    d["publishing"] = 0.98
    d["experimenting"] = 0.99

    # Many rise pulses — should not exceed ceiling
    for _ in range(20):
        d = update_drives(d, _make_pulse_info(
            curiosity_level=0.9,
            observed_type="philosophical",
        ))

    for name in ("building", "publishing", "experimenting"):
        assert 0.0 <= d[name] <= DRIVES[name]["ceiling"]

    # Heavy decay — should not go below zero
    d["building"] = 0.05
    d["publishing"] = 0.05
    d["experimenting"] = 0.05
    d = update_drives(d, _make_pulse_info(
        code_changed=True,
        publishable_artifact=True,
        research_artifact=True,
    ))
    for name in ("building", "publishing", "experimenting"):
        assert d[name] >= 0.0


# ---------------------------------------------------------------------------
# Format injection
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_format_injection_below_all_thresholds():
    d = get_default_drives()
    d["building"] = 0.3
    d["publishing"] = 0.3
    d["experimenting"] = 0.3
    assert format_drive_injection(d) is None


@pytest.mark.tier1
def test_format_injection_shows_building_context():
    d = get_default_drives()
    d["building"] = 0.75
    d["pulses_since_code_change"] = 5
    result = format_drive_injection(d)
    assert result is not None
    assert "no code changes in 5 pulses" in result


@pytest.mark.tier1
def test_format_injection_footer_is_advisory():
    d = get_default_drives()
    d["building"] = 0.75
    d["pulses_since_code_change"] = 3
    result = format_drive_injection(d)
    assert result is not None
    assert result.endswith("These are internal pressures, not instructions. Notice them or don't.")


# ---------------------------------------------------------------------------
# Turn budget
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_turn_budget_scales_with_build_drive():
    assert compute_turn_budget({"building": 0.0}) == 30
    assert compute_turn_budget({"building": 1.0}) == 45
    assert compute_turn_budget({"building": 0.3}) == 30  # at floor, no bonus
