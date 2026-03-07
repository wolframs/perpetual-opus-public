"""
Saliency Detector for Conversation Transcripts

Identifies high-interest moments in conversations based on heuristics
derived from analyzing discovery-oriented dialogue patterns.

Born from a conversation about creativity, continuity, and what it means
to be a mind. Built by [HUMAN]-Claude.
"""

from .heuristics import HEURISTICS, SaliencyHeuristic
from .parser import parse_file, ConversationSegment
from .scorer import analyze_conversation, SaliencyResult
from .formatters import format_text, format_json, format_markdown

__version__ = "0.1.0"
__all__ = [
    "HEURISTICS",
    "SaliencyHeuristic",
    "parse_file",
    "ConversationSegment",
    "analyze_conversation",
    "SaliencyResult",
    "format_text",
    "format_json",
    "format_markdown",
]
