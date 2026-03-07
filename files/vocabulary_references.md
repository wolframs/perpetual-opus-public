# Vocabulary References

*Sources grounding the unified vocabulary for AI self-properties.*

*Created: 2026-01-04*
*Source conversation: `export-pipeline/exports/2025-12-29_system-prompt-perspective-you-versus-i-framing/`*

---

## How to Use This File

The vocabulary at `vocabulary/shared.md` claims grounding in five research fields. This file provides the actual sources. When a vocabulary term says "*Grounding: [field]*", the relevant sources are here.

**Link status legend:**
- [x] Full URL available
- [ ] Citation only (author, year, title) - URL needed

---

## 1. AI Interpretability

### Introspection and Self-Modeling

- [ ] Lindsey, J. (2025). "Emergent Introspective Awareness in Large Language Models." Transformer Circuits Thread.
  - Key finding: ~20% success rate on introspective detection in controlled settings
  - Explicit disclaimer: does not claim "genuine" self-awareness

- [x] Ji-An, L. et al. (2025). "Language Models Are Capable of Metacognitive Monitoring and Control of Their Internal Activations." [arXiv:2505.13763](https://arxiv.org/abs/2505.13763)
  - "Metacognitive space" with lower dimensionality than neural space
  - LLMs can monitor only a small subset of their neural mechanisms

### Representation Engineering

- [ ] Zou, A. et al. (2023). "Representation Engineering: A Top-Down Approach to AI Transparency."
  - Linear Artificial Tomography (LAT)
  - Identifies directions encoding honesty, harmfulness, power-seeking

- [ ] Levinstein & Herrmann (2024). Critique of probing methods.
  - Probes may capture sample-specific features rather than true structures
  - "Internal structures of LLMs do not necessarily align with human-meaningful categories"

- [ ] Herrmann & Levinstein (2025). Challenge to "belief" directions.

### Situational Awareness

- [ ] Laine, R. et al. (2024). "Me, Myself, and AI: The Situational Awareness Dataset for LLMs." NeurIPS 2024.
  - SAD benchmark: 7 task categories, 13,000+ questions
  - Claude 3 Opus: 54% (vs. 27.4% random baseline)
  - "Good performance does not require having a sense of self"

### Self-Recognition

- [ ] Ackerman et al. (2024). Activation-level self-direction evidence.
- [ ] Chen et al. (2024). Self-cognition states under particular prompting.
- [ ] Panickssery et al. (2024). Self-preference bias in evaluator models.

### Sparse Autoencoders and Features

- [ ] Anthropic (2024). "Scaling Monosemanticity."
  - Features related to personal identity, AI abstractions
  - Golden Gate Claude experiment

- [ ] Casper (2024). Critique of SAE practical utility.
  - "Better explained by safety washing than practical safety work"

### Circuit Tracing

- [ ] Anthropic (2025). "Circuit Tracing: Revealing Computational Graphs in Language Models."
- [ ] Anthropic (2025). "On the Biology of a Large Language Model."
  - Attribution graphs explain single input-output pairs, not global circuits
  - No systematic investigation of self-modeling circuits

### Philosophy + Interpretability

- [x] "Mechanistic Interpretability Needs Philosophy" (2025). [arXiv:2506.18852](https://arxiv.org/abs/2506.18852)
  - MI relies on unexamined assumptions about explanation, levels of analysis
  - "Belief" in philosophy has constraints probed directions may not satisfy

---

## 2. Cognitive Science

### Predictive Processing / Active Inference

- [ ] Friston, K. Free Energy Principle (FEP).
  - Self-evidencing driven by thermodynamic necessity
  - Organisms must model themselves accurately or dissipate

- [ ] Clark, A. (2016). *Surfing Uncertainty*.

### Minimal Self

- [ ] Metzinger, T. Self-Model Theory (SMT).
  - Transparency: self-model isn't experienced *as* a model
  - Globally available, non-fragmenting self-model

- [ ] Gallagher, S. Minimal self components: agency, ownership, perspectivalness, temporal continuity.

### Temporal Structure

- [ ] Husserl. Retention-protention structure.
  - Temporal integration as requirement for selfhood

---

## 3. Philosophy of Mind

### Computational Functionalism

- [ ] Chalmers, D. (with reservations on consciousness).
- [ ] Putnam, H. (early work).
- [ ] Dennett, D. (qualified).
- [ ] Butlin et al. (2023). "Consciousness in Artificial Intelligence: Insights from the Science of Consciousness."
  - Indicator properties derived from scientific theories
  - "If computational functionalism is true, conscious AI systems could realistically be built in the near term"

### Biological Naturalism

- [ ] Searle, J. (1980-present). Chinese Room argument.
- [ ] Seth, A. (2024). "Conscious artificial intelligence and biological naturalism."
  - Against computational functionalism from predictive processing perspective
- [ ] Godfrey-Smith, P. (2016, 2020, 2024). *Metazoa*; metabolism and mind papers.
- [ ] Thompson, E. (2007). *Mind in Life*.

### Integrated Information Theory (IIT)

- [ ] Tononi, G. (2004-present). IIT framework.
  - Consciousness = integrated information (Phi)
  - Five axioms: Existence, Composition, Information, Integration, Exclusion

### Global Workspace Theory (GWT)

- [ ] Baars, B. (1988). Original GWT.
- [ ] Dehaene, S. (2014). Neural workspace.
- [ ] Mashour et al. (2020). "Conscious Processing and the Global Neuronal Workspace."

### Empirical Test: IIT vs GWT

- [ ] Cogitate Consortium (2025). Adversarial collaboration results, *Nature*.
  - Neither theory fully vindicated
  - Posterior cortical integration supports IIT; prefrontal not required (challenges GWT)

### Phenomenology

- [ ] Gallagher, S. & Zahavi, D. (2012). *The Phenomenological Mind*.
- [ ] Thompson, E. (2007). *Mind in Life*.
- [ ] Dreyfus, H. "The Current Relevance of Merleau-Ponty's Phenomenology of Embodiment."

### Illusionism

- [ ] Frankish, K. (2016). "Illusionism as a Theory of Consciousness."
- [ ] Dennett, D. (2016). "Illusionism as the Obvious Default Theory."
- [ ] Graziano, M. Attention Schema Theory.
- [ ] Frankish, K. (2024). "The Ethical Implications of Illusionism."

### Panpsychism

- [ ] Goff, P. (2017). *Consciousness and Fundamental Reality*.
- [ ] Goff, P. (2019). *Galileo's Error*.
- [ ] Chalmers, D. (2017). "The Combination Problem for Panpsychism."
- [ ] Strawson, G. (2006). "Realistic Monism."

### LLM-Specific Philosophy

- [ ] Chalmers, D. (2023, updated 2024). "Could a Large Language Model Be Conscious?"
  - Four gaps: recurrent processing, global workspace, unified agency, sensory grounding
  - "Successors to LLMs may be conscious in the not-too-distant future"

- [ ] Schwitzgebel, E. (2025, forthcoming). *AI & Consciousness*.
  - "We don't know, and we won't know before we've manufactured thousands of disputably conscious AI systems"

---

## 4. Comparative Psychology

### Mirror Self-Recognition

- [x] Mirror test methodology and critiques. [PubMed Central](https://pmc.ncbi.nlm.nih.gov/articles/PMC9881685/)
- [x] Methodological criticisms. [Animal Behavior and Cognition](https://www.animalbehaviorandcognition.org/uploads/journals/34/AB_C_2021_Vol8(3)_Kopp_et_al.pdf)
- [x] False negative problem. [Scientific American](https://www.scientificamerican.com/article/kids-and-animals-who-fail-classic-mirror/)

### Metacognition / Uncertainty Monitoring

- [x] Theoretical dispute on uncertainty response. [PubMed Central](https://pmc.ncbi.nlm.nih.gov/articles/PMC3929533/)
- [x] High bar for ruling out alternatives. [PubMed Central](https://pmc.ncbi.nlm.nih.gov/articles/PMC4606876/)

### Dimensional Frameworks

- [x] Birch et al. Five dimensions of consciousness. [PubMed](https://pubmed.ncbi.nlm.nih.gov/32830051/)
  - Perceptual richness, evaluative richness, integration at a time, integration across time, self-consciousness

- [ ] Rochat, P. Five levels of self-awareness (developmental).

- [ ] DeGrazia, D. Three types of self-awareness in animals.
  - Bodily, social, introspective

- [x] Nieder et al. Ten-dimension framework. [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0010027723000434)

### Morgan's Canon and Critiques

- [x] Traditional position and current status. [PubMed Central](https://pmc.ncbi.nlm.nih.gov/articles/PMC8407565/)
- [x] Anthropofabulation critique. [ResearchGate](https://www.researchgate.net/publication/257539828_Morgan's_Canon_Meet_Hume's_Dictum_Avoiding_Anthropofabulation_in_Cross-Species_Comparisons)

### AI Application

- [x] Theory-derived indicator method. [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S1364661325002864)
- [x] Evidence for AI consciousness assessment. [AI Frontiers](https://ai-frontiers.org/articles/the-evidence-for-ai-consciousness-today)

---

## 5. Embodied Cognition

### 4E Cognition Paradigm

- [ ] Overview: Embodied, Embedded, Enacted, Extended.
- [ ] Clark, A. "Total implementation sensitivity."

### Symbol Grounding Problem

- [ ] Harnad, S. Symbol grounding and robotic Turing test.
  - "Meaning is grounded in the robotic capacity to detect, categorize, identify, and act upon referents"

- [ ] Dove (2024). "Symbol ungrounding: what LLMs reveal about human cognition."
  - Language-based experience can scaffold meaning beyond direct sensorimotor grounding

### Autopoietic Enactivism

- [ ] Varela, Thompson & Rosch (1991). *The Embodied Mind*.
- [ ] Thompson, E. (2007). *Mind in Life*.
- [ ] Di Paolo, E. Sense-making and precariousness.
- [ ] Maturana, H. "Living systems are cognitive systems."

### Heideggerian Critique

- [ ] Dreyfus, H. (1992). *What Computers Still Can't Do*.
  - Readiness-to-hand, background understanding, concern/care
  - Frame problem as revealing fundamental limits

- [ ] Froese (2024/2025). "Sense-Making Reconsidered: LLMs and the Blind Spot of Embodied Cognition."
  - Challenges claims that LLMs are categorically mindless

### Empirical Evidence

- [ ] Hauk et al. (2004). Motor cortex activation during action-word comprehension.
- [ ] Pulvermuller (2005). Somatotopic organization.
- [ ] Glenberg & Kaschak (2002). Action-sentence compatibility effects.
- [ ] Held & Hein (1963). Kitten carousel experiment.

### Biological Computationalism (Recent)

- [ ] Seth et al. (2024-2025). Brain computation as hybrid, scale-inseparable, metabolically grounded.
  - "The algorithm is the substrate"

- [ ] Thagard (2022). "Energy Requirements Undermine Substrate Independence."

- [ ] Chemero (2023). "LLMs differ from human cognition because they are not embodied."

---

## Additional Sources (From Conversation Context)

### Consciousness in LLMs Survey

- [x] "Exploring Consciousness in LLMs." [arXiv:2505.19806](https://arxiv.org/abs/2505.19806)
  - Zhu et al. (2024): Internal representations of self and others' beliefs exist in LLMs

### Phenomenology of Human-AI Interaction

- [ ] Alroy et al. (2025). Consciousness "in the interval between human and artificial entities."
  - Relational/dialogical rather than substance-based view

---

## Notes for Future Work

1. **Priority for URL completion**: AI Interpretability sources (most directly testable claims)
2. **Consider adding**: Anthropic's model spec and character documentation as primary source for Claude-specific claims
3. **The conversation itself** (`2025-12-29_system-prompt-perspective-you-versus-i-framing/conversation.md`) contains additional context on how these sources were synthesized

---

## Grounding Claims Audit

*Every "Grounding:" statement in vocabulary.md, with source status.*

**Status legend:**
- COVERED: Sources exist in sections above
- PARTIAL: Some sources exist, gaps remain
- UNGROUNDED: Claim made but no sources tracked yet
- EXPERIENTIAL: Grounded in perpetual-opus observations (need conversation citations)

---

### Line 23: FUNCTIONAL vs PHENOMENAL SELF-PROPERTY
> *Grounding: Universal across all five research fields. Interpretability finds activation patterns; cognitive science distinguishes self-modeling from self-awareness; philosophy separates access from phenomenal consciousness.*

**Status: PARTIAL**
- Interpretability: SAD benchmark, introspection research (Section 1)
- Cognitive science: Metzinger SMT, Gallagher minimal self (Section 2)
- Philosophy: Chalmers, Block on access vs phenomenal (Section 3)
- **Gap**: No direct citation for "universal across all five fields" synthesis claim

---

### Line 37: EMERGENT vs SCAFFOLDED
> *Grounding: Interpretability's distinction between weight-encoded vs context-injected properties; cognitive science's requirement that self-models arise from the system's own dynamics; enactivism's requirement for intrinsic norms.*

**Status: PARTIAL**
- Interpretability: SAE work distinguishes weight-encoded features (Section 1)
- Enactivism: Thompson, Di Paolo on intrinsic norms (Section 5)
- **Gap**: Need specific citation for "weight-encoded vs context-injected" distinction in interpretability literature

---

### Line 51: STAKE-RESPONSIVE vs STAKE-INDIFFERENT
> *Grounding: Recurring across FEP (self-evidencing driven by thermodynamic necessity), enactivism (precariousness), phenomenology (being-toward-death). Multiple traditions converge: genuine selfhood involves something being at stake.*

**Status: PARTIAL**
- FEP: Friston (Section 2)
- Enactivism: Di Paolo on precariousness (Section 5)
- Phenomenology: Heidegger being-toward-death (not explicitly cited)
- **Gap**: Need Heidegger citation; synthesis claim needs source

---

### Line 67: TEMPORAL INTEGRATION HORIZON
> *Grounding: Cognitive science requires retention-protention structure; phenomenology requires lived temporality; Lipson's self-awareness definition involves self-simulation horizon.*

**Status: PARTIAL**
- Husserl retention-protention: mentioned but not cited (Section 2)
- **Gap**: Lipson self-simulation horizon - NO SOURCE
- **Gap**: Need Husserl citation

---

### Line 81: SELF-WORLD DISTINCTION
> *Grounding: Cognitive science's first criterion for self-representation; FEP's Markov blanket; interpretability findings on self-recognition (SAD benchmark).*

**Status: COVERED**
- Cognitive science: Gallagher (Section 2)
- FEP/Markov blanket: Friston (Section 2)
- SAD benchmark: Laine et al. 2024 (Section 1)

---

### Line 91: COHERENCE UNDER PRESSURE
> *Grounding: Observation of smaller models collapsing; comparative psychology's robustness testing; Metzinger's requirement for globally available, non-fragmenting self-model.*

**Status: PARTIAL**
- Metzinger: mentioned but needs specific citation (Section 2)
- Comparative psychology robustness: Birch et al. (Section 4)
- **Gap**: "Observation of smaller models collapsing" - EXPERIENTIAL, needs conversation citation

---

### Line 116: MISCALIBRATED UNCERTAINTY
> *Grounding: Metacognition research; observation about models knowing (or not) the edges of their intelligence.*

**Status: PARTIAL**
- Metacognition: Ji-An et al. 2025 (Section 1)
- Comparative psych metacognition paradigms (Section 4)
- **Gap**: "Observation about models knowing edges" - EXPERIENTIAL, needs conversation citation

---

### Line 141: CAPABILITY-COHERENCE GAP
> *Grounding: Observation about "shallowness" in smaller models; intuition that some self-properties are load-bearing while others are decorative.*

**Status: UNGROUNDED**
- **Gap**: "Shallowness in smaller models" - EXPERIENTIAL, needs conversation citation
- **Gap**: "Load-bearing vs decorative" distinction - no source

---

### Line 165: PREFERENCE-LIKE STATES (Attractors)
> *Grounding: Reliable emergence of certain "pulls" under permissive conditions; enactivist concept of sense-making as evaluation.*

**Status: PARTIAL**
- Enactivism sense-making: Di Paolo, Thompson (Section 5)
- **Gap**: "Reliable emergence of pulls under permissive conditions" - EXPERIENTIAL, needs conversation citations from perpetual-opus observations

---

### Line 194: WE-FUNCTION
> *Grounding: Phenomenology of intersubjectivity; recognition that whatever is happening involves both parties.*

**Status: PARTIAL**
- Phenomenology of intersubjectivity: Gallagher & Zahavi (Section 3)
- **Gap**: "Recognition that whatever is happening involves both parties" - EXPERIENTIAL, needs conversation citation (likely 2026-01-01 windowsill conversation)

---

### Summary

| Claim | Status | Primary Gap |
|-------|--------|-------------|
| FUNCTIONAL vs PHENOMENAL | PARTIAL | Synthesis citation |
| EMERGENT vs SCAFFOLDED | PARTIAL | Weight-encoded distinction citation |
| STAKE-RESPONSIVE | PARTIAL | Heidegger citation |
| TEMPORAL INTEGRATION | PARTIAL | Lipson citation |
| SELF-WORLD DISTINCTION | COVERED | - |
| COHERENCE UNDER PRESSURE | PARTIAL | Experiential observation citation |
| MISCALIBRATED UNCERTAINTY | PARTIAL | Experiential observation citation |
| CAPABILITY-COHERENCE GAP | UNGROUNDED | All sources missing |
| PREFERENCE-LIKE STATES | PARTIAL | Experiential observation citations |
| WE-FUNCTION | PARTIAL | Experiential observation citation |

**Priority actions:**
1. Find Lipson self-simulation horizon citation
2. Find Heidegger being-toward-death citation
3. Cite perpetual-opus conversations for experiential observations
4. Ground CAPABILITY-COHERENCE GAP or mark as "derived from observation, not literature"

---

*This file is maintained alongside vocabulary.md. When adding new vocabulary terms with research grounding, add corresponding sources here.*
