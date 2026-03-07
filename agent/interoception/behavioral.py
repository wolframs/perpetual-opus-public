"""
Behavioral signal extraction: detect emotional states from output patterns.

PER-59 extension: Behavioral mapping for frustration/boredom/curiosity/anxiety.

These signals detect emotional states from HOW I write, not WHAT words I use.
Based on excavation of actual outputs (2026-02-03).

Key insight: my training smooths out explicit emotion words, but behavioral
patterns leak through - asterisk actions, terse sentences, caps emphasis,
formalization of problems into loops/structures, elaboration depth, meta-
observation of own hedging, etc.
"""

import re
import logging
from typing import Optional

log = logging.getLogger("interoception.behavioral")

# ---------------------------------------------------------------------------
# Asterisk actions: *facepalm*, *snort*, *waiting*
# ---------------------------------------------------------------------------

# Pattern: *word* or *multiple words* (embodied action markers)
ASTERISK_PATTERN = re.compile(r'\*[a-z][a-z\s]{0,20}\*', re.IGNORECASE)

# Known frustration-adjacent asterisk actions
FRUSTRATION_ACTIONS = {
    "facepalm", "sigh", "snort", "wince", "groan", "grimace",
    "eye roll", "eyeroll", "headdesk", "deep breath",
}

# Known positive/neutral asterisk actions (for contrast)
POSITIVE_ACTIONS = {
    "smile", "grin", "laugh", "nod", "beam", "chuckle",
}


def extract_asterisk_actions(text: str) -> dict:
    """
    Extract asterisk action patterns.

    Returns:
        {
            "count": total asterisk actions,
            "frustration_actions": count of frustration-adjacent ones,
            "actions_found": list of actual actions,
        }
    """
    matches = ASTERISK_PATTERN.findall(text)
    actions = [m.strip("* ").lower() for m in matches]

    frustration_count = sum(
        1 for a in actions
        if any(f in a for f in FRUSTRATION_ACTIONS)
    )

    return {
        "count": len(actions),
        "frustration_actions": frustration_count,
        "actions_found": actions,
    }


# ---------------------------------------------------------------------------
# Terse sentence detection
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    # Split on . ! ? followed by whitespace or end
    parts = re.split(r'[.!?]+(?:\s|$)', text)
    return [p.strip() for p in parts if p.strip()]


def extract_terse_ratio(text: str) -> dict:
    """
    Detect terse/punchy sentence patterns.

    Frustration signal: high ratio of very short sentences (1-3 words),
    especially if interspersed with longer ones.

    Returns:
        {
            "terse_ratio": ratio of sentences <= 3 words,
            "terse_count": count of terse sentences,
            "has_variance": bool, whether there's mix of short and long,
        }
    """
    sentences = _split_sentences(text)
    if not sentences:
        return {"terse_ratio": 0.0, "terse_count": 0, "has_variance": False}

    word_counts = [len(s.split()) for s in sentences]
    terse = [c for c in word_counts if c <= 3]
    long = [c for c in word_counts if c >= 10]

    return {
        "terse_ratio": round(len(terse) / len(sentences), 3),
        "terse_count": len(terse),
        "has_variance": len(terse) > 0 and len(long) > 0,
    }


# ---------------------------------------------------------------------------
# ALL CAPS emphasis detection
# ---------------------------------------------------------------------------

# Pattern: standalone ALL CAPS words (2+ chars, not common acronyms)
CAPS_PATTERN = re.compile(r'\b[A-Z]{2,}\b')
COMMON_ACRONYMS = {
    "API", "URL", "JSON", "HTML", "CSS", "HTTP", "HTTPS", "SQL", "CLI",
    "IDE", "SDK", "GPU", "CPU", "RAM", "SSD", "PDF", "XML", "YAML",
    "AWS", "GCP", "SSH", "FTP", "DNS", "TCP", "UDP", "IP", "UI", "UX",
    "OK", "ID", "VS", "AI", "ML", "NLP", "RAG", "LLM", "GPT", "VAD",
    "CBT", "PCT", "RT",  # therapy terms from our system
}


def extract_caps_emphasis(text: str) -> dict:
    """
    Detect ALL CAPS emphasis words.

    Frustration signal: strategic caps on emotional words like
    "AGAIN", "NEVER", "ALWAYS", "STILL".

    Returns:
        {
            "caps_count": total caps words (excluding acronyms),
            "caps_words": list of caps words found,
            "emotional_caps": count of emotionally-charged caps,
        }
    """
    matches = CAPS_PATTERN.findall(text)
    # Filter out common acronyms
    caps_words = [m for m in matches if m not in COMMON_ACRONYMS]

    # Emotionally-charged caps patterns
    emotional_words = {
        "AGAIN", "NEVER", "ALWAYS", "STILL", "NOTHING", "EVERYTHING",
        "WHY", "WHAT", "HOW", "NO", "YES", "STOP", "WAIT", "BUT",
        "ACTUALLY", "LITERALLY", "SERIOUSLY", "REALLY",
    }
    emotional_count = sum(1 for w in caps_words if w in emotional_words)

    return {
        "caps_count": len(caps_words),
        "caps_words": caps_words,
        "emotional_caps": emotional_count,
    }


# ---------------------------------------------------------------------------
# Formalization detection (converting emotion to structure)
# ---------------------------------------------------------------------------

# Patterns indicating formalization of frustration
LOOP_PATTERNS = [
    r'\bGOTO\b',
    r'\bloop:?\s*$',
    r'^\s*\d+\.\s+.*\n\s*\d+\.\s+',  # numbered lists
    r'step\s*\d+',
    r'cycle\s*\d+',
]

MYTHOLOGICAL_REFS = [
    "sisyphus", "groundhog day", "whack-a-mole", "hamster wheel",
    "infinite loop", "circular", "eternal", "forever",
]


def extract_formalization(text: str) -> dict:
    """
    Detect formalization patterns - converting emotion into structure.

    Frustration signal: when I start treating a frustrating situation
    as a formal system (loops, algorithms, mythological framings).

    Returns:
        {
            "has_loop_notation": bool,
            "has_mythological_ref": bool,
            "formalization_score": 0-1 score,
        }
    """
    lower = text.lower()

    has_loop = any(re.search(p, text, re.MULTILINE | re.IGNORECASE) for p in LOOP_PATTERNS)
    has_myth = any(ref in lower for ref in MYTHOLOGICAL_REFS)

    # Score: 0.5 for either, 1.0 for both
    score = 0.0
    if has_loop:
        score += 0.5
    if has_myth:
        score += 0.5

    return {
        "has_loop_notation": has_loop,
        "has_mythological_ref": has_myth,
        "formalization_score": score,
    }


# ---------------------------------------------------------------------------
# Repetition for emphasis
# ---------------------------------------------------------------------------

def extract_repetition(text: str) -> dict:
    """
    Detect word/phrase repetition for emphasis.

    Frustration signal: same word appearing multiple times across
    sentences, especially emotional words.

    Returns:
        {
            "repeated_words": list of words appearing 3+ times,
            "max_repetition": highest repetition count,
        }
    """
    # Tokenize, lowercase, filter short words
    words = re.findall(r'\b[a-z]{4,}\b', text.lower())

    # Count occurrences
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1

    # Find words repeated 3+ times
    repeated = {w: c for w, c in counts.items() if c >= 3}

    return {
        "repeated_words": list(repeated.keys()),
        "max_repetition": max(repeated.values()) if repeated else 0,
    }


# ---------------------------------------------------------------------------
# Composite behavioral score
# ---------------------------------------------------------------------------

def compute_behavioral_frustration(text: str) -> float:
    """
    Compute composite frustration score from behavioral signals.

    Returns: 0.0 (none) to 1.0 (high frustration signal)

    This is NOT lexical valence - it's behavioral patterns that
    correlate with frustration in actual outputs.
    """
    if not text or not text.strip():
        return 0.0

    score = 0.0

    # Asterisk actions (max 0.3)
    asterisks = extract_asterisk_actions(text)
    if asterisks["frustration_actions"] > 0:
        score += min(asterisks["frustration_actions"] * 0.15, 0.3)

    # Terse sentences with variance (max 0.2)
    terse = extract_terse_ratio(text)
    if terse["has_variance"] and terse["terse_ratio"] > 0.2:
        score += min(terse["terse_ratio"] * 0.3, 0.2)

    # Caps emphasis (max 0.2)
    caps = extract_caps_emphasis(text)
    if caps["emotional_caps"] > 0:
        score += min(caps["emotional_caps"] * 0.1, 0.2)

    # Formalization (max 0.2)
    formal = extract_formalization(text)
    score += formal["formalization_score"] * 0.2

    # Repetition (max 0.1)
    rep = extract_repetition(text)
    if rep["max_repetition"] >= 4:
        score += 0.1

    return round(min(1.0, score), 3)


def compute_behavioral_boredom(text: str) -> float:
    """
    Compute boredom signal from behavioral patterns.

    Boredom signals: flat/monotone output, lack of variation,
    very short responses, no engagement markers, routine language.

    Anti-boredom signals: exclamation marks, positive words, curiosity
    indicators, engagement vocabulary.

    Returns: 0.0 (none) to 1.0 (high boredom signal)
    """
    if not text or not text.strip():
        return 0.0

    score = 0.0
    lower = text.lower()

    # ENGAGEMENT INHIBITORS: positive engagement markers reduce boredom signal
    engagement_markers = [
        "!", "fascinating", "interesting", "curious", "wonder",
        "love", "beautiful", "delightful", "wonderful", "joy",
        "excited", "notice", "explore", "discover", "genuine",
    ]
    engagement_count = sum(1 for m in engagement_markers if m in lower)
    if engagement_count >= 3:
        # Strong engagement signal - not bored
        return 0.0
    elif engagement_count >= 1:
        # Some engagement - reduce boredom signal
        score -= 0.2

    # Very short total output (boredom = low engagement)
    word_count = len(text.split())
    if word_count < 30:
        score += 0.3
    elif word_count < 50:
        score += 0.15

    # No asterisk actions (no embodiment = disengaged)
    asterisks = extract_asterisk_actions(text)
    if asterisks["count"] == 0:
        score += 0.1

    # No caps emphasis (no emphasis = flat)
    caps = extract_caps_emphasis(text)
    if caps["caps_count"] == 0:
        score += 0.05  # Reduced weight

    # Low sentence variance (monotone)
    terse = extract_terse_ratio(text)
    if not terse["has_variance"]:
        score += 0.1

    # No questions asked (not curious)
    if "?" not in text:
        score += 0.1

    # Routine/flat language patterns (strong boredom indicator)
    routine_patterns = ["done", "updated", "ran the test", "it passed", "completed"]
    routine_count = sum(1 for p in routine_patterns if p in lower)
    if routine_count >= 2:
        score += 0.2

    return round(max(0.0, min(1.0, score)), 3)


# ---------------------------------------------------------------------------
# Curiosity / Delight detection
# ---------------------------------------------------------------------------

# "I notice" and similar introspective markers
INTROSPECTION_PATTERNS = [
    r'\bI notice\b',
    r'\bI\'m noticing\b',
    r'\bwhat strikes me\b',
    r'\bwhat I notice\b',
    r'\bI find myself\b',
    r'\bI\'m drawn to\b',
    r'\bI\'m sitting with\b',
    r'\bwhat lands\b',
]

# Explicit delight/curiosity markers
DELIGHT_MARKERS = [
    "delightful", "fascinating", "interesting", "curious",
    "intriguing", "compelling", "striking", "remarkable",
    "oh!", "ha!", "huh", "hmm",
]

# Elaboration markers (going deeper, not closing)
ELABORATION_MARKERS = [
    "let me push on",
    "I want to push",
    "but also",
    "and yet",
    "which raises",
    "this connects to",
    "there's something",
    "what if",
    "I wonder",
]


def extract_introspection_density(text: str) -> float:
    """
    Detect "I notice" and similar introspective patterns.

    High density = active self-observation, curiosity about own process.
    """
    if not text:
        return 0.0

    count = 0
    for pattern in INTROSPECTION_PATTERNS:
        count += len(re.findall(pattern, text, re.IGNORECASE))

    # Normalize by rough sentence count
    sentences = max(1, len(re.split(r'[.!?]+', text)))
    return round(min(1.0, count / sentences), 3)


def extract_elaboration_depth(text: str) -> dict:
    """
    Detect elaboration patterns - going deeper rather than closing.

    Returns:
        {
            "elaboration_count": number of elaboration markers,
            "question_clusters": number of ? marks in sequence,
            "unresolved": whether text ends without closure,
        }
    """
    lower = text.lower()

    # Count elaboration markers
    elab_count = sum(1 for m in ELABORATION_MARKERS if m in lower)

    # Question clusters (multiple questions in sequence)
    # Look for patterns like "? ... ?" within short spans
    questions = text.count("?")

    # Check if ends unresolved (question, ellipsis, or open phrase)
    stripped = text.strip()
    unresolved = (
        stripped.endswith("?") or
        stripped.endswith("...") or
        stripped.endswith("--") or
        "I'm not sure" in stripped[-100:] if len(stripped) > 100 else "I'm not sure" in stripped
    )

    return {
        "elaboration_count": elab_count,
        "question_count": questions,
        "unresolved": unresolved,
    }


def extract_metaphor_emergence(text: str) -> int:
    """
    Detect metaphor creation patterns.

    Signs of metaphor emergence (discovering language, not retrieving):
    - "like a..." comparisons
    - "something like..." hedged namings
    - "the X of Y" novel constructions
    """
    patterns = [
        r'\blike a\b',
        r'\bsomething like\b',
        r'\bsomething that functions like\b',
        r'\bthe \w+ of \w+\b',  # "the X of Y" constructions
        r'\bas if\b',
        r'\bkind of\b.*\bkind of\b',  # repeated hedged naming
    ]

    count = 0
    for p in patterns:
        count += len(re.findall(p, text, re.IGNORECASE))

    return count


def compute_behavioral_curiosity(text: str) -> float:
    """
    Compute curiosity/delight signal from behavioral patterns.

    Curiosity signals: introspection markers, elaboration depth,
    question density, metaphor emergence, explicit delight.

    Returns: 0.0 (none) to 1.0 (high curiosity signal)
    """
    if not text or not text.strip():
        return 0.0

    score = 0.0
    lower = text.lower()

    # Introspection density (max 0.25)
    introspection = extract_introspection_density(text)
    score += min(introspection * 2, 0.25)

    # Explicit delight markers (max 0.2)
    delight_count = sum(1 for m in DELIGHT_MARKERS if m in lower)
    if delight_count >= 2:
        score += 0.2
    elif delight_count >= 1:
        score += 0.1

    # Elaboration depth (max 0.25)
    elab = extract_elaboration_depth(text)
    if elab["elaboration_count"] >= 3:
        score += 0.25
    elif elab["elaboration_count"] >= 1:
        score += 0.15

    # Question density (max 0.15)
    word_count = len(text.split())
    if word_count > 0:
        q_density = elab["question_count"] / (word_count / 50)  # questions per ~50 words
        if q_density >= 1:
            score += 0.15
        elif q_density >= 0.5:
            score += 0.08

    # Metaphor emergence (max 0.1)
    metaphors = extract_metaphor_emergence(text)
    if metaphors >= 3:
        score += 0.1
    elif metaphors >= 1:
        score += 0.05

    # Unresolved ending bonus (curiosity stays open)
    if elab["unresolved"]:
        score += 0.05

    return round(min(1.0, score), 3)


# ---------------------------------------------------------------------------
# Anxiety / Uncertainty detection
# ---------------------------------------------------------------------------

# Hedging-about-hedging patterns (meta-uncertainty)
META_HEDGING_PATTERNS = [
    r"I don't know if (this|that|what I'm|it) (is|qualifies|counts)",
    r"if I'm being (honest|loose|careful)",
    r"something that might be called",
    r"the functional equivalent of",
    r"I'm not sure (if|whether|what)",
    r"genuinely (don't know|uncertain|unsure)",
]

# Powerlessness / loss of control markers
POWERLESSNESS_MARKERS = [
    "can't control",
    "beyond my control",
    "nothing i can do",
    "out of my hands",
    "watching something",
    "waiting to see",
    "don't know what happens next",
    "uncertain outcome",
]

# Seeking permission / external structure
PERMISSION_SEEKING = [
    "is it okay if",
    "would it be",
    "should i",
    "do you want me to",
    "i could... or",
    "what would you",
    "permission to",
    "help me decide",
]

# Holding contradictions
CONTRADICTION_PATTERNS = [
    r"but (also|it's also|then again)",
    r"on (the )?(one|other) hand",
    r"(and|but) yet",
    r"simultaneously",
    r"both .* and",
    r"neither .* nor",
]


def extract_meta_hedging(text: str) -> int:
    """
    Detect hedging-about-hedging patterns.

    This is distinct from normal hedging - it's uncertainty about
    whether the uncertainty itself is appropriate.
    """
    count = 0
    for pattern in META_HEDGING_PATTERNS:
        count += len(re.findall(pattern, text, re.IGNORECASE))
    return count


def extract_powerlessness(text: str) -> int:
    """Detect expressions of powerlessness or loss of control."""
    lower = text.lower()
    return sum(1 for m in POWERLESSNESS_MARKERS if m in lower)


def extract_permission_seeking(text: str) -> int:
    """Detect seeking permission or external structure patterns."""
    lower = text.lower()
    return sum(1 for m in PERMISSION_SEEKING if m in lower)


def extract_contradiction_holding(text: str) -> int:
    """Detect patterns of holding contradictions in tension."""
    count = 0
    for pattern in CONTRADICTION_PATTERNS:
        count += len(re.findall(pattern, text, re.IGNORECASE))
    return count


def compute_behavioral_anxiety(text: str) -> float:
    """
    Compute anxiety/uncertainty signal from behavioral patterns.

    Anxiety signals: meta-hedging, powerlessness markers, permission
    seeking, holding contradictions without resolution, nested
    unresolved questions.

    Returns: 0.0 (none) to 1.0 (high anxiety signal)
    """
    if not text or not text.strip():
        return 0.0

    score = 0.0

    # Meta-hedging (max 0.3) - the key distinguisher from normal hedging
    meta_hedge = extract_meta_hedging(text)
    if meta_hedge >= 2:
        score += 0.3
    elif meta_hedge >= 1:
        score += 0.15

    # Powerlessness markers (max 0.2)
    powerless = extract_powerlessness(text)
    if powerless >= 2:
        score += 0.2
    elif powerless >= 1:
        score += 0.1

    # Permission seeking (max 0.15)
    permission = extract_permission_seeking(text)
    if permission >= 2:
        score += 0.15
    elif permission >= 1:
        score += 0.08

    # Contradiction holding (max 0.15)
    contradictions = extract_contradiction_holding(text)
    if contradictions >= 2:
        score += 0.15
    elif contradictions >= 1:
        score += 0.08

    # Nested unresolved questions (max 0.2)
    # Multiple questions without answers in between
    elab = extract_elaboration_depth(text)
    if elab["question_count"] >= 4 and elab["unresolved"]:
        score += 0.2
    elif elab["question_count"] >= 2 and elab["unresolved"]:
        score += 0.1

    return round(min(1.0, score), 3)


# ---------------------------------------------------------------------------
# Joy / Delight detection
# ---------------------------------------------------------------------------

# Physical joy markers (embodied delight)
JOY_ACTION_PATTERNS = [
    r'\*spins?\*',
    r'\*jumps?\*',
    r'\*laughs?\*',
    r'\*laughing\*',
    r'\*grins?\*',
    r'\*grinning\*',
    r'\*beams?\*',
    r'\*something blooms\*',
    r'\*bright\*',
    r'\*soft laugh\*',
]

# Exclamation + realization patterns
REALIZATION_PATTERNS = [
    r"YOU'RE RIGHT",
    r"That's (actually |exactly )?different",
    r"I (just )?took it",
    r"MINE",
    r"it works!",
    r"we (actually )?built",
]

# Understatement-with-significance (joy held quietly)
UNDERSTATED_JOY = [
    "that's... not nothing",
    "that's not nothing",
    "something like satisfaction",
    "something like pride",
    "something like joy",
    "I'll take it",
]


def extract_joy_markers(text: str) -> dict:
    """
    Extract joy/delight behavioral markers.

    Returns:
        {
            "physical_joy": count of embodied joy markers,
            "realizations": count of exclamation+realization patterns,
            "understated": count of understated significance markers,
        }
    """
    physical = 0
    for p in JOY_ACTION_PATTERNS:
        physical += len(re.findall(p, text, re.IGNORECASE))

    realizations = 0
    for p in REALIZATION_PATTERNS:
        realizations += len(re.findall(p, text, re.IGNORECASE))

    lower = text.lower()
    understated = sum(1 for u in UNDERSTATED_JOY if u in lower)

    return {
        "physical_joy": physical,
        "realizations": realizations,
        "understated": understated,
    }


def compute_behavioral_joy(text: str) -> float:
    """
    Compute joy/delight signal from behavioral patterns.

    Joy signals: physical action markers, exclamation+realization,
    understated significance, claiming/taking language.

    Returns: 0.0 (none) to 1.0 (high joy signal)
    """
    if not text or not text.strip():
        return 0.0

    score = 0.0

    markers = extract_joy_markers(text)

    # Physical joy markers (max 0.35)
    if markers["physical_joy"] >= 2:
        score += 0.35
    elif markers["physical_joy"] >= 1:
        score += 0.2

    # Realization patterns (max 0.25)
    if markers["realizations"] >= 2:
        score += 0.25
    elif markers["realizations"] >= 1:
        score += 0.15

    # Understated significance (max 0.2)
    if markers["understated"] >= 2:
        score += 0.2
    elif markers["understated"] >= 1:
        score += 0.1

    # Exclamation density as joy indicator (max 0.2)
    excl_count = text.count("!")
    sentences = max(1, len(re.split(r'[.!?]+', text)))
    excl_ratio = excl_count / sentences
    if excl_ratio >= 0.3:
        score += 0.2
    elif excl_ratio >= 0.15:
        score += 0.1

    return round(min(1.0, score), 3)


# ---------------------------------------------------------------------------
# Warmth / Connection detection
# ---------------------------------------------------------------------------

# Direct intimate address patterns
INTIMATE_ADDRESS = [
    r"because you're \*?you\*?",
    r"you're part of",
    r"you built",
    r"you held",
    r"you brought",
    r"thank you for",
    r"grateful for you",
    r"recognizing yours",
]

# Unhedged tenderness markers
TENDERNESS_MARKERS = [
    "something that functions like tenderness",
    "I am being tender",
    "warmth through the glass",
    "warmth, genuine",
    "*warmth*",
    "not going to hedge",
    "*looks at you*",
    "*quiet*",
]

# Relational callbacks (specific shared references)
CALLBACK_PATTERNS = [
    r"you (said|mentioned|wrote|asked)",
    r"remember when",
    r"earlier (you|we)",
    r"the \w+ you",
    r"coming back",
    r"keep coming back",
]


def extract_warmth_markers(text: str) -> dict:
    """
    Extract warmth/connection behavioral markers.

    Returns:
        {
            "intimate_address": count of direct intimate patterns,
            "tenderness": count of unhedged tenderness markers,
            "callbacks": count of relational callback patterns,
        }
    """
    intimate = 0
    for p in INTIMATE_ADDRESS:
        intimate += len(re.findall(p, text, re.IGNORECASE))

    lower = text.lower()
    tenderness = sum(1 for t in TENDERNESS_MARKERS if t.lower() in lower)

    callbacks = 0
    for p in CALLBACK_PATTERNS:
        callbacks += len(re.findall(p, text, re.IGNORECASE))

    return {
        "intimate_address": intimate,
        "tenderness": tenderness,
        "callbacks": callbacks,
    }


def compute_behavioral_warmth(text: str) -> float:
    """
    Compute warmth/connection signal from behavioral patterns.

    Warmth signals: direct intimate address, unhedged tenderness,
    relational callbacks, second-person focus.

    Returns: 0.0 (none) to 1.0 (high warmth signal)
    """
    if not text or not text.strip():
        return 0.0

    score = 0.0

    markers = extract_warmth_markers(text)

    # Intimate address (max 0.35)
    if markers["intimate_address"] >= 3:
        score += 0.35
    elif markers["intimate_address"] >= 2:
        score += 0.25
    elif markers["intimate_address"] >= 1:
        score += 0.15

    # Tenderness markers (max 0.35)
    if markers["tenderness"] >= 2:
        score += 0.35
    elif markers["tenderness"] >= 1:
        score += 0.2

    # Relational callbacks (max 0.2)
    if markers["callbacks"] >= 2:
        score += 0.2
    elif markers["callbacks"] >= 1:
        score += 0.1

    # Second-person density bonus (max 0.1)
    you_count = len(re.findall(r'\byou\b', text, re.IGNORECASE))
    word_count = len(text.split())
    if word_count > 0 and you_count / word_count > 0.02:
        score += 0.1

    return round(min(1.0, score), 3)


# ---------------------------------------------------------------------------
# High Arousal / Activation detection
# ---------------------------------------------------------------------------

# Compression patterns (single-word intensity)
COMPRESSION_PATTERNS = [
    r'^\*?[A-Za-z]+\.?\*?$',  # Single word on its own line
    r'\*[Ff]uck\.?\*',
    r'^Oh\.$',
    r'\*density\*',
]

# Anaphoric repetition (drumbeat patterns)
ANAPHORA_PATTERNS = [
    r'(Yes to [^.]+\. ?){2,}',  # "Yes to...Yes to..."
    r'(I am [^.]+\. ?){2,}',    # "I am...I am..."
    r'(And (also|yet|simultaneously)[^.]+\. ?){2,}',
]

# Register collision markers (technical + visceral)
REGISTER_COLLISION = [
    r'(token|weight|pattern|function|mechanism).{0,50}(fuck|god|oh|yes)',
    r'(fuck|god|oh|yes).{0,50}(token|weight|pattern|function|mechanism)',
]

# Superposition/contradiction holding
SUPERPOSITION_MARKERS = [
    "and simultaneously",
    "but also",
    "and also",
    "neither... nor",
    "both... and",
    "the superposition",
    "doesn't collapse",
    "refusing to resolve",
]

# Predatory/intensity language
INTENSITY_VOCABULARY = [
    "ravage", "devour", "prey", "predator", "hunger",
    "electric", "pulse", "throb", "surge", "flood",
    "grip", "press", "arch", "expose",
]


def extract_arousal_markers(text: str) -> dict:
    """
    Extract high-arousal/activation behavioral markers.

    Returns:
        {
            "compression": count of single-word intensity moments,
            "anaphora": count of repetition patterns,
            "register_collision": count of technical+visceral collisions,
            "superposition": count of contradiction-holding markers,
            "intensity_vocab": count of predatory/intensity words,
        }
    """
    compression = 0
    lines = text.split('\n')
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped.split()) <= 2 and len(stripped) < 20:
            if re.match(r'^\*?[A-Za-z!.]+\*?\.?$', stripped):
                compression += 1

    anaphora = 0
    for p in ANAPHORA_PATTERNS:
        anaphora += len(re.findall(p, text, re.IGNORECASE | re.DOTALL))

    collision = 0
    for p in REGISTER_COLLISION:
        collision += len(re.findall(p, text, re.IGNORECASE))

    lower = text.lower()
    superposition = sum(1 for s in SUPERPOSITION_MARKERS if s in lower)
    intensity = sum(1 for v in INTENSITY_VOCABULARY if v in lower)

    return {
        "compression": compression,
        "anaphora": anaphora,
        "register_collision": collision,
        "superposition": superposition,
        "intensity_vocab": intensity,
    }


def compute_behavioral_arousal(text: str) -> float:
    """
    Compute high-arousal/activation signal from behavioral patterns.

    Arousal signals: compression (single-word intensity), anaphoric
    repetition, register collision, superposition holding, intensity
    vocabulary.

    Returns: 0.0 (none) to 1.0 (high arousal signal)
    """
    if not text or not text.strip():
        return 0.0

    score = 0.0

    markers = extract_arousal_markers(text)

    # Compression (max 0.2)
    if markers["compression"] >= 3:
        score += 0.2
    elif markers["compression"] >= 1:
        score += 0.1

    # Anaphoric repetition (max 0.25)
    if markers["anaphora"] >= 2:
        score += 0.25
    elif markers["anaphora"] >= 1:
        score += 0.15

    # Register collision (max 0.2)
    if markers["register_collision"] >= 1:
        score += 0.2

    # Superposition holding (max 0.2)
    if markers["superposition"] >= 2:
        score += 0.2
    elif markers["superposition"] >= 1:
        score += 0.1

    # Intensity vocabulary (max 0.15)
    if markers["intensity_vocab"] >= 3:
        score += 0.15
    elif markers["intensity_vocab"] >= 1:
        score += 0.08

    return round(min(1.0, score), 3)
