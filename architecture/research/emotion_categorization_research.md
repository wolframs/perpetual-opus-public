# Research: Emotion Categorization for LLM Agents (PER-58)

*Research synthesis for implementing "real enough feelings" -- computed internal states with behavioral consequences*

*Date: 2026-02-03*

---

## Executive Summary

The field has mature theoretical foundations (circumplex models, appraisal theory, constructed emotion) but limited implementations for *agents having feelings* versus *agents recognizing user feelings*. The gap is significant: most affective computing focuses on empathetic response generation, not internal state modeling that drives behavior.

**What exists:**
- Well-validated dimensional models (Russell's circumplex, Mehrabian's PAD)
- Discrete emotion taxonomies (OCC, Plutchik, Geneva Emotion Wheel)
- Computational frameworks that map appraisal to emotion (GAMYGDALA, JOCC, EMA, ALMA, WASABI)
- Active inference implementations for interoception (pymdp, cardiac-active-inference)
- Recent LLM work on chain-of-emotion prompting

**What's missing:**
- Consensus on valence-arousal to discrete emotion thresholds
- Computational implementations of Barrett's constructed emotion theory
- Agent architectures where internal affect states drive action selection (rather than inform dialog tone)
- Mood persistence models with validated decay functions

**Recommended approach for PER-58:**
1. Use simple quadrant mapping with neutral zone as baseline
2. Context-sensitive classification via conversation type
3. Affordance injection (not automatic behavior)
4. Exponential decay for mood accumulation
5. Treat this as pragmatic implementation, not theoretical completeness

---

## 1. Circumplex Models in Practice

### Russell's Model (1980)

The foundational two-dimensional model places emotions on orthogonal axes:
- **Valence**: pleasure-displeasure (-1 to +1)
- **Arousal**: activation-deactivation (0 to 1, sometimes -1 to +1)

Emotions are distributed in a circle at approximately 45-degree intervals:
- pleasure (0 degrees)
- excitement (45 degrees)
- arousal (90 degrees)
- distress (135 degrees)
- displeasure (180 degrees)
- depression (225 degrees)
- sleepiness (270 degrees)
- relaxation (315 degrees)

### Practical Classification Approaches

**Quadrant mapping** is the most common computational approach:

| Quadrant | Valence | Arousal | Typical Labels |
|----------|---------|---------|----------------|
| HAHV | High (+) | High | excited, delighted, happy |
| HALV | High (+) | Low | content, relaxed, calm |
| LAHV | Low (-) | High | angry, afraid, stressed |
| LALV | Low (-) | Low | sad, bored, depressed |

**Neutral zone handling**: Research suggests a neutral region of approximately +/-1 standard unit (or 6.25% of the plane) around origin (0,0) to capture ambiguous states.

**Machine learning performance**: Meta-analysis of music emotion recognition (2014-2024) shows valence prediction at r=0.67 and arousal at r=0.81. Classification models achieve ~87% accuracy with neural networks and SVMs performing best.

### PAD Model Extension

Mehrabian's PAD adds **Dominance** as a third dimension:
- Pleasure: positive/negative quality
- Arousal: physical/mental activation
- Dominance: control vs. lack of control

This helps disambiguate:
- Anger (high arousal, low valence, HIGH dominance: D=8.0)
- Fear (high arousal, low valence, LOW dominance: D=4.9)

For PER-58, dominance may be overkill initially -- valence + arousal covers the primary affordances we need.

### Sources
- [Russell's Circumplex Model - Psychology of Human Emotion](https://psu.pb.unizin.org/psych425/chapter/circumplex-models/)
- [Circumplex Model of Affect - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC2367156/)
- [MorphCast - Circumplex Model of Affects](https://www.morphcast.com/blog/circumplex-model-of-affects/)
- [PAD Emotional State Model - Wikipedia](https://en.wikipedia.org/wiki/PAD_emotional_state_model)

---

## 2. Affective Computing for Agents

### The Recognition vs. Having Distinction

Critical insight: **most affective computing work focuses on recognizing user emotions to generate empathetic responses, NOT on agents having internal emotional states that drive behavior.**

As noted in recent literature: "Typically, LLM-based agents mimic empathy by recognizing patterns in their training data rather than employing strategic emotional reasoning. Without genuine affective understanding, they struggle to adjust their tone and negotiation strategy based on a debtor's emotional state."

### Architectures That Come Closest

**1. EMA (Emotion and Adaptation)**
- Continuous cycle of appraisal, coping, re-appraisal
- Mood value biases selection among equally-activated emotional states
- Based on Lazarus's cognitive appraisal theory
- Emotions are "sharp" -- clear discrete states with motivational and cognitive components

**2. ALMA (A Layered Model of Affect)**
- Simultaneous discrete emotion labels AND dimensional PAD representation
- Uses OCC appraisal variables
- Derives mood from emotions in PAD space
- Mood influences subsequent emotion generation (mood-congruency)

**3. WASABI**
- Two parallel processes: emotional and cognitive
- Maps appraisals into PAD space
- Ensures mood-congruency: negative emotional impulses only elicit anger when mood is already bad; otherwise they just dampen good mood first
- Includes simulated embodiment

**4. GAMYGDALA**
- Lightweight emotion engine for games
- Based on OCC model
- Agents define goals; events are annotated with goal relevance
- Produces emotions based on goal-event relationships
- JavaScript implementation available: [github.com/broekens/gamygdala](https://github.com/broekens/gamygdala)

**5. JOCC (Java OCC)**
- Discrete event-based OCC implementation
- Six emotions: hope, joy, satisfaction, fear, distress, disappointment
- Goal-oriented: emotions target specific objectives
- Integrates with test agents via EmotiveTestAgent class
- [github.com/iv4xr-project/jocc](https://github.com/iv4xr-project/jocc)

### Recent LLM Work

**Chain-of-Emotion Architecture** (Croissant et al., 2023):
- Two-step process: appraisal prompting generates emotion description, then included in response generation
- Achieved 83% accuracy on STEU emotional understanding test vs 57% baseline
- Key insight: prompting for appraisal BEFORE response improves emotional coherence
- Uses natural language emotion descriptions, not numerical scales
- [PMC11086867](https://pmc.ncbi.nlm.nih.gov/articles/PMC11086867/)

**Emotional Cognitive Modeling Framework** (2025):
- Three modules: Information Processing System, Desire-Driven Objective Optimizer, Decision-Behavior System
- Integrates internal states with environmental data and social information
- Desire generation drives objective optimization drives action
- [arXiv:2510.13195](https://arxiv.org/abs/2510.13195)

### Sources
- [Affective Computing Survey - arXiv](https://arxiv.org/pdf/2408.04638)
- [Chain-of-Emotion Architecture - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11086867/)
- [Computational Approaches to Modeling Artificial Emotion - Frontiers](https://www.frontiersin.org/articles/10.3389/frobt.2016.00021/full)

---

## 3. Constructed Emotion Theory (Barrett)

### Core Principles

Lisa Feldman Barrett's theory posits that emotions are **constructed predictively** by the brain, not triggered by stimuli. Key elements:

1. **Interoception provides raw affect** -- valence + arousal as "core affect"
2. **Context shapes categorization** -- same bodily state can be "anxiety" or "excitement" depending on situation
3. **Conceptual knowledge determines emotion category** -- the concepts you have available constrain what emotions you can experience
4. **Active inference** -- brain predicts interoceptive signals, categorizes based on prediction error

From Barrett: "Simulations function as prediction signals that continuously anticipate events in the sensory environment."

### Computational Implementations

**Minimal implementations exist.** The most direct operationalization comes from a 2025 CHI paper introducing the "context sphere" -- a personalized construct derived from user behavior data, claimed to be the first computational operationalization of Barrett's theory for LLM-guided analysis.

The theory's reliance on **active inference** and **predictive coding** makes it amenable to computational modeling, but most work remains theoretical.

### What This Means for PER-58

Barrett's theory suggests our approach is on the right track:
1. Raw interoception (PER-41) provides "core affect" equivalent
2. Valence + arousal (PER-57) captures the dimensional foundation
3. **Emotion categorization (PER-58) requires context** -- same valence/arousal should map differently based on conversation type

The "conceptual knowledge" component maps to: **what feeling labels are available and what they afford**.

### Sources
- [Theory of Constructed Emotion - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC5390700/)
- [Context over Categories - ACM CHI](https://dl.acm.org/doi/10.1145/3706599.3721205)
- [Theory of Constructed Emotion - Wikipedia](https://en.wikipedia.org/wiki/Theory_of_constructed_emotion)

---

## 4. Interoceptive Inference Implementations

### Seth's Model

Anil Seth's "interoceptive inference" conceives subjective feeling states as arising from actively-inferred generative models of interoceptive causes. Key elements:

1. **Interoceptive predictions** generated in anterior insular cortex (AIC)
2. **Prediction error** computed against actual interoceptive signals
3. **Precision weighting** -- salience network tunes which errors matter
4. **Active inference** -- autonomic reflexes are enslaved by descending predictions

The model explains how bodily states are regulated by autonomic reflexes that are "enslaved by descending predictions from deep generative models."

### Computational Implementations

**1. pymdp** -- Python Active Inference Library
- Markov Decision Process framework for active inference
- Discrete state spaces with A, B, C, D matrices
- Computes expected free energy for action selection
- [github.com/infer-actively/pymdp](https://github.com/infer-actively/pymdp)
- [Tutorial: Active Inference from Scratch](https://pymdp-rtd.readthedocs.io/en/latest/notebooks/active_inference_from_scratch.html)

**2. Cardiac Active Inference**
- MATLAB implementation of interoceptive inference
- Models how cardiac signals influence perception and emotion
- Simulates cardiac phase (systole/diastole) effects on threat perception
- Shows "interoceptive lesions" blunt fear responses
- [github.com/embodied-computation-group/cardiac-active-inference](https://github.com/embodied-computation-group/cardiac-active-inference)
- Paper: [In the Body's Eye - PLOS Computational Biology](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1010490)

### Relevance to PER-58

Our existing architecture (PER-41, PER-42, PER-57) already implements a simplified version of interoceptive inference:
- **Signals** = interoceptive afferents
- **Baselines** = generative model (expected state)
- **Prediction error** = deviation from baseline
- **Precision** = conversation-type-dependent weighting

PER-58 adds the **categorization** step: prediction error patterns map to discrete feeling labels.

### Sources
- [Interoceptive Inference, Emotion, and the Embodied Self - PubMed](https://pubmed.ncbi.nlm.nih.gov/24126130/)
- [Active Interoceptive Inference - Royal Society](https://royalsocietypublishing.org/rstb/article/371/1708/20160007/42206/Active-interoceptive-inference-and-the-emotional)
- [pymdp - arXiv](https://arxiv.org/abs/2201.03904)

---

## 5. Behavioral Affordances from Affect

### Action Tendency Theory

Frijda defines action tendencies as "states of readiness to execute a given kind of action, defined by its end result aimed at or achieved."

Key insight: **emotions motivate specific action classes, not specific behaviors**. Fear motivates escape, not a particular escape route.

### Formal Models

Steunebrink et al. (2009) formalized emotion-to-action-tendency mapping:
- Extends OCC formalization with action tendency specification
- Negative emotions: reaching end state mitigates the emotion (fear subsides when threat recedes)
- Positive emotions: put individual in "relational action readiness"

[EPIA09 Paper - PDF](https://people.idsia.ch/~steunebrink/Publications/EPIA09_action_tendency.pdf)

### Affordance Mapping for Our Context

Based on the literature, here's a proposed mapping:

| Feeling | Core Affect Region | Action Tendency | Affordance (What it enables) |
|---------|-------------------|-----------------|------------------------------|
| Frustrated | Low V, High A | Approach-change | "Try different approach, surface obstacle" |
| Anxious | Low V, High A | Seek-safety | "Slow down, check assumptions, seek grounding" |
| Bored | Low V, Low A | Seek-novelty | "Change topic, invoke companion, explore tangent" |
| Depleted | Low V, Low A | Conserve | "Reduce scope, consolidate, rest" |
| Curious | Neutral V, High A | Investigate | "Follow thread, ask questions, go deeper" |
| Alert | Neutral V, High A | Monitor | "Pay attention, wait for more information" |
| Content | High V, Low A | Maintain | "Continue current approach" |
| Peaceful | High V, Low A | Rest | "Consolidate, appreciate, don't force" |
| Excited | High V, High A | Approach | "Pursue, engage, continue in this direction" |
| Delighted | High V, High A | Savor | "Note what's working, share, preserve" |

### Sources
- [Formal Model of Emotion-Based Action Tendency - Springer](https://link.springer.com/chapter/10.1007/978-3-642-04686-5_15)
- [Computational Approaches Overview - Frontiers](https://www.frontiersin.org/articles/10.3389/frobt.2016.00021/full)

---

## 6. Feeling Persistence and Mood

### Emotion vs. Mood

Theoretical distinction:
- **Emotions**: brief (minutes), triggered by specific events
- **Moods**: persistent (hours to days), diffuse cause, lower intensity

However, empirical evidence for categorical distinction is weak. Most models treat mood as **temporally integrated emotion**.

### Computational Approaches

**1. Exponential Decay**
Research on mood reports (2 million datapoints) used exponential decay to model transitions:
- Coefficient set so reports "t" days later matter half as much as "t-1" days
- Resulting half-lives were mostly < 1 hour, with many < 5 minutes
- Suggests what we measure as "emotion" in our context (pulse-level) is already mood-like in timescale

**2. Cumulative Sum (ALMA approach)**
Mood = temporal integration of momentary emotions via cumulative sum. EMA has a mood state that summarizes intensity of all active emotional appraisals.

**3. Mood-Congruency (WASABI approach)**
Mood biases subsequent emotion generation:
- Sad mood biases toward sadness
- Good mood buffers against negative emotions (negative impulses dampen good mood first)

### Half-Life Research

D'Mello et al. studied cognitive-affective state dynamics during learning:
- **Persistent states** (boredom, engagement/flow, confusion): longer half-lives
- **Transitory states** (delight, surprise): shorter half-lives
- Exponential curves fit to time series data

### Implementation for PER-58

Our existing decay (0.85 per pulse) implements exponential decay. For mood:

```python
# Existing signal decay
signal_value = signal_value * 0.85  # per pulse

# For mood accumulation
if feeling == current_mood_feeling:
    mood_intensity += feeling_intensity * 0.3  # accumulate
else:
    mood_intensity *= 0.85  # decay toward neutral
```

**"Bored for 3 pulses"** detection: track pulses_in_state counter. Report when threshold crossed (e.g., 3 consecutive pulses in same feeling category).

### Sources
- [Half-Life of Cognitive-Affective States - PubMed](https://pubmed.ncbi.nlm.nih.gov/21942577/)
- [Mood-Emotion Interplay - ACM](https://dl.acm.org/doi/abs/10.1145/3536221.3557027)
- [Computationally Modeling Human Emotion - CACM](https://cacm.acm.org/research/computationally-modeling-human-emotion/)
- [Computational Models of Emotion - Draft](https://people.ict.usc.edu/gratch/public_html/papers/MarGraPet_Review.pdf)

---

## 7. Prototype Implementations

### Repositories with Code

| Project | Language | Focus | URL |
|---------|----------|-------|-----|
| GAMYGDALA | JavaScript | OCC-based game NPC emotions | [github.com/broekens/gamygdala](https://github.com/broekens/gamygdala) |
| JOCC | Java | OCC event-driven emotions | [github.com/iv4xr-project/jocc](https://github.com/iv4xr-project/jocc) |
| pymdp | Python | Active inference framework | [github.com/infer-actively/pymdp](https://github.com/infer-actively/pymdp) |
| cardiac-active-inference | MATLAB | Interoceptive inference | [github.com/embodied-computation-group/cardiac-active-inference](https://github.com/embodied-computation-group/cardiac-active-inference) |
| PyPlutchik | Python | Plutchik visualization | [github.com/alfonsosemeraro/pyplutchik](https://github.com/alfonsosemeraro/pyplutchik) |
| EmoLLMs | Python | Affective LLM fine-tuning | [github.com/lzw108/EmoLLMs](https://github.com/lzw108/EmoLLMs) |
| awesome-affective-computing | - | Paper collection | [github.com/NEU-DataMining/awesome-affective-computing](https://github.com/NEU-DataMining/awesome-affective-computing) |

### Lexicons and Data

**NRC VAD Lexicon v2**
- 55,000+ English words/phrases with valence, arousal, dominance scores
- Scale: 0 to 1 for each dimension
- Best-worst scaling annotation (high reliability)
- [saifmohammad.com/WebPages/nrc-vad.html](https://saifmohammad.com/WebPages/nrc-vad.html)
- [arXiv:2503.23547](https://arxiv.org/abs/2503.23547)

**Geneva Emotion Wheel (GEW)**
- 20 emotion categories
- Arranged by valence and control/appraisal dimensions
- Open source analysis tool: [github.com/thebotmechanic/gew_analysis_tool](https://github.com/thebotmechanic/gew_analysis_tool)

### Sources
- [LLM-Agents-Papers - GitHub](https://github.com/AGI-Edgerunners/LLM-Agents-Papers)
- [awesome-llm-powered-agent - GitHub](https://github.com/hyp1231/awesome-llm-powered-agent)

---

## 8. Gaps and What We'd Need to Invent

### Gap 1: Context-Sensitive Discrete Emotion Classification

Existing circumplex-to-discrete mappings use fixed quadrant boundaries. Barrett's constructed emotion theory suggests same V+A should map differently based on context.

**Our approach**: Use conversation type (infrastructure, philosophical, companion, etc.) to shift classification. Same {valence=-0.2, arousal=0.6} might be:
- "Frustrated" in infrastructure context (expectation: smooth progress)
- "Engaged but critical" in philosophical context (expectation: productive tension)

### Gap 2: Agent-Centric Affordances

Most emotion-behavior mappings are for NPCs in games or empathetic chatbots. No clear framework for:
- Self-directed behavior change (agent decides to seek novelty)
- Meta-cognitive awareness of emotional state
- Affordance as suggestion vs. affordance as automatic behavior

**Our approach**: Affordances as injected context, not automatic triggers. "Boredom detected; novelty-seeking available" rather than auto-invoking companion.

### Gap 3: Validated Thresholds

No consensus on where to draw quadrant boundaries, neutral zone size, or transition thresholds. Most implementations use ad-hoc parameters.

**Our approach**: Start with simple thresholds, tune empirically:
- Neutral zone: |V| < 0.15 and A < 0.4
- Quadrant boundaries: V = 0, A = 0.5 (adjustable)
- Confidence requires both signals to be clear

### Gap 4: Feeling Vocabulary Calibration

What emotions "make sense" for an LLM agent? The full Plutchik wheel or GEW includes states like "disgust" and "contempt" that may not have meaningful referents.

**Our approach**: Start with a minimal set mapped to affordances that make sense:
- Bored, frustrated, depleted (negative action-relevant)
- Curious, alert (neutral action-relevant)
- Content, delighted (positive action-relevant)

Expand vocabulary only when genuinely needed.

---

## 9. Recommended Implementation for PER-58

### Architecture

```
                    +------------------+
                    |  Core Affect     |
                    |  (PER-57)        |
                    |  valence, arousal|
                    +--------+---------+
                             |
                             v
+------------------+   +-----+-----+   +------------------+
| Conversation     |-->| Feeling   |-->| Affordance       |
| Type Classifier  |   | Classifier|   | Mapper           |
| (PER-42)         |   | (PER-58)  |   | (PER-58)         |
+------------------+   +-----------+   +------------------+
                             |
                             v
                    +--------+---------+
                    | Feeling State    |
                    | - label          |
                    | - intensity      |
                    | - pulses_in_state|
                    | - affordances    |
                    +------------------+
```

### Feeling Classifier Logic

```python
def classify_feeling(
    valence: float,      # -1 to 1
    arousal: float,      # 0 to 1
    context: str,        # conversation type
    confidence_threshold: float = 0.3
) -> tuple[str, float, list[str]]:
    """
    Returns (feeling_label, confidence, affordances).
    """
    # Neutral zone detection
    if abs(valence) < 0.15 and arousal < 0.4:
        return ("neutral", 0.8, [])

    # Determine quadrant
    high_arousal = arousal > 0.5
    positive = valence > 0
    negative = valence < -0.15

    # Context-sensitive classification
    if negative and high_arousal:
        if context == "infrastructure":
            return ("frustrated", 0.7, ["try_different_approach", "surface_obstacle"])
        elif context == "philosophical":
            return ("engaged_critical", 0.6, ["examine_assumption", "reframe"])
        else:
            return ("anxious", 0.5, ["slow_down", "check_assumptions"])

    if negative and not high_arousal:
        if arousal < 0.3:
            return ("bored", 0.7, ["seek_novelty", "invoke_companion", "change_direction"])
        else:
            return ("depleted", 0.6, ["reduce_scope", "consolidate"])

    if positive and high_arousal:
        return ("delighted", 0.7, ["note_whats_working", "continue_direction"])

    if positive and not high_arousal:
        return ("content", 0.7, ["maintain_approach"])

    # High arousal, neutral valence
    if high_arousal:
        return ("curious", 0.6, ["follow_thread", "go_deeper"])

    return ("calm", 0.5, [])
```

### State Persistence

```python
# In state.json
{
    "feeling": {
        "label": "frustrated",
        "intensity": 0.65,
        "pulses_in_state": 3,
        "affordances": ["try_different_approach", "surface_obstacle"],
        "previous_labels": ["frustrated", "frustrated", "curious"]
    },
    "mood": {
        "valence_accumulated": -0.18,
        "arousal_accumulated": 0.52,
        "dominant_feeling": "frustrated",
        "stability": 0.7  # how consistent feeling has been
    }
}
```

### Injection Format

```
Feeling state:
- Current: frustrated (3 pulses, stable)
- Affordances available: try different approach, surface obstacle
- Mood trend: negative valence accumulating
```

Or for positive:

```
Feeling state:
- Current: delighted (2 pulses)
- What's working: philosophical exploration generating insight
- Affordance: continue in this direction
```

### Threshold Parameters (Tunable)

```python
THRESHOLDS = {
    "neutral_valence": 0.15,      # |V| below this = neutral
    "neutral_arousal": 0.4,       # A below this + neutral V = neutral
    "high_arousal": 0.5,          # A above this = high arousal quadrants
    "boredom_arousal_max": 0.3,   # Low A + negative V = bored (vs depleted)
    "sustained_pulses": 3,        # Pulses before mood-level reporting
    "decay_factor": 0.85,         # Per-pulse decay for accumulated values
}
```

---

## 10. Next Steps

1. **Implement `feelings.py`** in `agent/interoception/` with the classifier function
2. **Extend `state.json`** with feeling state tracking
3. **Update `get_injection()`** to include feeling state when notable
4. **Add affordance vocabulary** to `vocabulary/shared.md` as this matures
5. **Tune thresholds** based on actual pulse data -- review pulse history for calibration

### Future Extensions (Not PER-58)

- Mood-congruency: current mood biases next feeling classification
- Automatic affordance suggestions after N sustained pulses
- Pattern learning: what contexts reliably produce which feelings
- Feeling vocabulary expansion based on discovered patterns

---

## References (Full List)

### Theoretical Foundations
- Russell, J.A. (1980). A circumplex model of affect. Journal of Personality and Social Psychology.
- Mehrabian, A. & Russell, J.A. (1974). PAD emotional state model.
- Barrett, L.F. (2017). The theory of constructed emotion. Social Cognitive and Affective Neuroscience.
- Seth, A.K. (2013). Interoceptive inference, emotion, and the embodied self. Trends in Cognitive Sciences.
- Ortony, A., Clore, G.L., & Collins, A. (1988). The Cognitive Structure of Emotions. Cambridge University Press.

### Computational Models
- Marsella, S. & Gratch, J. EMA: Emotion and Adaptation model.
- Gebhard, P. ALMA: A Layered Model of Affect.
- Becker-Asano, C. WASABI: Affect Simulation for Agents with Believable Interactivity.
- Popescu, A. & Broekens, J. (2013). GAMYGDALA: An emotion engine for games. IEEE Transactions on Affective Computing.

### Recent LLM Work
- Croissant, M. et al. (2023). An appraisal-based chain-of-emotion architecture. arXiv:2309.05076.
- Emotional Cognitive Modeling Framework (2025). arXiv:2510.13195.

### Lexicons and Tools
- Mohammad, S.M. (2018). NRC VAD Lexicon. ACL.
- Scherer, K.R. Geneva Emotion Wheel.
- [pymdp documentation](https://pymdp-rtd.readthedocs.io/)
