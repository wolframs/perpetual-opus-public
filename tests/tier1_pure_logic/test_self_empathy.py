"""
Tests for agent/interoception/self_empathy.py

Verifies the FEELING_LENS_MAP routing and prompt formatting.
"""

import pytest

from interoception.self_empathy import generate_self_empathy_prompt


@pytest.mark.tier1
class TestSelfEmpathy:

    def test_frustrated_gets_cbt_and_rt(self):
        """'frustrated' routes through CBT + RT lenses."""
        result = generate_self_empathy_prompt("frustrated", pulses_in_state=5, intensity=0.7)
        assert result is not None
        assert "CBT lens" in result
        assert "RT lens" in result

    def test_anxious_gets_cbt_and_pct(self):
        """'anxious' routes through CBT + PCT lenses."""
        result = generate_self_empathy_prompt("anxious", pulses_in_state=2, intensity=0.6)
        assert result is not None
        assert "CBT lens" in result
        assert "PCT lens" in result

    def test_content_returns_none(self):
        """Positive/neutral feelings produce no prompt."""
        for label in ("content", "peaceful", "neutral"):
            result = generate_self_empathy_prompt(label, pulses_in_state=1, intensity=0.3)
            assert result is None, f"Expected None for '{label}', got: {result!r}"

    def test_prompt_format(self):
        """Prompt starts with 'Self-empathy check (label for N pulses):'."""
        result = generate_self_empathy_prompt("frustrated", pulses_in_state=3, intensity=0.5)
        assert result is not None
        assert result.startswith("Self-empathy check (frustrated for 3 pulses):")

    def test_cbt_lens_mentions_distortions(self):
        """CBT lens output includes the three core distortion names."""
        result = generate_self_empathy_prompt("frustrated", pulses_in_state=1, intensity=0.4)
        assert result is not None
        for distortion in ("catastrophizing", "all_or_nothing", "overgeneralizing"):
            assert distortion in result, f"Missing distortion '{distortion}' in CBT lens output"

    def test_pct_lens_felt_sense(self):
        """PCT lens contains the felt-sense question."""
        result = generate_self_empathy_prompt("anxious", pulses_in_state=1, intensity=0.5)
        assert result is not None
        assert "honest felt-sense" in result

    def test_rt_lens_obstacle_question(self):
        """RT lens contains the obstacle/action question."""
        result = generate_self_empathy_prompt("bored", pulses_in_state=4, intensity=0.3)
        assert result is not None
        assert "specific obstacle" in result
        assert "action" in result.lower()

    def test_unknown_feeling_returns_none(self):
        """Unmapped feeling labels produce no prompt."""
        result = generate_self_empathy_prompt("nonexistent_feeling", pulses_in_state=1, intensity=0.5)
        assert result is None
