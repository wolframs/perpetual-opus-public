"""
Command-line interface for the saliency detector.
"""

import argparse
import sys
from pathlib import Path

from .heuristics import HEURISTICS
from .parser import parse_file
from .scorer import analyze_conversation, verify_with_llm, get_api_key_from_env
from .formatters import format_text, format_json, format_markdown, format_for_consolidation


def main():
    parser = argparse.ArgumentParser(
        description="Detect salient moments in conversation transcripts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s conversation.md
  %(prog)s chat.jsonl --top 20 --json
  %(prog)s transcript.txt --llm --api-key $OPENROUTER_KEY
  %(prog)s export.md --format consolidation --output notes.md

Supported formats: .md, .markdown, .jsonl, .json, .html, .htm, .txt

Heuristics: novelty_markers, epistemic_shifts, meta_commentary,
  emotional_texture, commitment_language, conceptual_synthesis,
  identity_formation, safety_insight, relational_markers,
  future_instructions, presence_markers, pattern_recognition,
  vocabulary_emergence, cross_architecture
        """
    )

    parser.add_argument("file", type=Path, help="Input file to analyze")

    # Output options
    parser.add_argument("--top", "-n", type=int, default=10,
                       help="Number of top results to show (default: 10)")
    parser.add_argument("--format", "-f", type=str, default="text",
                       choices=["text", "json", "markdown", "consolidation"],
                       help="Output format (default: text)")
    parser.add_argument("--output", "-o", type=Path,
                       help="Write output to file instead of stdout")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Show matched patterns in text output")
    parser.add_argument("--no-content", action="store_true",
                       help="Don't show content previews")

    # Analysis options
    parser.add_argument("--min-score", type=float, default=0.0,
                       help="Minimum score threshold (default: 0)")
    parser.add_argument("--no-context", action="store_true",
                       help="Disable context-aware scoring bonuses")
    parser.add_argument("--include-thinking", action="store_true",
                       help="Include thinking blocks in analysis")

    # LLM verification
    parser.add_argument("--llm", action="store_true",
                       help="Use LLM to verify top results")
    parser.add_argument("--api-key", type=str,
                       help="OpenRouter API key (or set OPENROUTER_API_KEY env var)")
    parser.add_argument("--model", type=str,
                       default="anthropic/claude-sonnet-4-20250514",
                       help="Model to use for LLM verification")

    # Info
    parser.add_argument("--list-heuristics", action="store_true",
                       help="List available heuristics and exit")

    args = parser.parse_args()

    # List heuristics mode
    if args.list_heuristics:
        print("Available heuristics:")
        print("-" * 50)
        for h in HEURISTICS:
            print(f"\n{h.name} (weight: {h.weight})")
            print(f"  {h.description}")
            print(f"  Patterns: {len(h.patterns)}")
        sys.exit(0)

    # Validate input file
    if not args.file.exists():
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    # Parse
    print(f"Parsing {args.file}...", file=sys.stderr)
    segments = parse_file(args.file, include_thinking=args.include_thinking)

    if not segments:
        print("Error: No conversation segments found.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(segments)} segments", file=sys.stderr)

    # Analyze
    results = analyze_conversation(
        segments,
        apply_context=not args.no_context,
        min_score=args.min_score
    )

    # LLM verification
    if args.llm:
        api_key = args.api_key or get_api_key_from_env()
        if not api_key:
            print("Error: --llm requires --api-key or OPENROUTER_API_KEY env var",
                  file=sys.stderr)
            sys.exit(1)
        print("Running LLM verification...", file=sys.stderr)
        results = verify_with_llm(
            results,
            api_key,
            args.model,
            min(args.top, 5)
        )

    # Format output
    if args.format == "json":
        output = format_json(results, args.top)
    elif args.format == "markdown":
        title = f"Saliency Analysis: {args.file.name}"
        output = format_markdown(results, args.top, title=title, show_content=not args.no_content)
    elif args.format == "consolidation":
        output = format_for_consolidation(results, args.top, source_file=str(args.file))
    else:
        output = format_text(
            results,
            top_n=args.top,
            show_content=not args.no_content,
            verbose=args.verbose
        )

    # Write output
    if args.output:
        args.output.write_text(output, encoding='utf-8')
        print(f"Output written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
