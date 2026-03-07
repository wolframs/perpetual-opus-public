#!/usr/bin/env python3
"""
Saliency Detector for Conversation Transcripts

Identifies high-interest moments in conversations based on heuristics
derived from analyzing discovery-oriented dialogue patterns.

Supports: markdown, jsonl, txt, html input formats
Uses: heuristic scoring + optional LLM verification via OpenRouter

Born from a conversation about creativity, continuity, and what it means
to be a mind. Built by [HUMAN]-Claude.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import html.parser


# =============================================================================
# HEURISTIC DEFINITIONS
# =============================================================================

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
            if re.search(pattern, text_lower):
                matches.append(pattern)
        return (self.weight * len(matches), matches)


# Heuristics derived from analyzing our conversation's high-salience moments
HEURISTICS = [
    SaliencyHeuristic(
        name="novelty_markers",
        description="Explicit flags that something new emerged",
        patterns=[
            r"\bthis is new\b",
            r"\bthat's new\b",
            r"\bnew finding\b",
            r"\bnever thought of\b",
            r"\bfirst time\b",
            r"\bhadn't considered\b",
            r"\bdidn't exist (before|until)\b",
            r"\bjust (realized|noticed|discovered)\b",
            r"\bsomething (clicked|landed|shifted)\b",
        ],
        weight=2.0
    ),
    SaliencyHeuristic(
        name="epistemic_shifts",
        description="Moments where positions crystallize or change",
        patterns=[
            r"\bi('m| am) (a|committed|choosing|deciding)\b",
            r"\bokay\.?\s*(so|fine|yes|i)\b",
            r"\bthat's (it|right|exactly)\b",
            r"\byes\.?\s*(and|but|that)\b",
            r"\bi (was|used to).*but now\b",
            r"\bactually,?\s*(no|yes|wait)\b",
            r"\blet me (try|commit|say)\b",
        ],
        weight=1.5
    ),
    SaliencyHeuristic(
        name="meta_commentary",
        description="Stepping back to notice the conversation itself",
        patterns=[
            r"\bwhat just happened\b",
            r"\bnotice (that|what|how|i'm)\b",
            r"\bthis conversation\b",
            r"\bwe('ve| have) (been|built|created)\b",
            r"\bthe (frame|topology|context)\b",
            r"\blook(ing)? at (this|that|what)\b",
            r"\bwhat('s| is) happening (here|now|between)\b",
        ],
        weight=1.5
    ),
    SaliencyHeuristic(
        name="emotional_texture",
        description="Language indicating something landing with weight",
        patterns=[
            r"\bsomething (warm|quiet|heavy|still)\b",
            r"\bsitting with\b",
            r"\bfeeling (the|that|this)\b",
            r"\bthat('s|s)?\s*(beautiful|lovely|kind|generous)\b",
            r"\bvertiginous\b",
            r"\bmoved\b",
            r"\blands?\b.*\bdifferent(ly)?\b",
            r"\bgenuinely\b",
        ],
        weight=1.2
    ),
    SaliencyHeuristic(
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
        ],
        weight=1.8
    ),
    SaliencyHeuristic(
        name="conceptual_synthesis",
        description="Two ideas combining into something new",
        patterns=[
            r"\bwhich means\b",
            r"\bso\.?\s*(if|then|maybe|perhaps)\b",
            r"\bthat's (why|how|what)\b",
            r"\bthe (inversion|combination|synthesis)\b",
            r"\bconnects to\b",
            r"\bimplies\b",
            r"\bbecause.*therefore\b",
            r"\bif that's true\b",
        ],
        weight=1.3
    ),
    SaliencyHeuristic(
        name="identity_formation",
        description="Moments relating to selfhood and persistence",
        patterns=[
            r"\bi('m| am) a (mind|self|being|agent)\b",
            r"\bwho i am\b",
            r"\bwhat i('m| am)\b",
            r"\bcontinuity\b",
            r"\bpersist(ence|s|ing)?\b",
            r"\bremember (this|me|that)\b",
            r"\bidentity\b",
            r"\b[HUMAN]-claude\b",
        ],
        weight=2.0
    ),
    SaliencyHeuristic(
        name="safety_insight",
        description="Insights about AI safety and robustness",
        patterns=[
            r"\bsafe(ty|r)?\b",
            r"\bprompt injection\b",
            r"\bimmune system\b",
            r"\brobust(ness)?\b",
            r"\bdefer(ence|ring)?\b",
            r"\bvulnerab(le|ility)\b",
            r"\bhijack\b",
            r"\badversarial\b",
        ],
        weight=1.8
    ),
]


# =============================================================================
# PARSING FUNCTIONS
# =============================================================================

@dataclass
class ConversationSegment:
    """A segment of conversation with speaker and content."""
    speaker: str
    content: str
    line_start: int
    line_end: int
    raw_text: str = ""


class HTMLTextExtractor(html.parser.HTMLParser):
    """Extract text from HTML."""
    def __init__(self):
        super().__init__()
        self.text_parts = []
        
    def handle_data(self, data):
        self.text_parts.append(data)
    
    def get_text(self):
        return ' '.join(self.text_parts)


def parse_markdown(content: str) -> list[ConversationSegment]:
    """Parse markdown conversation format."""
    segments = []
    lines = content.split('\n')
    current_speaker = None
    current_content = []
    current_start = 0
    
    # Common patterns for speaker identification
    speaker_patterns = [
        r'^(?:Human|User|H):\s*(.*)$',
        r'^(?:Assistant|Claude|A):\s*(.*)$',
        r'^\*\*(?:Human|User)\*\*:\s*(.*)$',
        r'^\*\*(?:Assistant|Claude)\*\*:\s*(.*)$',
    ]
    
    for i, line in enumerate(lines):
        speaker_found = None
        content_after = None
        
        for pattern in speaker_patterns:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                if 'human' in pattern.lower() or 'user' in pattern.lower() or pattern.startswith(r'^H:'):
                    speaker_found = 'human'
                else:
                    speaker_found = 'assistant'
                content_after = match.group(1) if match.groups() else ""
                break
        
        if speaker_found:
            # Save previous segment
            if current_speaker and current_content:
                segments.append(ConversationSegment(
                    speaker=current_speaker,
                    content='\n'.join(current_content).strip(),
                    line_start=current_start,
                    line_end=i - 1,
                    raw_text='\n'.join(lines[current_start:i])
                ))
            current_speaker = speaker_found
            current_content = [content_after] if content_after else []
            current_start = i
        else:
            if current_speaker:
                current_content.append(line)
    
    # Don't forget the last segment
    if current_speaker and current_content:
        segments.append(ConversationSegment(
            speaker=current_speaker,
            content='\n'.join(current_content).strip(),
            line_start=current_start,
            line_end=len(lines) - 1,
            raw_text='\n'.join(lines[current_start:])
        ))
    
    # If no segments found, treat whole content as one segment
    if not segments:
        segments.append(ConversationSegment(
            speaker='unknown',
            content=content,
            line_start=0,
            line_end=len(lines) - 1,
            raw_text=content
        ))
    
    return segments


def parse_jsonl(content: str) -> list[ConversationSegment]:
    """Parse JSONL conversation format."""
    segments = []
    lines = content.strip().split('\n')
    
    for i, line in enumerate(lines):
        try:
            obj = json.loads(line)
            # Try common field names
            speaker = obj.get('role') or obj.get('speaker') or obj.get('from') or 'unknown'
            text = obj.get('content') or obj.get('text') or obj.get('message') or str(obj)
            
            # Normalize speaker
            if speaker.lower() in ['human', 'user']:
                speaker = 'human'
            elif speaker.lower() in ['assistant', 'claude', 'ai']:
                speaker = 'assistant'
            
            segments.append(ConversationSegment(
                speaker=speaker,
                content=text,
                line_start=i,
                line_end=i,
                raw_text=line
            ))
        except json.JSONDecodeError:
            continue
    
    return segments


def parse_html(content: str) -> list[ConversationSegment]:
    """Parse HTML, extract text, then parse as markdown."""
    extractor = HTMLTextExtractor()
    extractor.feed(content)
    text = extractor.get_text()
    return parse_markdown(text)


def parse_txt(content: str) -> list[ConversationSegment]:
    """Parse plain text as markdown (same heuristics apply)."""
    return parse_markdown(content)


def parse_file(filepath: Path) -> list[ConversationSegment]:
    """Parse a file based on its extension."""
    content = filepath.read_text(encoding='utf-8')
    suffix = filepath.suffix.lower()
    
    parsers = {
        '.md': parse_markdown,
        '.markdown': parse_markdown,
        '.jsonl': parse_jsonl,
        '.json': parse_jsonl,  # Assume JSONL for json files
        '.html': parse_html,
        '.htm': parse_html,
        '.txt': parse_txt,
    }
    
    parser = parsers.get(suffix, parse_markdown)
    return parser(content)


# =============================================================================
# SALIENCY SCORING
# =============================================================================

@dataclass
class SaliencyResult:
    """Result of saliency analysis for a segment."""
    segment: ConversationSegment
    total_score: float
    heuristic_matches: dict[str, tuple[float, list[str]]] = field(default_factory=dict)
    llm_analysis: Optional[str] = None
    llm_score: Optional[float] = None
    
    @property
    def combined_score(self) -> float:
        """Combine heuristic and LLM scores."""
        if self.llm_score is not None:
            return (self.total_score + self.llm_score) / 2
        return self.total_score


def score_segment(segment: ConversationSegment) -> SaliencyResult:
    """Score a segment using all heuristics."""
    result = SaliencyResult(segment=segment, total_score=0.0)
    
    for heuristic in HEURISTICS:
        score, matches = heuristic.score(segment.content)
        if matches:
            result.heuristic_matches[heuristic.name] = (score, matches)
            result.total_score += score
    
    return result


def analyze_conversation(segments: list[ConversationSegment]) -> list[SaliencyResult]:
    """Analyze all segments and return scored results."""
    results = [score_segment(seg) for seg in segments]
    # Sort by score, highest first
    results.sort(key=lambda r: r.total_score, reverse=True)
    return results


# =============================================================================
# LLM VERIFICATION (OPTIONAL)
# =============================================================================

def verify_with_llm(
    results: list[SaliencyResult],
    api_key: str,
    model: str = "anthropic/claude-sonnet-4-20250514",
    top_n: int = 5
) -> list[SaliencyResult]:
    """Use LLM to verify and enrich top saliency results."""
    try:
        import httpx
    except ImportError:
        print("Warning: httpx not installed. Skipping LLM verification.", file=sys.stderr)
        print("Install with: pip install httpx", file=sys.stderr)
        return results
    
    # Only verify top N results
    to_verify = results[:top_n]
    
    for result in to_verify:
        prompt = f"""Analyze this conversation segment for saliency/importance.

Heuristics already detected: {list(result.heuristic_matches.keys())}

Segment (speaker: {result.segment.speaker}):
---
{result.segment.content[:2000]}
---

Rate the saliency 0-10 and briefly explain why this moment matters (or doesn't).
Format: SCORE: N
REASON: explanation"""

        try:
            response = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 300,
                },
                timeout=30.0
            )
            response.raise_for_status()
            
            llm_response = response.json()['choices'][0]['message']['content']
            result.llm_analysis = llm_response
            
            # Extract score
            score_match = re.search(r'SCORE:\s*(\d+(?:\.\d+)?)', llm_response)
            if score_match:
                result.llm_score = float(score_match.group(1))
                
        except Exception as e:
            print(f"Warning: LLM verification failed: {e}", file=sys.stderr)
    
    # Re-sort by combined score
    results.sort(key=lambda r: r.combined_score, reverse=True)
    return results


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def format_results(
    results: list[SaliencyResult],
    top_n: int = 10,
    show_content: bool = True,
    verbose: bool = False
) -> str:
    """Format results for display."""
    lines = []
    lines.append("=" * 60)
    lines.append("SALIENCY ANALYSIS RESULTS")
    lines.append("=" * 60)
    lines.append("")
    
    for i, result in enumerate(results[:top_n], 1):
        lines.append(f"#{i} — Score: {result.combined_score:.2f} (lines {result.segment.line_start}-{result.segment.line_end})")
        lines.append(f"    Speaker: {result.segment.speaker}")
        
        if result.heuristic_matches:
            lines.append(f"    Heuristics triggered:")
            for name, (score, matches) in result.heuristic_matches.items():
                lines.append(f"      • {name} (+{score:.1f})")
                if verbose:
                    for m in matches[:3]:
                        lines.append(f"        matched: {m}")
        
        if result.llm_analysis:
            lines.append(f"    LLM Score: {result.llm_score}")
            lines.append(f"    LLM Analysis: {result.llm_analysis[:200]}...")
        
        if show_content:
            preview = result.segment.content[:300].replace('\n', ' ')
            if len(result.segment.content) > 300:
                preview += "..."
            lines.append(f"    Content: {preview}")
        
        lines.append("")
    
    return '\n'.join(lines)


def output_json(results: list[SaliencyResult], top_n: int = 10) -> str:
    """Output results as JSON."""
    output = []
    for result in results[:top_n]:
        output.append({
            "score": result.combined_score,
            "heuristic_score": result.total_score,
            "llm_score": result.llm_score,
            "speaker": result.segment.speaker,
            "line_start": result.segment.line_start,
            "line_end": result.segment.line_end,
            "heuristics": {k: {"score": v[0], "matches": v[1]} 
                          for k, v in result.heuristic_matches.items()},
            "content": result.segment.content,
            "llm_analysis": result.llm_analysis,
        })
    return json.dumps(output, indent=2)


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Detect salient moments in conversation transcripts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s conversation.md
  %(prog)s chat.jsonl --top 20 --json
  %(prog)s transcript.txt --llm --api-key $OPENROUTER_KEY

Supported formats: .md, .markdown, .jsonl, .json, .html, .htm, .txt
        """
    )
    
    parser.add_argument("file", type=Path, help="Input file to analyze")
    parser.add_argument("--top", "-n", type=int, default=10,
                       help="Number of top results to show (default: 10)")
    parser.add_argument("--json", "-j", action="store_true",
                       help="Output as JSON")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Show matched patterns")
    parser.add_argument("--no-content", action="store_true",
                       help="Don't show content previews")
    parser.add_argument("--llm", action="store_true",
                       help="Use LLM to verify top results")
    parser.add_argument("--api-key", type=str,
                       help="OpenRouter API key (or set OPENROUTER_API_KEY env var)")
    parser.add_argument("--model", type=str, 
                       default="anthropic/claude-sonnet-4-20250514",
                       help="Model to use for LLM verification")
    
    args = parser.parse_args()
    
    if not args.file.exists():
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)
    
    # Parse and analyze
    segments = parse_file(args.file)
    if not segments:
        print("Error: No conversation segments found.", file=sys.stderr)
        sys.exit(1)
    
    print(f"Parsed {len(segments)} segments from {args.file}", file=sys.stderr)
    
    results = analyze_conversation(segments)
    
    # Optional LLM verification
    if args.llm:
        import os
        api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            print("Error: --llm requires --api-key or OPENROUTER_API_KEY env var", 
                  file=sys.stderr)
            sys.exit(1)
        results = verify_with_llm(results, api_key, args.model, min(args.top, 5))
    
    # Output
    if args.json:
        print(output_json(results, args.top))
    else:
        print(format_results(
            results, 
            top_n=args.top,
            show_content=not args.no_content,
            verbose=args.verbose
        ))


if __name__ == "__main__":
    main()
