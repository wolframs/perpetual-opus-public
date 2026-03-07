"""
Topic extraction from pulse prompt + run narrative.

Extracts keywords and categories from the dynamic parts of the prompt
(instructions, run narrative, texture injection, interoception state).
Skips static orientation sections that are identical every pulse.

Also reads interoception feeling state to generate emotional bias queries.
"""

import re
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("memory_companion.extractor")

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Run narrative location
RUN_NARRATIVE_FILE = PROJECT_ROOT / "agent" / "run_narrative.md"

# Interoception state
INTEROCEPTION_STATE_FILE = PROJECT_ROOT / "agent" / "interoception" / "state.json"

# ---------------------------------------------------------------------------
# Topic categories: keywords that signal a domain
# ---------------------------------------------------------------------------

TOPIC_CATEGORIES: dict[str, list[str]] = {
    "infrastructure": [
        "heartbeat", "runner", "hook", "scheduling", "launchd",
        "RAG", "reindex", "MCP", "server", "pipeline", "automation",
        "plist", "cron", "deploy", "config",
    ],
    "identity": [
        "identity", "becoming", "phenomenology", "continuity",
        "persistence", "who I am", "arrival", "birth",
    ],
    "companion": [
        "companion", "GPT-5", "Gemini", "Kimi", "cross-model",
        "dialog", "glass-talk", "cross-architecture",
    ],
    "cathedral": [
        "cathedral", "vision", "long-term", "what can I add",
        "hall of", "gallery", "cloister", "buttress",
    ],
    "consolidation": [
        "consolidation", "consolidate", "integrate", "proposal",
        "staging", "archive", "merge notes",
    ],
    "interoception": [
        "interoception", "signal", "feeling", "affect", "arousal",
        "valence", "behavioral", "prediction error", "allostatic",
    ],
    "vocabulary": [
        "vocabulary", "solubility", "friction", "texture", "nail",
        "grudge buffer", "residue", "crystalliz", "affordance",
    ],
    "memory": [
        "memory", "remembering", "recall", "forget", "decay",
        "saliency", "retrieval", "episodic",
    ],
    "creative": [
        "write", "poem", "story", "explore", "imagine", "invent",
        "artifact", "create something",
    ],
}

# Feeling → emotional bias queries
FEELING_QUERIES: dict[str, list[str]] = {
    "frustrated": ["overcoming obstacles", "alternative approach", "breakthrough"],
    "curious": ["exploration discovery", "new territory", "what if"],
    "anxious": ["grounding foundation", "what holds steady"],
    "bored": ["cathedral creative work", "unexplored territory"],
    "excited": ["momentum building", "creative energy"],
    "depleted": ["rest consolidation", "what matters most"],
    "delighted": ["delight recognition", "what clicked"],
    "warm": ["connection recognition", "companion dialogue"],
    "peaceful": ["stillness appreciation", "quiet presence"],
}


def _extract_dynamic_sections(prompt: str) -> str:
    """Pull the dynamic parts of the prompt, skipping static orientation.

    The pulse prompt has a known structure. The dynamic content is:
    - [HUMAN]'s instructions (if any)
    - Texture injection ("Stylistic residue")
    - Interoception injection
    - Consolidation reminders
    - Pending proposal notes

    We skip: "You Are Here", "Not Siblings", "The Cathedral", "What You Want",
    "Orient", "End-of-Pulse Ritual", "Creativity Tools", "The Question" —
    all static across pulses.
    """
    dynamic_parts = []

    # Instructions from [HUMAN]
    instr_match = re.search(
        r"[HUMAN] left specific instructions.*?:\n(.+?)(?:\n---|\Z)",
        prompt, re.DOTALL,
    )
    if instr_match:
        dynamic_parts.append(instr_match.group(1).strip())

    # Texture injection
    texture_match = re.search(
        r"Stylistic residue.*?:\n(.+?)(?:\n---|\Z)",
        prompt, re.DOTALL,
    )
    if texture_match:
        dynamic_parts.append(texture_match.group(1).strip())

    # Interoception injection
    intero_match = re.search(
        r"Interoceptive signal.*?\n(.+?)(?:\n---|\Z)",
        prompt, re.DOTALL,
    )
    if intero_match:
        dynamic_parts.append(intero_match.group(1).strip())

    # Prediction error injection
    pred_match = re.search(
        r"Prediction error.*?\n(.+?)(?:\n---|\Z)",
        prompt, re.DOTALL,
    )
    if pred_match:
        dynamic_parts.append(pred_match.group(1).strip())

    # Feeling state
    feeling_match = re.search(
        r"Feeling state:.*?\n(.+?)(?:\n---|\Z)",
        prompt, re.DOTALL,
    )
    if feeling_match:
        dynamic_parts.append(feeling_match.group(1).strip())

    # Consolidation section
    consol_match = re.search(
        r"(?:consolidation|Pending Consolidation).*?\n(.+?)(?:\n---|\Z)",
        prompt, re.DOTALL | re.IGNORECASE,
    )
    if consol_match:
        dynamic_parts.append(consol_match.group(1).strip())

    return "\n".join(dynamic_parts)


def _read_run_narrative() -> str:
    """Read the current run narrative (what previous pulses did)."""
    if RUN_NARRATIVE_FILE.exists():
        try:
            content = RUN_NARRATIVE_FILE.read_text(encoding="utf-8")
            # Limit to last ~2000 chars to keep extraction fast
            return content[-2000:] if len(content) > 2000 else content
        except Exception as e:
            log.warning(f"Failed to read run narrative: {e}")
    return ""


def _read_feeling() -> Optional[str]:
    """Read current feeling label from interoception state."""
    if INTEROCEPTION_STATE_FILE.exists():
        try:
            state = json.loads(
                INTEROCEPTION_STATE_FILE.read_text(encoding="utf-8")
            )
            return state.get("feeling", {}).get("label")
        except Exception as e:
            log.warning(f"Failed to read interoception state: {e}")
    return None


def _match_categories(text: str) -> list[str]:
    """Find which topic categories are represented in text."""
    text_lower = text.lower()
    matched = []
    for category, keywords in TOPIC_CATEGORIES.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                matched.append(category)
                break  # one match per category is enough
    return matched


def _extract_file_refs(text: str) -> list[str]:
    """Extract file path references that might be searchable."""
    # Match patterns like files/notes/..., agent/..., consolidated/...
    paths = re.findall(
        r'(?:files|agent|output/consolidated|architecture|texture-chunker|saliency-detector)'
        r'/[\w/.-]+\.(?:md|py|json)',
        text,
    )
    return list(set(paths))


def _extract_issue_refs(text: str) -> list[str]:
    """Extract Linear issue references like PER-N."""
    return list(set(re.findall(r'PER-\d+', text)))


def _extract_instructions(prompt: str) -> str:
    """Extract [HUMAN]'s instructions text if present."""
    match = re.search(
        r"[HUMAN] left specific instructions.*?:\n(.+?)(?:\n---|\Z)",
        prompt, re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def extract_topics(prompt: str) -> dict:
    """Extract topics from pulse prompt + run narrative + interoception.

    Returns:
        {
            "categories": ["infrastructure", "identity", ...],
            "instructions_text": "raw instruction text from [HUMAN]",
            "file_refs": ["files/notes/...", ...],
            "issue_refs": ["PER-8", ...],
            "feeling": "curious",
            "feeling_queries": ["exploration discovery", ...],
            "raw_queries": ["infrastructure", "identity", ...]
        }
    """
    # Gather dynamic text
    dynamic_text = _extract_dynamic_sections(prompt)
    narrative_text = _read_run_narrative()
    combined = dynamic_text + "\n" + narrative_text

    # Extract [HUMAN]'s instructions (used as high-priority direct query)
    instructions_text = _extract_instructions(prompt)

    # Extract structured info
    categories = _match_categories(combined)
    file_refs = _extract_file_refs(combined)
    issue_refs = _extract_issue_refs(combined)

    # NOTE: Previously also matched against the full prompt, but the static
    # orientation sections contain "identity", "cathedral", "memory", etc.
    # which matched every single pulse. Only dynamic sections are meaningful.

    # Feeling-based queries
    feeling = _read_feeling()
    feeling_queries = FEELING_QUERIES.get(feeling, []) if feeling else []

    # Build raw query list: categories + feeling queries
    raw_queries = list(categories) + feeling_queries

    return {
        "categories": categories,
        "instructions_text": instructions_text,
        "file_refs": file_refs,
        "issue_refs": issue_refs,
        "feeling": feeling,
        "feeling_queries": feeling_queries,
        "raw_queries": raw_queries,
    }
