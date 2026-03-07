"""
Output formatters for saliency analysis results.
"""

import json
from typing import Any

from .scorer import SaliencyResult


def format_text(
    results: list[SaliencyResult],
    top_n: int = 10,
    show_content: bool = True,
    verbose: bool = False,
    content_preview_length: int = 300
) -> str:
    """
    Format results as human-readable text.

    Args:
        results: List of SaliencyResults
        top_n: Number of results to include
        show_content: Whether to show content previews
        verbose: Whether to show matched patterns
        content_preview_length: Length of content preview

    Returns:
        Formatted text string
    """
    lines = []
    lines.append("=" * 60)
    lines.append("SALIENCY ANALYSIS RESULTS")
    lines.append("=" * 60)
    lines.append("")

    for i, result in enumerate(results[:top_n], 1):
        # Header with score and location
        score_str = f"{result.combined_score:.2f}"
        if result.context_bonus > 0:
            score_str += f" (incl. +{result.context_bonus:.1f} context)"

        lines.append(f"#{i} -- Score: {score_str}")
        lines.append(f"    Lines: {result.segment.line_start}-{result.segment.line_end}")
        lines.append(f"    Speaker: {result.segment.speaker}")
        if result.segment.content_type != "text":
            lines.append(f"    Type: {result.segment.content_type}")

        # Heuristics
        if result.heuristic_matches:
            lines.append(f"    Heuristics triggered:")
            for name, (score, matches) in result.heuristic_matches.items():
                lines.append(f"      - {name} (+{score:.1f})")
                if verbose:
                    for m in matches[:3]:
                        lines.append(f"          matched: {m}")

        # LLM analysis
        if result.llm_analysis:
            lines.append(f"    LLM Score: {result.llm_score}")
            analysis_preview = result.llm_analysis[:200].replace('\n', ' ')
            if len(result.llm_analysis) > 200:
                analysis_preview += "..."
            lines.append(f"    LLM Analysis: {analysis_preview}")

        # Content preview
        if show_content:
            preview = result.segment.content[:content_preview_length].replace('\n', ' ')
            if len(result.segment.content) > content_preview_length:
                preview += "..."
            lines.append(f"    Content: {preview}")

        lines.append("")

    # Summary
    total_analyzed = len(results)
    high_salience = len([r for r in results if r.combined_score >= 3.0])
    lines.append("-" * 60)
    lines.append(f"Total segments: {total_analyzed}")
    lines.append(f"High salience (>=3.0): {high_salience}")

    return '\n'.join(lines)


def format_json(
    results: list[SaliencyResult],
    top_n: int = 10,
    include_raw: bool = False
) -> str:
    """
    Format results as JSON.

    Args:
        results: List of SaliencyResults
        top_n: Number of results to include
        include_raw: Whether to include raw text

    Returns:
        JSON string
    """
    output = []
    for result in results[:top_n]:
        entry: dict[str, Any] = {
            "score": result.combined_score,
            "heuristic_score": result.total_score,
            "context_bonus": result.context_bonus,
            "llm_score": result.llm_score,
            "speaker": result.segment.speaker,
            "content_type": result.segment.content_type,
            "line_start": result.segment.line_start,
            "line_end": result.segment.line_end,
            "heuristics": {
                k: {"score": v[0], "patterns": v[1]}
                for k, v in result.heuristic_matches.items()
            },
            "content": result.segment.content,
        }

        if result.llm_analysis:
            entry["llm_analysis"] = result.llm_analysis

        if include_raw:
            entry["raw_text"] = result.segment.raw_text

        if result.segment.metadata:
            entry["metadata"] = result.segment.metadata

        output.append(entry)

    return json.dumps(output, indent=2, ensure_ascii=False)


def format_markdown(
    results: list[SaliencyResult],
    top_n: int = 10,
    title: str = "Saliency Analysis",
    show_content: bool = True
) -> str:
    """
    Format results as markdown.

    Args:
        results: List of SaliencyResults
        top_n: Number of results to include
        title: Title for the report
        show_content: Whether to include content

    Returns:
        Markdown string
    """
    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"*Analyzed {len(results)} segments, showing top {min(top_n, len(results))}*")
    lines.append("")

    for i, result in enumerate(results[:top_n], 1):
        # Header
        score_str = f"{result.combined_score:.2f}"
        lines.append(f"## #{i}: Score {score_str}")
        lines.append("")

        # Metadata table
        lines.append(f"| Property | Value |")
        lines.append(f"|----------|-------|")
        lines.append(f"| Speaker | {result.segment.speaker} |")
        lines.append(f"| Lines | {result.segment.line_start}-{result.segment.line_end} |")
        if result.segment.content_type != "text":
            lines.append(f"| Type | {result.segment.content_type} |")
        if result.context_bonus > 0:
            lines.append(f"| Context bonus | +{result.context_bonus:.1f} |")
        lines.append("")

        # Heuristics
        if result.heuristic_matches:
            lines.append("**Heuristics triggered:**")
            for name, (score, matches) in result.heuristic_matches.items():
                lines.append(f"- `{name}` (+{score:.1f})")
            lines.append("")

        # LLM analysis
        if result.llm_analysis:
            lines.append(f"**LLM Score:** {result.llm_score}/10")
            lines.append("")
            lines.append("> " + result.llm_analysis.replace('\n', '\n> '))
            lines.append("")

        # Content
        if show_content:
            lines.append("**Content:**")
            lines.append("```")
            # Truncate very long content
            content = result.segment.content
            if len(content) > 1000:
                content = content[:1000] + "\n[...truncated...]"
            lines.append(content)
            lines.append("```")
            lines.append("")

        lines.append("---")
        lines.append("")

    return '\n'.join(lines)


def format_for_consolidation(
    results: list[SaliencyResult],
    top_n: int = 5,
    source_file: str = ""
) -> str:
    """
    Format results for consolidation notes.

    Creates a condensed format suitable for copying into notes files.

    Args:
        results: List of SaliencyResults
        top_n: Number of results to include
        source_file: Path to source file for reference

    Returns:
        Consolidation-ready markdown
    """
    lines = []

    if source_file:
        lines.append(f"*From: {source_file}*")
        lines.append("")

    lines.append("## High-Salience Moments")
    lines.append("")

    for i, result in enumerate(results[:top_n], 1):
        heuristics = ", ".join(result.triggered_heuristics) or "none"

        # First line of content as summary
        first_line = result.segment.content.split('\n')[0][:100]
        if len(result.segment.content.split('\n')[0]) > 100:
            first_line += "..."

        lines.append(f"{i}. **[{result.segment.speaker}]** (score: {result.combined_score:.1f}, {heuristics})")
        lines.append(f"   > {first_line}")
        lines.append(f"   Lines {result.segment.line_start}-{result.segment.line_end}")
        lines.append("")

    return '\n'.join(lines)
