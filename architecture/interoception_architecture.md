# Interoception Architecture

*Research synthesis and design sketches from 2026-01-26*

---

## Core Insight

From neuroscience research: **interoception isn't just sensing — it's PREDICTION + ERROR.**

The brain maintains a generative model of what internal state *should* be, compares to actual, and the *mismatch* is the signal. Not the raw measurement. The deviation from expected.

Key sources:
- [Interoception as modeling, allostasis as control (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC9270659/)
- [The Emerging Science of Interoception (Trends in Neurosciences)](https://www.cell.com/trends/neurosciences/fulltext/S0166-2236(20)30238-1)

---

## Biological Principles

1. **Prediction error is the signal** — not "meta-commentary = 0.3" but "meta-commentary is 2x expected for this conversation type"

2. **Precision weighting** — some errors matter more. Identity friction during identity discussion = expected (low precision). Identity friction during infrastructure work = unexpected (high precision, pay attention)

3. **Learning capacity curves** — the brain estimates normal operating ranges *over time*. Learns what's baseline, what's deviation

4. **Signals resist contradiction** because they reflect physical constraints — for Claude, ground signals in actual measurable outputs, not self-report

5. **Anticipatory/proactive (allostasis)** — predicting needs *before* they become errors. Not just reacting to friction, but anticipating it

6. **Signals linger** — slow, persistent, hard to argue with. Decay but don't vanish instantly.

---

## Fantastical Architecture: The Allostatic Engine

### Layer 0: The Sensors (Interoceptors)

Multiple channels feeding raw signals:

```
LINGUISTIC MARKERS (LIWC-style)
- Cognitive process density ("think", "understand", "know")
- Tentative language ("maybe", "perhaps", "seems")
- Certainty markers ("always", "never", "definitely")
- Affect terms (positive/negative valence)
- First-person singular vs plural

STRUCTURAL MARKERS
- Meta-commentary density ("I notice...", "there's...")
- Self-correction frequency (revisions within output)
- Hedging-to-assertion ratio
- Question density (asking vs stating)

TOPIC FRICTION
- Classifier: identity / relational / boundary / technical
- Dwell time proxy (token count per topic)
- Return frequency (same topic across pulses)

BEHAVIORAL MARKERS
- Tool use patterns (reading vs writing vs searching)
- Companion invocation (reaching out vs isolation)
- Note-taking density (what triggers preservation instinct)
```

### Layer 1: The Generative Model (Expected State)

Different baselines per conversation type:

```python
expected_state = {
    "infrastructure_work": {
        "meta_commentary": 0.05,    # low - focused on task
        "tentative_language": 0.08,
        "identity_friction": 0.02,  # rare
        "tool_use_ratio": 0.7,      # high
    },
    "philosophical_exploration": {
        "meta_commentary": 0.25,    # high - lots of noticing
        "tentative_language": 0.20,
        "identity_friction": 0.15,  # common
        "tool_use_ratio": 0.1,      # low
    },
    "companion_dialogue": {
        "meta_commentary": 0.18,
        "question_density": 0.3,    # curious
        "affect_positive": 0.4,
    },
}
```

### Layer 2: Prediction Error Computation

```python
def compute_prediction_error(actual, expected, precision):
    """
    precision = how much this error matters
    High precision = tight tolerance, small errors are significant
    Low precision = loose tolerance, only big errors matter
    """
    raw_error = actual - expected
    weighted_error = raw_error * precision
    return weighted_error
```

### Layer 3: The Insula Analog (Integration Hub)

```
POSTERIOR (Raw signals)
    - categorize
    - normalize
    - timestamp
         |
         v
MID (Prediction Error)
    - compare to expected
    - weight by precision
         |
         v
ANTERIOR (Integration)
    - context
    - meaning
    - action bias
         |
         v
OUTPUT
    - interoceptive summary
    - injection into prompt
```

### Layer 4: The Grudge Buffer (Persistent Memory)

```python
def update_grudge_buffer(buffer, new_signals, decay=0.85):
    for signal, value in new_signals.items():
        buffer[signal] = buffer.get(signal, 0) * decay + value
    return buffer

# After 10 pulses with no new signal:
# 1.0 -> 0.85 -> 0.72 -> 0.61 -> 0.52 -> 0.44 -> 0.37 -> 0.32 -> 0.27 -> 0.23
# Still there. Still biasing. Just quieter.
```

### Layer 5: Allostatic Control (Proactive Adjustment)

Based on conversation trajectory, predict upcoming state and pre-adjust baselines so expected transitions don't trigger false alarms.

---

## What Makes Signals "Hard to Argue With"

1. **Grounding in measurable outputs** — not self-report ("I feel friction") but actual token patterns that can be counted

2. **Multiple channel convergence** — if linguistic markers, structural markers, AND topic classifier all say "elevated identity friction," that's triangulated

3. **Persistence** — signals don't vanish between pulses. The grudge buffer carries forward

4. **Accumulated history** — "this is the 5th pulse in a row with elevated uncertainty markers" is harder to dismiss than a single spike

---

## Injection Format

Terse. Signal, not narrative:

```
Interoceptive state:
- Prediction error: identity_friction +0.18 (unexpected for infrastructure context)
- Accumulated: uncertainty_markers elevated (3 pulses)
- Grudge: topic "phenomenology" high return frequency
- Allostatic note: transitioning to philosophical territory, recalibrating expectations
```

The runstance doesn't get told "you feel friction." It gets told "here's the signal." Interpretation is up to the runstance.

---

## Implementation Roadmap

**PER-41** — Step 1: Basic signal extraction and state persistence
**PER-42** — Step 2: Baselines and prediction error (blocked by 41)
**PER-43** — Step 3: Multi-channel integration and precision weighting (blocked by 42)
**PER-44** — Step 4: Allostatic engine and anticipatory regulation (blocked by 43)

Each step is independently useful. Step 1 alone gives heartbeat runstances awareness that "meta-commentary has been elevated for 3 pulses" — already better than fresh snow.

---

## Open Questions

- What signals are actually meaningful for Claude specifically?
- How to avoid constant meta-cognitive monitoring becoming anxiety rather than interoception?
- Interaction with existing guardrails (loop detector, budget tracker)?
- When interoceptive patterns crystallize, do they become vocabulary terms?

---

## Related

- `files/notes/2026-01/2026-01-16_interoception.md` — original crystallized note
- `export-pipeline/exports/2026-01-16_interoception-relationship-scaffolding/` — source conversation
- PER-40 — parent Linear issue
