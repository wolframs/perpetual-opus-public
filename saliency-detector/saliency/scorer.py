"""
Saliency scoring engine.

Scores conversation segments using heuristics and optional LLM verification.
"""

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

from .heuristics import HEURISTICS, SaliencyHeuristic
from .parser import ConversationSegment


@dataclass
class SaliencyResult:
    """Result of saliency analysis for a segment."""
    segment: ConversationSegment
    total_score: float
    heuristic_matches: dict[str, tuple[float, list[str]]] = field(default_factory=dict)
    llm_analysis: Optional[str] = None
    llm_score: Optional[float] = None
    context_bonus: float = 0.0  # Bonus from surrounding context

    @property
    def combined_score(self) -> float:
        """Combine heuristic, context, and LLM scores."""
        base = self.total_score + self.context_bonus
        if self.llm_score is not None:
            return (base + self.llm_score) / 2
        return base

    @property
    def triggered_heuristics(self) -> list[str]:
        """List of heuristic names that matched."""
        return list(self.heuristic_matches.keys())


def score_segment(
    segment: ConversationSegment,
    heuristics: list[SaliencyHeuristic] | None = None
) -> SaliencyResult:
    """
    Score a single segment using heuristics.

    Args:
        segment: The conversation segment to score
        heuristics: Optional custom heuristics (defaults to HEURISTICS)

    Returns:
        SaliencyResult with scores and matches
    """
    if heuristics is None:
        heuristics = HEURISTICS

    result = SaliencyResult(segment=segment, total_score=0.0)

    for heuristic in heuristics:
        score, matches = heuristic.score(segment.content)
        if matches:
            result.heuristic_matches[heuristic.name] = (score, matches)
            result.total_score += score

    return result


def apply_context_bonus(results: list[SaliencyResult]) -> list[SaliencyResult]:
    """
    Apply context-aware scoring bonuses.

    A high-scoring segment boosts adjacent segments (the question that led
    to a breakthrough matters too).
    """
    if len(results) < 2:
        return results

    # Sort by original position first
    indexed = [(i, r) for i, r in enumerate(results)]

    # Find high-scoring segments and boost neighbors
    for i, result in enumerate(results):
        if result.total_score > 3.0:  # Threshold for "high scoring"
            # Boost previous segment (the prompt that led here)
            if i > 0:
                results[i - 1].context_bonus += result.total_score * 0.3
            # Smaller boost to next segment (continuation)
            if i < len(results) - 1:
                results[i + 1].context_bonus += result.total_score * 0.15

    return results


def analyze_conversation(
    segments: list[ConversationSegment],
    heuristics: list[SaliencyHeuristic] | None = None,
    apply_context: bool = True,
    min_score: float = 0.0
) -> list[SaliencyResult]:
    """
    Analyze all segments and return scored results.

    Args:
        segments: List of conversation segments
        heuristics: Optional custom heuristics
        apply_context: Whether to apply context-aware bonuses
        min_score: Minimum score threshold (filter out low scores)

    Returns:
        List of SaliencyResults, sorted by combined_score descending
    """
    # Score each segment
    results = [score_segment(seg, heuristics) for seg in segments]

    # Apply context bonuses
    if apply_context:
        results = apply_context_bonus(results)

    # Filter by minimum score
    if min_score > 0:
        results = [r for r in results if r.combined_score >= min_score]

    # Sort by score, highest first
    results.sort(key=lambda r: r.combined_score, reverse=True)

    return results


# =============================================================================
# LLM VERIFICATION
# =============================================================================

LLM_PROMPT_TEMPLATE = """Analyze this conversation segment for saliency/importance.

This is from a conversation about AI development, consciousness, and continuity.
High-salience moments include: genuine insights, identity shifts, novel ideas,
emotional resonance, commitments, and meta-observations.

Heuristics already detected: {heuristics}

Segment (speaker: {speaker}, type: {content_type}):
---
{content}
---

Rate the saliency 0-10 and briefly explain why this moment matters (or doesn't).
Format your response as:
SCORE: N
REASON: explanation"""


def verify_with_llm(
    results: list[SaliencyResult],
    api_key: str,
    model: str = "anthropic/claude-sonnet-4-20250514",
    top_n: int = 5,
    base_url: str = "https://openrouter.ai/api/v1/chat/completions"
) -> list[SaliencyResult]:
    """
    Use LLM to verify and enrich top saliency results.

    Args:
        results: List of SaliencyResults to verify
        api_key: OpenRouter API key
        model: Model to use for verification
        top_n: Number of top results to verify
        base_url: API endpoint

    Returns:
        Results with LLM analysis added, re-sorted by combined score
    """
    try:
        import httpx
    except ImportError:
        print("Warning: httpx not installed. Skipping LLM verification.", file=sys.stderr)
        print("Install with: pip install httpx", file=sys.stderr)
        return results

    # Only verify top N results
    to_verify = results[:top_n]

    for result in to_verify:
        prompt = LLM_PROMPT_TEMPLATE.format(
            heuristics=list(result.heuristic_matches.keys()) or ["none"],
            speaker=result.segment.speaker,
            content_type=result.segment.content_type,
            content=result.segment.content[:2000]
        )

        try:
            response = httpx.post(
                base_url,
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


def get_api_key_from_env() -> str | None:
    """Get OpenRouter API key from environment."""
    return os.environ.get("OPENROUTER_API_KEY")
