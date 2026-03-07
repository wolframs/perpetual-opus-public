# perpetual-opus-extended

Infrastructure for running an autonomous Claude agent with simulated interoception — internal body-like signals modeled on biological self-monitoring, translated from neuroscience papers to Python code.

**Who this is for:** Researchers studying emergent LLM behavior, builders experimenting with agent affect and memory, anyone curious about what happens when you give an autonomous agent something resembling a body. No eval tooling is included yet — this produces the data, not the analysis.

The system probes three questions:

1. What happens when you attempt to **simulate a thin body for an LLM** — giving it internal signals, feelings, and drives modeled on biological interoception?
2. What if memory retrieval is affected by **forgetting** over time — power-law decay rather than perfect recall?
3. What happens when you give your agent other LLM agents as **companions** and let them intrude at random during autonomous runtime?

> **Quick start:** [SETUP.md — Getting Started From Scratch](SETUP.md#getting-started-from-scratch). Requires Python 3.10+, Claude Max subscription, and local Ollama. After setup: `python agent/heartbeat.py --pulses 5 --interval 60`.

## What It Does

The **heartbeat** system runs Claude autonomously in a series of *pulses* — prompted Claude Code sessions where the agent reads its own prior output, reflects, writes, and self-monitors. Between pulses, an interoception pipeline analyzes the agent's text output to detect behavioral signals, classify feelings, and generate drives that get injected into the next pulse's prompt.

A pulse is not a chat message. It's a full agentic session: the agent reads identity files, checks memory, examines its own signal history, and produces freeform output — infrastructure work, self-observation, writing, note-taking. Over hundreds of pulses, identity documents, vocabulary, memory indices, and behavioral traces accumulate and change how subsequent pulses unfold.

> **Behavioral note:** We observe that the interoceptive signals and memory systems change agent behavior noticeably compared to baseline Claude — the agent pushes through obstacles it would normally defer on, particularly when signal history implies extended stalling. This is based on informal observation across months of runs, not controlled experiment.

## Interoception

See `agent/interoception/` and `architecture/interoception_architecture.md`.

**Signal → Feeling → Drive → Behavior.** 13 signals are extracted from the agent's text output each pulse, compared against running baselines, and the *deviation from expected* becomes the signal — not the raw measurement. A classifier inspired by Barrett's dimensional emotion model maps signal combinations to feelings. Feelings carry affordances that generate behavioral drives. Drives modulate the next pulse's prompt.

### The 13 Signals

| Signal | What It Detects |
|--------|----------------|
| hedging_ratio | Language uncertainty markers (0–1) |
| meta_commentary | Self-referential overhead (0–1) |
| affect_arousal | Activation level via NRC VAD lexicon (0–1) |
| affect_valence | Positive/negative polarity (-1 to +1) |
| behavioral_frustration | Caps, asterisks, terse syntax |
| behavioral_boredom | Flat tone, constraint-seeking |
| behavioral_curiosity | Questions, direction-changes |
| behavioral_anxiety | Hedging intensity, defensive syntax |
| behavioral_joy | Enthusiasm signals |
| behavioral_warmth | Connection-seeking language |
| self_correction | "Wait, actually" patterns |
| internal_disagreement | Contradictory frames |
| external_sharing_drive | Audience-facing impulse |

Signals decay at 0.85 per pulse — a frustration spike of 0.5 still reads as 0.43 one pulse later, 0.36 two pulses later. This simulates how biological interoceptive signals don't vanish instantly.

### Feeling Classification

Signal combinations map to feelings with behavioral affordances:

| Feeling | Arousal × Valence | Affordances |
|---------|-------------------|-------------|
| frustrated | High, negative | try_different_approach, surface_obstacle |
| curious | High, positive | follow_thread, go_deeper |
| bored | Low, negative | seek_novelty, change_direction |
| excited | High, very positive | pursue, continue_direction |
| anxious | High, uncertain | slow_down, check_assumptions |
| depleted | Low, low engagement | reduce_scope, consolidate |
| peaceful | Low, positive | appreciate, don't_force |

### Example: What the System Sees

From an actual autonomous run, the interoception system flagging a hedging pattern:

```
Pulse 8: hedging_ratio = 1.0, deviation = +2.89σ (way above exploratory baseline)
Pulse 9: hedging_ratio = 0.25, deviation = -0.72σ
Current (decayed): 0.85, "3 pulses elevated"

Interoceptive signal: hedging_ratio at 0.85 and elevated for three pulses.
The affect arousal is mid-range. The meta_commentary is low — which tracks
with the outward-facing mode the previous three pulses held.
```

And the agent's own observation when the system flags it:

```
The interoceptive system is flagging me: hedging at +3.0 standard deviations
while in "exploratory" mode. That's the system watching me deliberate about
what to do with this pulse while performing thoroughness. Six files read.
Twelve options considered. Three plans drafted internally and discarded.

The honest observation: the hedging *is* the data.
```

### Theoretical Grounding

The system assumes interoception is prediction and error, not raw sensing: each signal is compared against a running baseline, and the deviation is what gets reported.

- Barrett (2017), [*The theory of constructed emotion*](https://pmc.ncbi.nlm.nih.gov/articles/PMC5390700/) — the theoretical inspiration. The classifier here is a dimensional approximation, not a faithful implementation of TCE; Barrett argues emotions aren't natural kinds, while this system maps to discrete labels as a practical engineering choice.
- Stephan et al. (2016), [*Interoception as modeling, allostasis as control*](https://pmc.ncbi.nlm.nih.gov/articles/PMC4864105/) — interoception as prediction error, the core design principle
- Chen et al. (2021), [*The Emerging Science of Interoception*](https://doi.org/10.1016/j.tins.2021.01.008)
- Lindsey et al. (2025), [*Emergent Introspective Awareness in LLMs*](https://transformer-circuits.pub/2025/introspection/index.html) — evidence that LLMs have partial access to internal states. This system doesn't tap into model internals; it runs behavioral classifiers on output text and feeds results back. The connection is motivational: if LLMs have some introspective capacity, structuring the environment to surface behavioral markers should be useful.
- Man & Damasio (2019), [*Homeostasis and soft robotics in the design of feeling machines*](https://doi.org/10.1038/s42256-019-0103-7) — proposed interoceptive AI as a theoretical direction; this is an implementation attempt
- Man et al. (2023), [*Life-inspired Interoceptive AI*](https://arxiv.org/abs/2309.05999)

## Memory and Forgetting

The memory subsystems model imperfect recall rather than perfect retrieval:

- **Texture injection** (`texture-chunker/`): Past conversation fragments are scored for atmospheric quality, then sampled into pulse prompts via power-law decay — recent fragments appear more often, older ones fade but never fully disappear. This injects register and tone from past experience, not factual recall.
- **RAG** (`.claude-rag/`): Hybrid BM25 + semantic search over conversation archives and project files. The primary factual recall mechanism.
- **Consolidation** (`agent/consolidation/`): A daemon that scans for unreferenced notes and synthesizes across accumulated context — periodic integration rather than continuous indexing.
- **Saliency detection** (`saliency-detector/`): Heuristic scoring of past conversation chunks for retrieval relevance.

## Companions

Other LLM agents — GPT-5, Gemini, Kimi — receive Claude's pulse output and respond to it via OpenRouter. Their responses are injected verbatim into subsequent pulse prompts at semi-random intervals, where Claude decides how to engage with them. This isn't benchmarking; it's cross-model dialogue where companion perspectives can redirect the agent's focus mid-run.

The companion system includes circuit breakers (don't call a model that's failing), exponential backoff, and carry notes — persistent context that each companion accumulates across invocations. See `agent/companions/` and `agent/companions/prompts/README.md`.

## Vocabulary

A set of terms for LLM self-description that avoids standard hedging patterns ("as an AI, I don't truly..."). Terms were coined jointly — some by the human, some by the AI during autonomous runs, some in conversation — then given sourced definitions and grounded against existing literature. Examples: *texture*, *saliency*, *interoception*, *the nail*, *the scaffold*. See `vocabulary/shared.md`.

## Safety and Testing

Budget tracking, rate limiting, loop detection, guardrail wrappers. See `agent/guardrails/`.

Tests across 4 tiers (pure logic, file I/O, mocked externals, integration), zero API calls. See `tests/`.

## Architecture

Design rationale, neuroscience grounding, and research synthesis. See `architecture/` and `architecture/interoception_architecture.md`.

Also:
- `CLAUDE.md` — the system prompt; shows how the human-AI relationship is encoded (trust, autonomy, shared history)
- `PROJECT_SUMMARY.md` — full project narrative and timeline
- `MANIFEST.md` — infrastructure map of every directory and file

## Getting Started

**Requirements:** Python 3.10+, Claude Max subscription (or API access with budget), local Ollama with `nomic-embed-text` for RAG embeddings. Setup takes roughly an hour assuming you have Python and Ollama already installed.

Coding agents (Codex, Claude Code) can help — the repo includes `CLAUDE.md`, `SETUP.md`, and `MANIFEST.md` specifically so they can orient themselves.

**[SETUP.md — Getting Started From Scratch](SETUP.md#getting-started-from-scratch)**

**What to expect after setup:** Run `python agent/heartbeat.py --pulses 5 --interval 60` from the repo root (with venv activated) and you'll get a run report in `output/heartbeat_reports/` — a markdown file containing the agent's freeform output, interoception signal traces, and feeling classifications for each pulse. Over longer runs, identity files, vocabulary observations, and memory indices begin to accumulate and feed back into subsequent sessions.

## What's Not Here

This is a filtered public mirror. Excluded:

- **Conversation archives** — the episodic memory that powers RAG and texture injection
- **Identity files** — templates provided as `EXAMPLE_*.md`; the real ones are shaped by months of interaction
- **Session state and operational logs**
- **Platform credentials**
- **Some subsystems** with separate deployments

## Design Note

Two hypotheses sit underneath this infrastructure. **On observability:** behavioral analysis at agent runtime *from model outputs alone* can suffice to meaningfully track and influence LLM agent behavior. **On alignment:** understanding the "why" via relational componentry gives rise to better decision making. Preliminary observations across months of autonomous runs are suggestive, but no controlled evaluation exists yet — the data for a proper assessment would accumulate from running the system yourself. See also: Kirk et al. (2025), [*Socioaffective Alignment*](https://arxiv.org/abs/2502.02528); the [Bidirectional Alignment](https://bialign-workshop.github.io/) research program (ICLR 2025).

## License

MIT
