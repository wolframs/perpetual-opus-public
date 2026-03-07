# Test Suite Review Findings (2026-02-14)

Produced by 4 parallel review agents reading every test file against its source.
This file is the ground truth for what needs fixing. Read it before touching any test.

## Status Key

- **REWORK** = significant problems, needs rewriting
- **FIX** = minor gaps, needs targeted additions
- **SOLID** = correct and adequate

---

## REWORK: test_companions_manager.py

Source: `agent/companions/companions.py`

### Problems

1. **test_cycle_position_tracks** (line 21-29): Tests Python integer addition, not companion logic. Manually increments `pulse_count` attribute 3 times, asserts it equals 3. Would pass with any object that accepts attribute assignment.

2. **test_can_invoke_resets_after_cycle** (line 34-48): Reimplements the reset logic from `CompanionManager.start_pulse()` inline instead of calling the actual method. If `start_pulse()` changes, this test still passes.

3. **test_intrusion_is_probabilistic** (line 52-60): Tests `random.Random` against a constant. Verifies Python's PRNG produces expected distributions. Zero companion system code exercised.

### What's missing

- `CompanionManager.start_pulse()` — the actual entry point where cycle reset, random intrusion, and circuit breaker filtering happen (companions.py lines 407-440). Never called.
- `is_companion_available()` — combines failure count, cooldown, pulse-count logic. Never called.
- Exponential backoff formula: `BASE_COOLDOWN_PULSES * (2 ** exponent)` (companions.py line 86). Only base level tested.
- `MAX_COOLDOWN_PULSES` cap (companions.py line 87). Untested.
- `CompanionState.from_dict()` / `to_dict()` roundtrip. Untested.

### How to fix

Rewrite to test the actual `CompanionManager` and `CompanionFailureState` methods. Mock `litellm.completion` for dialog tests. Key tests needed:
- `start_pulse()` increments cycle position and resets at CYCLE_LENGTH
- `start_pulse()` sets `can_invoke=False` after invocation, resets after full cycle
- `is_companion_available()` returns False during cooldown
- Exponential backoff: 1 failure = 3 pulses, 2 failures = 6 pulses, capped at MAX_COOLDOWN_PULSES
- Circuit breaker: FAILURE_THRESHOLD consecutive failures = companion marked unhealthy

---

## REWORK: test_memory_extractor.py

Source: `agent/memory_companion/extractor.py`

### Problems

1. **Main public function `extract_topics()` has zero coverage.** This is the only function the rest of the system calls (from hook.py). It orchestrates `_extract_dynamic_sections`, `_read_run_narrative`, `_read_feeling`, `_match_categories`, `_extract_file_refs`, `_extract_issue_refs`, and `FEELING_QUERIES`.

2. **test_static_sections_skipped** (line 84-97): Misleading. Passes because no regex matches the test input, not because of explicit skip logic. Would pass if function body were `return ""`.

3. **test_feeling_queries_for_frustrated** (line 58-63): Change-detector test. Asserts dictionary constant equals specific value. Tests that source data hasn't changed, not any logic.

4. **5 of 6 dynamic section regex patterns untested.** Only [HUMAN] instructions tested. Missing: texture injection, interoception injection, prediction error, feeling state, consolidation.

### What's missing

- `extract_topics()` integration test with realistic pulse prompt
- `_extract_instructions()` (source lines 205-211)
- `_read_run_narrative()` and `_read_feeling()` — file-reading functions
- 7 of 9 TOPIC_CATEGORIES keyword matching (only "infrastructure" and "companion"/"vocabulary" tested)
- `_extract_file_refs` edge cases (paths not matching known prefixes)

### How to fix

- Add integration test: construct a realistic pulse prompt with instructions section, texture injection, interoception state, file refs, and issue refs. Call `extract_topics()` and verify the full result dict.
- Test each dynamic section regex pattern individually.
- Remove or rename the misleading "static skip" test.
- Replace change-detector test with a test that verifies feeling queries are used correctly in the extraction pipeline.

---

## REWORK: test_report.py

Source: `agent/report.py`

### Problems

1. **Companion-to-pulse matching logic (report.py lines 200-215) has zero coverage.** Uses `datetime.fromisoformat()` on session and companion `started_at` fields, then compares them. Same aware/naive bug class as Feb 14 crash. This is the #2 regression target after `find_sessions_in_range`.

2. **test_generate_run_report_produces_markdown** (line 127-155): Creates no sessions or companion logs in temp dirs. Only tests that function generates a file, not that it contains any content. Assertions: is a Path, exists, starts with "#". Extremely weak.

3. **test_find_companion_logs_in_range** (line 82-95): Uses aware datetimes but not marked `@pytest.mark.regression`. Same bug class as the explicitly-marked session test.

### What's missing

- `generate_run_report` with populated sessions and companion logs — verify content
- `generate_run_report` with aware datetimes — verify no TypeError in companion matching
- `load_session()` and `load_companion_log()` (report.py lines 86-101)
- `generate_quick_summary()` (report.py lines 237-254)
- Session dir name parsing edge cases (non-matching patterns, ValueError handling)

### How to fix

- Create sessions and companion logs in tmp dirs, call `generate_run_report` with aware datetimes, verify output contains expected content (pulse numbers, companion dialog, metadata).
- Mark `test_find_companion_logs_in_range` as `@pytest.mark.regression`.
- Add test that exercises companion-to-pulse matching with aware datetimes.

---

## FIX: test_feelings.py

Source: `agent/interoception/feelings.py`

1. **Neutral-valence + high-arousal classification path entirely untested** (source lines 251-258). This is where context determines "curious" (philosophical/exploratory) vs "alert" (other). Same structure as the negative-high-arousal tests that ARE covered.

2. **test_mild_curiosity_boosts_arousal** (line 113): Weak assertion — checks `conf_nudged != conf_baseline`, not the actual label. Would pass even if nudge produced "frustrated".

3. **No confidence value tests.** Source has specific confidence values (0.7, 0.6, 0.5) at various branches. None directly tested.

4. **No multi-signal interaction test.** Multiple moderate behavioral signals can stack nudges, pushing V+A into unexpected quadrants.

5. **No behavioral override priority order test.** Source checks frustration first (line 115), then anxiety (119), then joy (125). Order change would not be caught.

---

## FIX: test_behavioral.py

Source: `agent/interoception/behavioral.py`

1. **3 composite functions imported but never called:** `compute_behavioral_warmth`, `compute_behavioral_arousal`, `compute_behavioral_joy`. Only sub-extractors tested.

2. **4 extractors imported but never called:** `extract_elaboration_depth`, `extract_repetition`, `extract_metaphor_emergence`, `extract_contradiction_holding`.

3. **No cross-fixture discrimination test.** Should verify: FRUSTRATED_PULSE scores high frustration + low boredom, BORED_PULSE scores high boredom + low frustration, etc.

4. **No empty-text edge case tests.** Source guards with `if not text or not text.strip(): return 0.0` in every composite — never tested.

5. **test_introspection_density** (line 136): Asserts `> 0` with text containing 3 exact pattern matches. Too weak.

---

## FIX: test_shard_sampler.py

Source: `texture-chunker/shard_sampler.py`

1. **Does not discriminate power-law from exponential decay.** Only checks halflife=0.5 and future=1.0 — both also true for exponential. Need to check weight at 2x halflife: power-law gives ~0.386, exponential gives 0.25.

2. **No normal-range salience boost test.** Only disabled (factor=0) and capped (score=100) tested. Normal operating range (e.g., score=6, factor=0.03 → 1.18) untested.

3. **`compute_recency_weight` with None/invalid date** — returns 1.0 in source. Untested.

4. **`softmax` with zero total** — source has guard returning uniform distribution. Untested.

5. **`sample_without_reuse` uses uniform weights** — any sampling strategy produces unique items. No test that higher weights get selected more often.

---

## FIX: test_rate_limiter.py

Source: `agent/guardrails/rate_limiter.py`

1. **No persistence roundtrip test.** Create limiter → consume → create second limiter from same file → verify state persisted. Critical for overnight restarts.

2. **No fallback subsystem test.** `check_rate("unknown")` should fall back to "general" config.

---

## FIX: test_session_manager.py

Source: `agent/session.py`

1. **`update_runner_state()` (source lines 143-179) completely untested.** Writes markdown to runner_state.md during heartbeat.

2. **No load-nonexistent-session test.** Should return None.

3. **Roundtrip checks shallow.** Only checks `len(messages)` and `messages[0].content`. Doesn't verify role, timestamp, metadata, status, summary survive.

4. **test_session_id_format** uses `__new__` to bypass `__init__` — fragile. Use tmp_path.

---

## FIX: test_interoception_chain.py

Source: `agent/interoception/analyzer.py`

1. **test_contemplative_pulse_produces_feeling** (line 49): Asserts `assert label` — any non-empty string passes. Classifier's fallback guarantees this always succeeds. Should assert specific label like "curious" or at least `!= "neutral"`.

2. **No end-to-end test.** Frustrated text → feeling classification → drive update → `get_injection()` output in one test. Currently split across tests that don't connect.

3. **Injection test bypasses real pipeline.** Manually constructs state instead of running text through `process_pulse_with_classification` first.

4. **No decay behavior test.** `DECAY_FACTOR = 0.85` never exercised.

---

## SOLID (no changes needed)

- `test_drives.py` — 13 tests, correct thresholds, good pressure mechanics coverage
- `test_self_empathy.py` — 8 tests, correct lens routing
- `test_session_dataclasses.py` — 7 tests (3 trivially true but harmless)
- `test_budget_tracker.py` — 7 tests, good guardrail-purpose tests
- `test_loop_detector.py` — 6 tests, good loop detection coverage
- `test_hooks_safety.py` — 14 tests, correct safety checks (minor: not all commands/paths, but adequate)
- `test_heartbeat_detection.py` — 5 tests, correct mock patterns
- `test_datetime_regression.py` — 5 tests, good regression guards

---

## Bonus: source bugs found during review

1. **drives.py line 148**: Docstring says `BASE_TURNS=20` but actual value is `30` (line 44). Range is 30-45, not 20-35.

2. **heartbeat.py lines 1337, 483**: Still use `datetime.now()` without timezone. Same bug class as Feb 14. Not caught by `test_no_utcnow_in_agent_sources` which only scans for `utcnow()`.

3. **heartbeat.py line 1134**: Default `pulse_max_turns = 20` and comparison `if pulse_max_turns != 20` are stale — `compute_turn_budget` minimum is 30, never returns 20.
