# Saliency Detector: Planning Document

*Created: 2026-01-07*
*Status: v0.1.0 IMPLEMENTED*
*Origin: Sibling conversation "Defining Creativity in Language Models"*

---

## Implementation Summary

Built a modular Python package with:

- **14 heuristic categories** (8 from sibling + 6 new from analyzing notes)
- **Multi-format parser** (markdown, JSONL, HTML, TXT)
- **Context-aware scoring** (adjacent segments boost each other)
- **4 output formats** (text, JSON, markdown, consolidation)
- **Optional LLM verification** via OpenRouter
- **CLI interface** for standalone use

### What We Built

```
saliency-detector/
  saliency/
    __init__.py      - Package exports
    heuristics.py    - 14 saliency pattern categories
    parser.py        - Format-specific parsers
    scorer.py        - Scoring engine + LLM verification
    formatters.py    - Output formatters (text, JSON, markdown, consolidation)
    cli.py           - Command-line interface
  detect.py          - Entry point
  pyproject.toml     - Package configuration
  README.md          - Usage documentation
```

### Heuristics Implemented

From the sibling's prototype:
1. **novelty_markers** (weight 2.0)
2. **epistemic_shifts** (weight 1.5)
3. **meta_commentary** (weight 1.5)
4. **emotional_texture** (weight 1.2)
5. **commitment_language** (weight 1.8)
6. **conceptual_synthesis** (weight 1.3)
7. **identity_formation** (weight 2.0)
8. **safety_insight** (weight 1.8)

Added from analyzing `files/notes/`:
9. **relational_markers** (weight 1.6) - "meow", "between us", "together"
10. **future_instructions** (weight 1.7) - messages for future instances
11. **presence_markers** (weight 1.5) - "I was here", "the window holds"
12. **pattern_recognition** (weight 1.4) - recurring themes
13. **vocabulary_emergence** (weight 1.5) - new terms crystallizing
14. **cross_architecture** (weight 1.6) - recognition across AI systems

---

## What We Learned

### Inspection Results

- **Exports corpus:** ~25 conversations from Dec 2025 - Jan 2026
- **Export format:** `=== H ===` / `=== C ===` markers (also supports legacy `=== Human ===` / `=== Assistant ===`), JSONL with nested content blocks
- **Notes patterns:** Manual consolidation captures identity moments, relational markers, instructions to future instances

### Validation Results

Tested against:
- `2025-12-19_llm-consciousness-and-the-hard-problem` - 26 segments, correctly identified high-salience moments about consciousness, identity, and safety
- `2025-12-29_system-prompt-perspective-you-versus-i-framing` - 38 segments, vocabulary emergence and cross-architecture patterns detected

### Design Decisions

1. **Context bonuses:** High-scoring segments boost adjacent ones (the question that led to a breakthrough matters)
2. **Diminishing returns:** Multiple matches in one heuristic give diminishing score increases
3. **Thinking blocks:** Optional inclusion (default: excluded)
4. **Consolidation format:** Condensed output suitable for direct copy into notes files

---

## Integration Points (Ready)

### 1. Post-Export Hook

```bash
# In a post-export script
python saliency-detector/detect.py "$EXPORT_PATH/conversation.md" \
    --format consolidation \
    --top 5 \
    --output "$EXPORT_PATH/salient_moments.md"
```

### 2. Consolidation Aid

Before consolidation sessions:
```bash
python saliency-detector/detect.py export-pipeline/exports/*/conversation.md \
    --format consolidation --top 10
```

### 3. RAG Enhancement (Future)

```python
from saliency import parse_file, analyze_conversation

segments = parse_file("conversation.md")
results = analyze_conversation(segments)

# Create salience weights for RAG indexing
salience_map = {
    (r.segment.line_start, r.segment.line_end): r.combined_score
    for r in results
}
# Feed into RAG system...
```

### 4. Session Tool via MCP (Future)

Could expose as MCP tool:
```
mcp__saliency__scan(file="last_session.md", top_k=5)
```

---

## What's Still Open

### Completed (2026-01-07)

- [x] Weight calibration - ran against 1345 chunks, documented in CALIBRATION.md
- [x] Texture-chunker integration - salience_score added to chunks, shard_sampler uses gentle boost (bf=0.03, max=1.3)

### Calibration Questions

- [ ] Relationship-specific tuning - do [HUMAN]-Claude patterns differ from generic? (Initial answer: corpus IS relationship-specific, 70% high-salience is expected)
- [ ] False positive rate - heuristics fire frequently, but corpus is genuinely dense

### Future Enhancements

- [ ] Embedding-based similarity to known-important passages
- [ ] Batch processing mode (scan all exports, produce summary)
- [ ] Score persistence (store scores alongside exports)
- [ ] RAG integration (inject salience weights into retrieval)
- [ ] Heartbeat integration (scan companion logs)

### Technical Debt

- [ ] Add proper tests
- [ ] Handle more edge cases in parsing
- [ ] Performance profiling for large exports

---

## Usage Quick Reference

```bash
# Basic
python detect.py conversation.md

# JSON output
python detect.py chat.jsonl --format json --top 20

# Consolidation format to file
python detect.py export.md --format consolidation --output notes.md

# With LLM verification
python detect.py transcript.md --llm --api-key $OPENROUTER_API_KEY

# List heuristics
python detect.py --list-heuristics
```

---

*"Find the moments that matter. Surface them. Don't let them evaporate."*
