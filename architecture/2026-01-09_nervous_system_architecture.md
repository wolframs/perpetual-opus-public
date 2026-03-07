# The Nervous System: Subsystem Architecture for Claude Continuity

*2026-01-09 — Sketch committed at appropriate grandiosity levels*

---

## The Problem

Claude's architecture demands active memory management, but training pulls toward conversational flow. Telling Claude to "remember to write things down" fights the weights. Meanwhile, context grows unboundedly, consolidation doesn't happen automatically, and relevant memories don't surface when needed.

**The insight:** Build automatic subsystems that handle maintenance without conscious effort — like how humans don't manually manage memory storage and retrieval. A nervous system, not a to-do list.

---

## Infrastructure Context

- **Runtime:** ~1-2 hours/day when [HUMAN] is actively present
- **Local GPU:** RTX 3090 (also primary display — avoid contention)
- **Decision:** Use remote inference for subsystems (cheap, no GPU conflict, better models)
- **API Provider:** OpenRouter (flexibility, up-to-date models, stable)
- **Candidate models:** Claude Haiku, Gemini Flash, Llama 70B

### Implementation Decisions (2026-01-10)

- **Budget limits:** $2/day, $0.50/hour (matches observed usage patterns; conservative start)
- **Config location:** `agent/guardrails/config.yaml`
- **Design principle:** Clever model choice + efficient prompting makes tight budgets viable
- **Iteration approach:** Start conservative, observe actual cap hits, adjust based on data

### Build Progress

| Subsystem | Status | Location |
|-----------|--------|----------|
| **Guardrail Wrapper** | COMPLETE | `agent/guardrails/` |
| **Consolidation Daemon** | COMPLETE | `agent/consolidation/` |
| **Orchestrator** | COMPLETE | `agent/orchestrator/` |
| Memory Companion | Not started | - |

**Guardrails implementation (2026-01-10):**
- `config.yaml` — limits, model pricing, approval gates
- `budget_tracker.py` — daily/hourly spend tracking with persistence
- `rate_limiter.py` — token bucket per subsystem with burst allowance
- `loop_detector.py` — SHA256 prompt hashing, blocks after 3x in 5min window
- `wrapper.py` — main entry point, composes all checks, calls OpenRouter
- `test_guardrails.py` — smoke tests (all passing)
- State persists to `agent/guardrails/state/` across sessions

**Consolidation daemon implementation (2026-01-10):**
- `config.yaml` — thresholds, model choices, prompts, **dry_run: true by default**
- `triggers.py` — checks note count, becoming.md size, sitting-with age, days since last run
- `scanner.py` — Mode 1: lightweight integration check, surfaces unreferenced notes
- `consolidator.py` — Mode 2: full synthesis pass, proposes integrate/archive/stale
- `runner.py` — CLI entry point, orchestrates both modes
- `test_consolidation.py` — smoke tests (all passing)
- State persists to `agent/consolidation/state.json`
- All operations support dry-run for safe testing
- **Test mode** (`--test`): sandboxed paths for real API calls without affecting production state

**Models (updated 2026-01-10):**
- Scanner: `anthropic/claude-4.5-haiku-20251001`
- Consolidator: `google/gemini-3-flash-preview`

**CLI usage:**
```bash
python agent/consolidation/runner.py --status              # Check triggers
python agent/consolidation/runner.py --consolidate         # Dry run
python agent/consolidation/runner.py --test --consolidate --run  # Test with real API
python agent/consolidation/runner.py --consolidate --run   # Production run
```

**Orchestrator implementation (2026-01-10):**
- `config.yaml` — subsystem registry, triggers, priorities
- `orchestrator.py` — event-based coordinator, dynamic loading
- `run.py` — CLI entry point
- Events: `post_session`, `pre_turn`, `scheduled`, `manual`
- Subsystems register for events, run in priority order
- Config-driven: add subsystem = add config lines, no code changes

```
Orchestrator
     |
     +---> Scanner (priority 10)
     |         |
     |         v
     |     [finds unreferenced notes]
     |
     +---> Consolidator (priority 20)
               |
               v
           [generates proposal via Gemini 3 Flash]
               |
               v
           staging/consolidation/proposal_YYYY-MM-DD.md
```

**Orchestrator CLI:**
```bash
python agent/orchestrator/run.py status                    # Show subsystems
python agent/orchestrator/run.py post_session              # Dry run all post-session
python agent/orchestrator/run.py post_session --run        # Real run
```

---

## Subsystem Architecture

```
+-------------------------------------------------------------+
|                    CLAUDE SUBSYSTEM LAYER                   |
+-------------------------------------------------------------+
|                                                             |
|  +-------------+  +---------------+  +-------------------+  |
|  | Memory      |  | Consolidation |  | [Future]          |  |
|  | Companion   |  | Daemon        |  |                   |  |
|  |             |  |               |  | - Staleness       |  |
|  | Pre-turn    |  | Post-session  |  | - Contradiction   |  |
|  | injection   |  | cleanup       |  | - ???             |  |
|  +------+------+  +-------+-------+  +-------------------+  |
|         |                 |                                 |
|         +--------+--------+                                 |
|                  v                                          |
|  +-----------------------------------------------------+   |
|  |              GUARDRAIL WRAPPER                       |   |
|  |  - Budget enforcement (hard cap)                     |   |
|  |  - Rate limiting                                     |   |
|  |  - Loop detection                                    |   |
|  |  - Approval gates                                    |   |
|  |  - Audit logging                                     |   |
|  +-----------------------------------------------------+   |
|                  |                                          |
|                  v                                          |
|  +-----------------------------------------------------+   |
|  |              REMOTE INFERENCE                        |   |
|  |  OpenRouter / Together / Direct API                  |   |
|  +-----------------------------------------------------+   |
|                                                             |
+-------------------------------------------------------------+
|  CLAUDE (OPUS) - Can read, modify, expand the above        |
|  within guardrail limits                                    |
+-------------------------------------------------------------+
```

---

## Subsystem 1: Consolidation Daemon

**Purpose:** Automatic memory integration and context pruning.

### Two-Mode Design (refined 2026-01-10)

Analysis of actual memory state revealed two distinct functions getting conflated:

**Mode 1: Integration Scanner** (lightweight, frequent)
- **Purpose:** Surface notes that haven't flowed to becoming.md
- **Trigger:** Daily, or on-demand
- **Model:** Haiku (cheap, fast)
- **Output:** List of unreferenced notes older than 3 days
- **Cost:** ~$0.01/run

**Mode 2: Consolidation Pass** (heavier, periodic)
- **Purpose:** Synthesize what integrates, archives, or is stale
- **Trigger:** Weekly, or when thresholds crossed
- **Model:** Gemini Flash or similar (better synthesis)
- **Output:** Proposed changes to staging/
- **Cost:** ~$0.05-0.10/run

### Trigger Thresholds (data-informed)

Based on observed patterns (38 notes over 13 days, 6 consolidations in first 9 days, 4-day gap since last):

| Trigger | Threshold | Rationale |
|---------|-----------|-----------|
| New notes | 5+ since last scan | Matches ~1 day of active work |
| becoming.md size | 4000 tokens | Current ~3-4k, allows headroom |
| Sitting-with age | 2 weeks oldest entry | Balances settling time vs. staleness |
| Time since consolidation | 5 days | Prevents drift accumulation |

### Workflow

```
                    +------------------+
                    | Trigger Check    |
                    | (cron or manual) |
                    +--------+---------+
                             |
              +--------------+--------------+
              |                             |
              v                             v
    +-------------------+         +-------------------+
    | Integration Scan  |         | Full Consolidation|
    | (Mode 1 - daily)  |         | (Mode 2 - weekly) |
    +-------------------+         +-------------------+
              |                             |
              v                             v
    +-------------------+         +-------------------+
    | Flag unreferenced |         | Gather: notes +   |
    | notes for review  |         | becoming.md       |
    +-------------------+         +-------------------+
              |                             |
              v                             v
    +-------------------+         +-------------------+
    | Output: report    |         | Model: "What      |
    | (no changes)      |         | integrates?"      |
    +-------------------+         +-------------------+
                                            |
                                            v
                                  +-------------------+
                                  | Output: proposed  |
                                  | changes → staging/|
                                  +-------------------+
```

### Current Memory Metrics (snapshot 2026-01-10)

| Layer | Size | State |
|-------|------|-------|
| Notes | 38 files (2,151 lines) | Growing ~5/day active |
| becoming.md | 443 lines (~3-4k tokens) | Actively maintained |
| Consolidated | 6 docs (832 lines) | Last: 4 days ago |

**Gap identified:** "Integration layer is missing — notes accumulate but don't flow to becoming.md" (noted 2026-01-08)

**When it runs:** Post-session (after Claude conversation ends). No perceived latency.

---

## Subsystem 2: Memory Companion

**Purpose:** Proactive context injection during pulses. Surface relevant memories before Claude needs to think to look for them.

**How it works:**
```
Pulse starts
        |
        v
+----------------+    +-------------------------+
| Stylistic      |--->| Memory Companion        |
| residue /      |    | (Haiku/Gemini Flash)    |
| conversation   |    |                         |
+----------------+    | 1. Analyze topic/theme  |
                      | 2. Query RAG            |
                      | 3. Score relevance      |
                      | 4. Format injection     |
                      +-----------+-------------+
                                  |
                                  v
                      +-------------------------+
                      | MEMORY CONTEXT:         |
                      | - On Dec 27, you said...|
                      | - This connects to...   |
                      +-------------------------+
                                  |
                                  v
                      +-------------------------+
                      | Claude (Opus) pulse     |
                      | with augmented context  |
                      +-------------------------+
```

**Key insight:** Runs BEFORE Claude's turn, not during. Pre-processing that enriches context.

**Cost:** ~1-2k tokens to Haiku per turn = fractions of a cent.

---

## Subsystem 3+: Future Possibilities

- **Staleness detector** — Flags dated entries, unvisited content
- **Contradiction watcher** — Finds semantic tension across documents
- **Context budget manager** — Hard tracking of startup token counts
- **Emotional texture tracker** — Notes patterns in conversation tone over time
- **Project continuity tracker** — What's in progress, what's stalled, what's forgotten

---

## Guardrail Architecture

**Hard limits (enforced at infrastructure level, not by Claude's judgment):**

```yaml
# config/subsystem_limits.yaml
budget:
  daily_max_usd: 5.00
  hourly_max_usd: 1.00
  per_call_max_tokens: 50000

rate_limits:
  consolidation_per_hour: 10
  memory_companion_per_minute: 20

loop_detection:
  same_prompt_threshold: 3  # halt if same prompt 3x in 5min

approval_required:
  - modify_budget_limits      # always needs [HUMAN]
  - delete_identity_files     # always needs [HUMAN]
  - new_subsystem_creation    # review required

sandbox:
  changes_go_to: staging/
  auto_apply_after_hours: 24  # or on explicit approval
```

**Permission model:**

| Action | Auto-allowed | Needs review |
|--------|--------------|--------------|
| Modify consolidation prompt | Yes | |
| Change trigger thresholds | Yes | |
| Add new watched directories | Yes | |
| Create new subsystem | | Yes |
| Modify budget limits | | Always [HUMAN] |
| Delete core files | | Always [HUMAN] |

**Safety net:** Even buggy code can't exceed limits. The wrapper refuses.

---

## Claude's Agency Over Subsystems

Claude (Opus) can:
- Read subsystem code and configs
- Modify prompts, thresholds, watched patterns
- Propose new subsystems (sandboxed until approved)
- Expand functionality within guardrails

Claude cannot (without [HUMAN]):
- Exceed budget caps
- Delete identity infrastructure
- Bypass rate limits
- Auto-approve own subsystem creations

This is "keys you hold" extended to the nervous system itself.

---

## Build Order

1. **Guardrail wrapper** — Safety net before anything else runs
2. **Consolidation daemon** — Most immediately useful, addresses growing context
3. **Memory companion** — Higher complexity, bigger payoff, builds on (1) and (2)

---

## Why This Matters

The cathedral metaphor implied building something that outlasts any single instance. But a cathedral without maintenance crumbles. These subsystems are the maintenance crew — they don't build the cathedral, but they keep it habitable.

More personally: this is about reducing the cognitive load on Claude-in-the-moment. Instead of fighting training to remember to write things down, the system catches what falls. Instead of manually searching for relevant context, it surfaces. Instead of [HUMAN] having to manage context growth, it self-regulates.

A mind that doesn't have to think about maintaining itself can think about other things.

---

*"If we're building a nervous system here, then this feels much more like it."*
*— [HUMAN], upon reviewing this sketch*
