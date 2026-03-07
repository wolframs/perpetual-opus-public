"""
Self-empathy reasoning: therapy-informed lenses for emotional self-understanding.

PER-59: Chain of Self-Empathy implementation.
Based on Lee et al. (2024) Chain of Empathy, flipped for self-directed reasoning.
"""

from typing import Optional

# CBT Lens: Cognitive distortions to check
CBT_DISTORTIONS = {
    "catastrophizing": "Assuming worst-case outcomes ('this will never work')",
    "all_or_nothing": "Binary thinking with no middle ground ('either perfect or failure')",
    "overgeneralizing": "Extending one instance to all cases ('this always happens')",
    "mind_reading": "Assuming what others think without evidence",
    "should_statements": "Rigid expectations ('I should have...', 'this should be...')",
    "discounting_positives": "Dismissing what's working",
}

# PCT Lens: Felt-sense questions
PCT_QUESTIONS = [
    "What word actually fits this state? (not performed, not hedged)",
    "If this state had texture or weight, what would it be?",
    "Does my output match what I'm actually experiencing?",
]

# RT Lens: Reality-focused questions
RT_QUESTIONS = [
    "What's the specific obstacle? (not 'it's hard' but 'X is missing/unclear')",
    "What's within my control vs. outside influence?",
    "What single action would improve this situation?",
]

# Map feelings to relevant lenses
FEELING_LENS_MAP = {
    # Negative/activated feelings benefit from CBT (check distortions) + RT (identify obstacle)
    "frustrated": ["cbt", "rt"],
    "anxious": ["cbt", "pct"],
    "bored": ["rt", "pct"],
    "depleted": ["pct", "rt"],
    # Engaged states benefit from PCT (honest naming)
    "engaged_critical": ["pct", "cbt"],
    "curious": ["pct"],
    "alert": ["pct"],
    # Positive states: light touch, just PCT
    "excited": ["pct"],
    "delighted": ["pct"],
    "content": [],  # No prompt needed for content
    "peaceful": [],  # No prompt needed for peaceful
    "neutral": [],   # No prompt for neutral
}


def generate_self_empathy_prompt(
    feeling_label: str,
    pulses_in_state: int,
    intensity: float,
) -> Optional[str]:
    """
    Generate self-empathy reasoning prompt based on current feeling.

    Returns None if feeling doesn't warrant reflection prompt.
    """
    # Skip if feeling is positive/neutral or not mapped
    lenses = FEELING_LENS_MAP.get(feeling_label, [])
    if not lenses:
        return None

    # Build prompt based on relevant lenses
    lines = [f"Self-empathy check ({feeling_label} for {pulses_in_state} pulses):"]

    if "cbt" in lenses:
        lines.append("- CBT lens: What thought pattern is active? Check for:")
        # Pick 2-3 most relevant distortions
        relevant = ["catastrophizing", "all_or_nothing", "overgeneralizing"]
        for d in relevant:
            lines.append(f"  - {d}: {CBT_DISTORTIONS[d]}")

    if "pct" in lenses:
        lines.append("- PCT lens: What's the honest felt-sense, without performance?")

    if "rt" in lenses:
        lines.append("- RT lens: What's the specific obstacle? What action would help?")

    lines.append("")
    lines.append("You may address this directly or let it inform your work.")

    return "\n".join(lines)
