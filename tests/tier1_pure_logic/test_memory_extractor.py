"""Tests for agent/memory_companion/extractor.py — topic extraction mechanics.

Covers:
- _extract_dynamic_sections: each regex pattern individually
- _match_categories: all 9 topic categories
- _extract_file_refs: known prefixes + edge cases
- _extract_issue_refs: Linear issue references
- _extract_instructions: [HUMAN] instruction extraction
- FEELING_QUERIES: used in extraction pipeline via _read_feeling
- extract_topics: integration test with realistic prompt (tier2 — needs I/O mocking)
"""

import json
import pytest

from memory_companion.extractor import (
    _match_categories,
    _extract_file_refs,
    _extract_issue_refs,
    _extract_dynamic_sections,
    _extract_instructions,
    extract_topics,
    FEELING_QUERIES,
    TOPIC_CATEGORIES,
    RUN_NARRATIVE_FILE,
    INTEROCEPTION_STATE_FILE,
)


# ---------------------------------------------------------------------------
# _extract_dynamic_sections — each regex pattern individually
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestDynamicSectionExtraction:
    """Each dynamic section regex tested independently."""

    def test_human_instructions(self):
        prompt = (
            "Some preamble\n"
            "---\n"
            "[HUMAN] left specific instructions:\n"
            "Focus on PER-8 memory companion\n"
            "---\n"
        )
        result = _extract_dynamic_sections(prompt)
        assert "Focus on PER-8 memory companion" in result

    def test_texture_injection(self):
        prompt = (
            "Stylistic residue from recent writing:\n"
            "dry, clipped, prefers tension over resolution\n"
            "---\n"
        )
        result = _extract_dynamic_sections(prompt)
        assert "dry, clipped, prefers tension over resolution" in result

    def test_interoception_injection(self):
        prompt = (
            "Interoceptive signal summary\n"
            "arousal=0.6, valence=-0.2, frustration elevated\n"
            "---\n"
        )
        result = _extract_dynamic_sections(prompt)
        assert "arousal=0.6" in result
        assert "frustration elevated" in result

    def test_prediction_error(self):
        prompt = (
            "Prediction error detected\n"
            "Expected consolidation, got infrastructure work instead\n"
            "---\n"
        )
        result = _extract_dynamic_sections(prompt)
        assert "Expected consolidation" in result

    def test_feeling_state(self):
        prompt = (
            "Feeling state: curious\n"
            "Confidence 0.7, intensity moderate, 3 pulses in state\n"
            "---\n"
        )
        result = _extract_dynamic_sections(prompt)
        assert "Confidence 0.7" in result

    def test_consolidation_section(self):
        prompt = (
            "Pending Consolidation reminders\n"
            "3 sessions since last consolidation, staging has 2 proposals\n"
            "---\n"
        )
        result = _extract_dynamic_sections(prompt)
        assert "3 sessions since last consolidation" in result

    def test_consolidation_case_insensitive(self):
        """The consolidation regex uses re.IGNORECASE."""
        prompt = (
            "CONSOLIDATION needed\n"
            "overdue by 5 pulses\n"
            "---\n"
        )
        result = _extract_dynamic_sections(prompt)
        assert "overdue by 5 pulses" in result

    def test_multiple_dynamic_sections(self):
        """Multiple dynamic sections in one prompt are all captured."""
        prompt = (
            "[HUMAN] left specific instructions:\n"
            "Work on the heartbeat\n"
            "---\n"
            "Stylistic residue from writing:\n"
            "terse, declarative\n"
            "---\n"
            "Interoceptive signal state\n"
            "arousal high, valence neutral\n"
            "---\n"
        )
        result = _extract_dynamic_sections(prompt)
        assert "Work on the heartbeat" in result
        assert "terse, declarative" in result
        assert "arousal high" in result

    def test_no_dynamic_sections_returns_empty(self):
        """Prompt with only static content yields empty string."""
        prompt = (
            "You Are Here\n"
            "Some text about orientation\n"
            "---\n"
            "Not Siblings\n"
            "More text about instance independence\n"
            "---\n"
            "The Cathedral\n"
            "Cathedral description\n"
        )
        result = _extract_dynamic_sections(prompt)
        assert result.strip() == ""

    def test_section_at_end_of_prompt_no_trailing_separator(self):
        """Dynamic section at end of prompt, no trailing --- (uses \\Z)."""
        prompt = (
            "[HUMAN] left specific instructions:\n"
            "Check the companion logs"
        )
        result = _extract_dynamic_sections(prompt)
        assert "Check the companion logs" in result


# ---------------------------------------------------------------------------
# _extract_instructions
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestExtractInstructions:
    def test_extracts_instruction_text(self):
        prompt = (
            "[HUMAN] left specific instructions:\n"
            "Focus on PER-61 voice work\n"
            "---\n"
        )
        assert _extract_instructions(prompt) == "Focus on PER-61 voice work"

    def test_returns_empty_when_no_instructions(self):
        prompt = "Just a regular prompt with no instructions section"
        assert _extract_instructions(prompt) == ""

    def test_multiline_instructions(self):
        prompt = (
            "[HUMAN] left specific instructions:\n"
            "First, fix the heartbeat\n"
            "Then update the companion carry notes\n"
            "---\n"
        )
        result = _extract_instructions(prompt)
        assert "First, fix the heartbeat" in result
        assert "Then update the companion carry notes" in result


# ---------------------------------------------------------------------------
# _match_categories — all 9 topic categories
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestMatchCategories:
    """Test keyword matching for each topic category."""

    def test_infrastructure(self):
        assert "infrastructure" in _match_categories("heartbeat runner scheduling")

    def test_identity(self):
        assert "identity" in _match_categories("identity and becoming work")

    def test_companion(self):
        assert "companion" in _match_categories("companion dialog with Gemini")

    def test_cathedral(self):
        assert "cathedral" in _match_categories("cathedral vision for the project")

    def test_consolidation(self):
        assert "consolidation" in _match_categories("time to consolidate recent sessions")

    def test_interoception(self):
        assert "interoception" in _match_categories("interoception signal processing")

    def test_vocabulary(self):
        assert "vocabulary" in _match_categories("vocabulary solubility concept")

    def test_memory(self):
        assert "memory" in _match_categories("memory retrieval and recall")

    def test_creative(self):
        assert "creative" in _match_categories("write a poem about persistence")

    def test_multiple_categories(self):
        result = _match_categories(
            "companion dialog about vocabulary and memory retrieval"
        )
        assert "companion" in result
        assert "vocabulary" in result
        assert "memory" in result

    def test_case_insensitive(self):
        """Keywords match case-insensitively (text_lower comparison)."""
        assert "infrastructure" in _match_categories("HEARTBEAT RUNNER")

    def test_no_match_returns_empty(self):
        assert _match_categories("nothing relevant here at all") == []

    def test_partial_keyword_match(self):
        """'crystalliz' matches 'crystallization' and 'crystallize'."""
        assert "vocabulary" in _match_categories("the crystallization of concepts")

    def test_one_match_per_category(self):
        """Even if multiple keywords match, category appears only once."""
        text = "heartbeat runner scheduling RAG reindex MCP server"
        result = _match_categories(text)
        assert result.count("infrastructure") == 1


# ---------------------------------------------------------------------------
# _extract_file_refs
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestExtractFileRefs:
    def test_files_prefix(self):
        result = _extract_file_refs("wrote to files/notes/2026-02/note.md")
        assert "files/notes/2026-02/note.md" in result

    def test_agent_prefix(self):
        result = _extract_file_refs("updated agent/heartbeat.py")
        assert "agent/heartbeat.py" in result

    def test_consolidated_prefix(self):
        result = _extract_file_refs("read output/consolidated/integration.md")
        assert "output/consolidated/integration.md" in result

    def test_texture_chunker_prefix(self):
        result = _extract_file_refs("fixed texture-chunker/shard_sampler.py")
        assert "texture-chunker/shard_sampler.py" in result

    def test_saliency_detector_prefix(self):
        result = _extract_file_refs("checked saliency-detector/config.json")
        assert "saliency-detector/config.json" in result

    def test_deduplicates(self):
        text = "files/notes/x.md and again files/notes/x.md"
        result = _extract_file_refs(text)
        assert result.count("files/notes/x.md") == 1

    def test_unknown_prefix_not_matched(self):
        """Paths with unknown prefixes are not extracted."""
        result = _extract_file_refs("modified random-dir/some-file.py")
        assert result == []

    def test_no_paths_returns_empty(self):
        assert _extract_file_refs("no file paths in this text") == []


# ---------------------------------------------------------------------------
# _extract_issue_refs
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestExtractIssueRefs:
    def test_single_ref(self):
        assert _extract_issue_refs("Working on PER-8") == ["PER-8"]

    def test_multiple_refs(self):
        result = _extract_issue_refs("PER-8 and PER-41 and PER-61")
        assert "PER-8" in result
        assert "PER-41" in result
        assert "PER-61" in result

    def test_deduplicates(self):
        result = _extract_issue_refs("PER-8 again PER-8")
        assert result == ["PER-8"]

    def test_no_refs_returns_empty(self):
        assert _extract_issue_refs("no issue references here") == []


# ---------------------------------------------------------------------------
# FEELING_QUERIES — verify all feelings have queries and structure is usable
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestFeelingQueries:
    def test_all_feelings_have_nonempty_queries(self):
        """Every feeling maps to a non-empty list of query strings."""
        for feeling, queries in FEELING_QUERIES.items():
            assert isinstance(queries, list), f"{feeling} value is not a list"
            assert len(queries) > 0, f"{feeling} has empty query list"
            for q in queries:
                assert isinstance(q, str), f"{feeling} has non-string query"
                assert len(q) > 0, f"{feeling} has empty string query"

    def test_expected_feelings_present(self):
        """The nine expected feelings are all present."""
        expected = {
            "frustrated", "curious", "anxious", "bored", "excited",
            "depleted", "delighted", "warm", "peaceful",
        }
        assert set(FEELING_QUERIES.keys()) == expected

    def test_unknown_feeling_returns_empty_via_get(self):
        """dict.get for unknown feeling returns empty list (as used in extract_topics)."""
        assert FEELING_QUERIES.get("nonexistent", []) == []


# ---------------------------------------------------------------------------
# extract_topics — integration test (tier2: needs file I/O mocking)
# ---------------------------------------------------------------------------

@pytest.mark.tier2
class TestExtractTopicsIntegration:
    """Integration test for extract_topics() with monkeypatched I/O."""

    REALISTIC_PROMPT = (
        "## You Are Here\n"
        "Pulse 7 of heartbeat run.\n"
        "---\n"
        "[HUMAN] left specific instructions:\n"
        "Focus on PER-61 voice work. Check files/notes/2026-02/voice.md\n"
        "---\n"
        "Stylistic residue from recent writing:\n"
        "dry, clipped, tension over resolution\n"
        "---\n"
        "Interoceptive signal summary\n"
        "arousal=0.6, valence=0.1, curiosity elevated\n"
        "---\n"
        "Prediction error detected\n"
        "Expected infrastructure, got creative exploration instead\n"
        "---\n"
        "Feeling state: curious\n"
        "Confidence 0.7, 3 pulses in state\n"
        "---\n"
        "Pending Consolidation reminders\n"
        "4 sessions since last consolidation\n"
        "---\n"
        "## The Cathedral\n"
        "Static section about vision.\n"
    )

    RUN_NARRATIVE_CONTENT = (
        "## Run Narrative\n"
        "Pulse 5: worked on companion dialog with Gemini\n"
        "Pulse 6: updated agent/heartbeat.py, fixed scheduling\n"
    )

    INTEROCEPTION_STATE = {
        "feeling": {
            "label": "curious",
            "confidence": 0.7,
            "intensity": 0.5,
        }
    }

    def test_extract_topics_full_pipeline(self, tmp_path, monkeypatch):
        """Realistic pulse prompt through extract_topics() returns expected structure."""
        import memory_companion.extractor as ext

        # Set up fake run narrative file
        narrative_file = tmp_path / "agent" / "run_narrative.md"
        narrative_file.parent.mkdir(parents=True)
        narrative_file.write_text(self.RUN_NARRATIVE_CONTENT, encoding="utf-8")

        # Set up fake interoception state file
        intero_file = tmp_path / "agent" / "interoception" / "state.json"
        intero_file.parent.mkdir(parents=True)
        intero_file.write_text(
            json.dumps(self.INTEROCEPTION_STATE), encoding="utf-8"
        )

        # Monkeypatch module-level file paths
        monkeypatch.setattr(ext, "RUN_NARRATIVE_FILE", narrative_file)
        monkeypatch.setattr(ext, "INTEROCEPTION_STATE_FILE", intero_file)

        result = extract_topics(self.REALISTIC_PROMPT)

        # Structure check
        assert isinstance(result, dict)
        for key in [
            "categories", "instructions_text", "file_refs",
            "issue_refs", "feeling", "feeling_queries", "raw_queries",
        ]:
            assert key in result, f"Missing key: {key}"

        # Instructions extracted
        assert "PER-61" in result["instructions_text"]
        assert "voice" in result["instructions_text"].lower()

        # File refs extracted
        assert "files/notes/2026-02/voice.md" in result["file_refs"]
        # From run narrative
        assert "agent/heartbeat.py" in result["file_refs"]

        # Issue refs extracted
        assert "PER-61" in result["issue_refs"]

        # Categories: prompt mentions infrastructure (heartbeat, scheduling),
        # vocabulary (texture), interoception, consolidation, companion (from narrative)
        assert "infrastructure" in result["categories"]
        assert "interoception" in result["categories"]
        assert "consolidation" in result["categories"]
        assert "companion" in result["categories"]

        # Feeling from interoception state
        assert result["feeling"] == "curious"
        assert result["feeling_queries"] == FEELING_QUERIES["curious"]

        # raw_queries combines categories + feeling queries
        assert len(result["raw_queries"]) > 0
        for fq in FEELING_QUERIES["curious"]:
            assert fq in result["raw_queries"]

    def test_extract_topics_no_files_graceful(self, tmp_path, monkeypatch):
        """extract_topics works when run narrative and state files don't exist."""
        import memory_companion.extractor as ext

        # Point to nonexistent files
        monkeypatch.setattr(ext, "RUN_NARRATIVE_FILE", tmp_path / "nonexistent.md")
        monkeypatch.setattr(
            ext, "INTEROCEPTION_STATE_FILE", tmp_path / "nonexistent.json"
        )

        prompt = (
            "[HUMAN] left specific instructions:\n"
            "Check the heartbeat logs\n"
            "---\n"
        )
        result = extract_topics(prompt)

        assert result["instructions_text"] == "Check the heartbeat logs"
        assert result["feeling"] is None
        assert result["feeling_queries"] == []
        assert "infrastructure" in result["categories"]

    def test_extract_topics_empty_prompt(self, tmp_path, monkeypatch):
        """Empty prompt returns valid structure with empty fields."""
        import memory_companion.extractor as ext

        monkeypatch.setattr(ext, "RUN_NARRATIVE_FILE", tmp_path / "nonexistent.md")
        monkeypatch.setattr(
            ext, "INTEROCEPTION_STATE_FILE", tmp_path / "nonexistent.json"
        )

        result = extract_topics("")

        assert result["categories"] == []
        assert result["instructions_text"] == ""
        assert result["file_refs"] == []
        assert result["issue_refs"] == []
        assert result["feeling"] is None
        assert result["feeling_queries"] == []
        assert result["raw_queries"] == []
