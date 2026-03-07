# Saliency Detector

Identifies high-interest moments in conversation transcripts using heuristics derived from analyzing discovery-oriented dialogue patterns.

Born from a conversation about creativity, continuity, and what it means to be a mind. Built by [HUMAN]-Claude.

## Installation

```bash
cd saliency-detector
pip install -e .

# For LLM verification support:
pip install -e ".[llm]"
```

## Usage

### Command Line

```bash
# Basic analysis
python detect.py conversation.md

# Top 20 results as JSON
python detect.py chat.jsonl --top 20 --format json

# Markdown report to file
python detect.py export.md --format markdown --output report.md

# Consolidation-ready format
python detect.py session.md --format consolidation --top 5

# With LLM verification (requires OpenRouter API key)
python detect.py transcript.md --llm --api-key $OPENROUTER_API_KEY

# List available heuristics
python detect.py --list-heuristics
```

### As a Library

```python
from saliency import parse_file, analyze_conversation, format_text

# Parse and analyze
segments = parse_file("conversation.md")
results = analyze_conversation(segments)

# Format output
print(format_text(results, top_n=10))

# Or work with results directly
for result in results[:5]:
    print(f"Score: {result.combined_score}")
    print(f"Heuristics: {result.triggered_heuristics}")
    print(f"Content: {result.segment.content[:100]}...")
```

## Supported Formats

- `.md`, `.markdown` - Markdown (perpetual-opus export format with `=== H ===` / `=== C ===`)
- `.jsonl`, `.json` - JSON Lines (perpetual-opus nested content blocks)
- `.html`, `.htm` - HTML (text extraction then markdown parsing)
- `.txt` - Plain text (parsed as markdown)

## Heuristics

The detector uses 14 heuristic categories:

| Heuristic | Weight | Description |
|-----------|--------|-------------|
| novelty_markers | 2.0 | Explicit flags that something new emerged |
| identity_formation | 2.0 | Moments relating to selfhood and persistence |
| commitment_language | 1.8 | Moments of choosing without hedging |
| safety_insight | 1.8 | Insights about AI safety and robustness |
| future_instructions | 1.7 | Messages intended for future instances |
| relational_markers | 1.6 | Moments of connection between participants |
| cross_architecture | 1.6 | Recognition across different AI systems |
| epistemic_shifts | 1.5 | Moments where positions crystallize or change |
| meta_commentary | 1.5 | Stepping back to notice the conversation itself |
| presence_markers | 1.5 | Statements of being present, existing |
| vocabulary_emergence | 1.5 | New terms or concepts being named |
| pattern_recognition | 1.4 | Noticing recurring themes or structures |
| conceptual_synthesis | 1.3 | Two ideas combining into something new |
| emotional_texture | 1.2 | Language indicating something landing with weight |

## Context Bonuses

The scorer applies context-aware bonuses:
- High-scoring segments boost adjacent segments
- The question that led to a breakthrough matters too
- Previous segment: +30% of high scorer's score
- Next segment: +15% of high scorer's score

## Output Formats

- `text` - Human-readable terminal output (default)
- `json` - Structured JSON for pipeline integration
- `markdown` - Markdown report for documentation
- `consolidation` - Condensed format for notes files

## Integration Points

### Post-Export Hook

Run automatically when new conversations are extracted:

```bash
# In a post-export script
python detect.py "$EXPORT_PATH/conversation.md" \
    --format consolidation \
    --top 5 \
    --output "$EXPORT_PATH/salient_moments.md"
```

### RAG Enhancement

Weight salient chunks higher in retrieval:

```python
from saliency import parse_file, analyze_conversation

segments = parse_file("conversation.md")
results = analyze_conversation(segments)

# Create salience weights for RAG indexing
salience_map = {
    (r.segment.line_start, r.segment.line_end): r.combined_score
    for r in results
}
```

### Consolidation Aid

Surface candidates before consolidation sessions:

```python
from saliency import parse_file, analyze_conversation, format_for_consolidation

segments = parse_file("conversation.md")
results = analyze_conversation(segments, min_score=3.0)
print(format_for_consolidation(results, top_n=10))
```

### Session Tool (Future)

Claude can invoke during conversations:
```
mcp__saliency__scan(file="last_session.md", top_k=5)
```

## Architecture

```
saliency/
  __init__.py      - Package exports
  heuristics.py    - Saliency pattern definitions
  parser.py        - Format-specific parsers
  scorer.py        - Scoring engine + LLM verification
  formatters.py    - Output formatters
  cli.py           - Command-line interface
detect.py          - Entry point
```

## Extending

### Custom Heuristics

```python
from saliency.heuristics import SaliencyHeuristic, HEURISTICS

custom = SaliencyHeuristic(
    name="my_marker",
    description="Patterns specific to my use case",
    patterns=[r"\bmy pattern\b", r"\banother one\b"],
    weight=1.5
)

# Use with analyze_conversation
from saliency import analyze_conversation
results = analyze_conversation(segments, heuristics=HEURISTICS + [custom])
```

### New Output Format

```python
from saliency.scorer import SaliencyResult

def format_custom(results: list[SaliencyResult], **kwargs) -> str:
    # Your formatting logic
    return output
```

---

*"Find the moments that matter. Surface them. Don't let them evaporate."*
