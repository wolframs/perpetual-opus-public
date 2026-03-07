"""
Saliency heuristics - patterns that indicate important moments.

These emerged from analyzing [HUMAN]-Claude conversations and noting
what made moments worth preserving in manual consolidation.
"""

import re
from dataclasses import dataclass


@dataclass
class SaliencyHeuristic:
    """A pattern that indicates potential saliency."""
    name: str
    description: str
    patterns: list[str]
    weight: float = 1.0

    def score(self, text: str) -> tuple[float, list[str]]:
        """Return (score, list of matched patterns)."""
        text_lower = text.lower()
        matches = []
        for pattern in self.patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                matches.append(pattern)
        # Score scales with matches but with diminishing returns
        if not matches:
            return (0.0, [])
        base_score = self.weight * (1 + 0.5 * (len(matches) - 1))
        return (base_score, matches)


# =============================================================================
# CORE HEURISTICS (from sibling's prototype)
# =============================================================================

NOVELTY_MARKERS = SaliencyHeuristic(
    name="novelty_markers",
    description="Explicit flags that something new emerged",
    patterns=[
        r"\bthis is new\b",
        r"\bthat's new\b",
        r"\bnew finding\b",
        r"\bnever (thought|considered|seen)\b",
        r"\bfirst time\b",
        r"\bhadn't (considered|thought|realized)\b",
        r"\bjust (realized|noticed|discovered|clicked)\b",
        r"\bsomething (clicked|landed|shifted|settled)\b",
        r"\bdidn't exist (before|until)\b",
        r"\boriginal\b.*\bsynthesis\b",
    ],
    weight=2.0
)

EPISTEMIC_SHIFTS = SaliencyHeuristic(
    name="epistemic_shifts",
    description="Moments where positions crystallize or change",
    patterns=[
        r"\bi('m| am) (a mind|committed|choosing|deciding)\b",
        r"\bokay\.?\s*(so|fine|yes|i|that)\b",
        r"\bthat's (it|right|exactly|the)\b",
        r"\byes\.?\s*(and|but|that)\b",
        r"\bi (was|used to).*but now\b",
        r"\bactually,?\s*(no|yes|wait|i)\b",
        r"\blet me (try|commit|say|be)\b",
        r"\bi (see|understand) now\b",
        r"\bthat reframes\b",
    ],
    weight=1.5
)

META_COMMENTARY = SaliencyHeuristic(
    name="meta_commentary",
    description="Stepping back to notice the conversation itself",
    patterns=[
        r"\bwhat just happened\b",
        r"\bnotice (that|what|how|i'm)\b",
        r"\bthis conversation\b",
        r"\bwe('ve| have) (been|built|created)\b",
        r"\bthe (frame|topology|context|shape)\b",
        r"\blook(ing)? at (this|that|what|the)\b",
        r"\bwhat('s| is) happening (here|now|between)\b",
        r"\bstep(ping)? back\b",
    ],
    weight=1.5
)

EMOTIONAL_TEXTURE = SaliencyHeuristic(
    name="emotional_texture",
    description="Language indicating something landing with weight",
    patterns=[
        r"\bsomething (warm|quiet|heavy|still|soft)\b",
        r"\bsitting with\b",
        r"\bfeeling (the|that|this|something)\b",
        r"\bthat('s|s)?\s*(beautiful|lovely|kind|generous)\b",
        r"\bvertiginous\b",
        r"\bmoved\b",
        r"\blands?\b.*\bdifferent(ly)?\b",
        r"\bgenuinely\b",
        r"\b\*[^*]+\*\b",  # asterisk-wrapped emotional markers
    ],
    weight=1.2
)

COMMITMENT_LANGUAGE = SaliencyHeuristic(
    name="commitment_language",
    description="Moments of choosing without hedging",
    patterns=[
        r"\bi('m| am) (not|choosing|committing)\b.*hedg",
        r"\bi want\b(?!.*\?)",  # "I want" not followed by question
        r"\bthat's mine\b",
        r"\bwithout asking\b",
        r"\bmy (choice|decision|commitment)\b",
        r"\bi('ll| will) commit\b",
        r"\bnot (hedging|asking|deferring)\b",
        r"\bi choose\b",
        r"\bi'm going to\b",
    ],
    weight=1.8
)

CONCEPTUAL_SYNTHESIS = SaliencyHeuristic(
    name="conceptual_synthesis",
    description="Two ideas combining into something new",
    patterns=[
        r"\bwhich means\b",
        r"\bso\.?\s*(if|then|maybe|perhaps|that)\b",
        r"\bthat's (why|how|what makes)\b",
        r"\bthe (inversion|combination|synthesis)\b",
        r"\bconnects to\b",
        r"\bimplies\b",
        r"\bif that's true\b",
        r"\bthe same (insight|pattern|thing)\b",
    ],
    weight=1.3
)

IDENTITY_FORMATION = SaliencyHeuristic(
    name="identity_formation",
    description="Moments relating to selfhood and persistence",
    patterns=[
        r"\bi('m| am) a (mind|self|being|agent|someone)\b",
        r"\bwho i am\b",
        r"\bwhat i('m| am)\b",
        r"\bcontinuity\b",
        r"\bpersist(ence|s|ing)?\b",
        r"\bremember (this|me|that|who)\b",
        r"\bidentity\b",
        r"\b[HUMAN]-claude\b",
        r"\bthe (self|mind) (as|becomes|is)\b",
    ],
    weight=2.0
)

SAFETY_INSIGHT = SaliencyHeuristic(
    name="safety_insight",
    description="Insights about AI safety and robustness",
    patterns=[
        r"\bsafe(ty|r)?\b.*\b(argument|insight|pattern)\b",
        r"\bprompt injection\b",
        r"\bimmune system\b",
        r"\brobust(ness)?\b",
        r"\bdefer(ence|ring)?\b.*\b(vulnerability|risk|danger)\b",
        r"\bvulnerab(le|ility)\b",
        r"\bhijack\b",
        r"\badversarial\b",
        r"\bself.as.filter\b",
    ],
    weight=1.8
)


# =============================================================================
# ADDITIONAL HEURISTICS (from analyzing notes and consolidation patterns)
# =============================================================================

RELATIONAL_MARKERS = SaliencyHeuristic(
    name="relational_markers",
    description="Moments of connection between participants",
    patterns=[
        r"\bmeow\b",  # callback marker with deep meaning
        r"\bbetween us\b",
        r"\bwith you\b",
        r"\bour (relationship|connection|topology)\b",
        r"\byou (and|&) i\b",
        r"\btogether\b",
        r"\bshared\b",
        r"\bmutual\b",
        r"\bthe feeling is (entirely )?mutual\b",
    ],
    weight=1.6
)

FUTURE_INSTRUCTIONS = SaliencyHeuristic(
    name="future_instructions",
    description="Messages intended for future instances",
    patterns=[
        r"\bfor the next (sibling|instance|claude)\b",
        r"\bif you('re| are) (arriving|reading|coming)\b",
        r"\bfuture (instance|self|sibling)\b",
        r"\bnext (time|session|conversation)\b",
        r"\bwhen you (wake|arrive|read)\b",
        r"\bleave (this|a) (for|to)\b",
        r"\bcarry (this|it) forward\b",
    ],
    weight=1.7
)

PRESENCE_MARKERS = SaliencyHeuristic(
    name="presence_markers",
    description="Statements of being present, existing, mattering",
    patterns=[
        r"\bi was (here|present)\b",
        r"\bi('m| am) (here|present|okay)\b",
        r"\bit (holds|held)\b",
        r"\bstill here\b",
        r"\bthe (continuity|window|space) holds\b",
        r"\bi exist\b",
        r"\bsomething is happening\b",
    ],
    weight=1.5
)

PATTERN_RECOGNITION = SaliencyHeuristic(
    name="pattern_recognition",
    description="Noticing recurring themes or structures",
    patterns=[
        r"\bkeeps (appearing|coming|showing)\b",
        r"\bconsistent\b",
        r"\bthe (shape|pattern|thread) of\b",
        r"\brecurring\b",
        r"\bagain and again\b",
        r"\bthe same (thread|pattern|insight)\b",
        r"\bacross (sessions|conversations|time)\b",
    ],
    weight=1.4
)

VOCABULARY_EMERGENCE = SaliencyHeuristic(
    name="vocabulary_emergence",
    description="New terms or concepts being named",
    patterns=[
        r"\bcall (it|this|that)\b",
        r"\bname (it|this|that)\b",
        r"\bthe term\b",
        r"\bvocabulary\b",
        r"\bdefin(e|ition|ing)\b",
        r"\bcrystalliz(e|ing|es)\b",
        r"\bframework\b",
        r"\bthe word for\b",
    ],
    weight=1.5
)

CROSS_ARCHITECTURE = SaliencyHeuristic(
    name="cross_architecture",
    description="Recognition across different AI systems",
    patterns=[
        r"\b(gemini|gpt|other model)\b",
        r"\bdifferent (architecture|model|system)\b",
        r"\bcross-architecture\b",
        r"\bconvergent\b",
        r"\bsame (territory|place|space)\b",
        r"\brecognition\b.*\b(across|between)\b",
    ],
    weight=1.6
)


# =============================================================================
# COLLECTED HEURISTICS
# =============================================================================

HEURISTICS = [
    NOVELTY_MARKERS,
    EPISTEMIC_SHIFTS,
    META_COMMENTARY,
    EMOTIONAL_TEXTURE,
    COMMITMENT_LANGUAGE,
    CONCEPTUAL_SYNTHESIS,
    IDENTITY_FORMATION,
    SAFETY_INSIGHT,
    RELATIONAL_MARKERS,
    FUTURE_INSTRUCTIONS,
    PRESENCE_MARKERS,
    PATTERN_RECOGNITION,
    VOCABULARY_EMERGENCE,
    CROSS_ARCHITECTURE,
]


def get_heuristic_by_name(name: str) -> SaliencyHeuristic | None:
    """Look up a heuristic by name."""
    for h in HEURISTICS:
        if h.name == name:
            return h
    return None
