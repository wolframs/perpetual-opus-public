"""
Parsers for conversation transcript formats.

Handles:
- Markdown (perpetual-opus export format with === Human/Assistant ===)
- JSONL (perpetual-opus export format with nested content blocks)
- Plain text
- HTML
"""

import json
import re
import html.parser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class ConversationSegment:
    """A segment of conversation with speaker and content."""
    speaker: Literal["human", "assistant", "system", "unknown"]
    content: str
    line_start: int
    line_end: int
    raw_text: str = ""
    content_type: str = "text"  # text, thinking, tool_use, tool_result
    metadata: dict = field(default_factory=dict)

    @property
    def is_thinking(self) -> bool:
        return self.content_type == "thinking"


class HTMLTextExtractor(html.parser.HTMLParser):
    """Extract text from HTML."""
    def __init__(self):
        super().__init__()
        self.text_parts = []

    def handle_data(self, data):
        self.text_parts.append(data)

    def get_text(self) -> str:
        return ' '.join(self.text_parts)


# =============================================================================
# MARKDOWN PARSER (perpetual-opus export format)
# =============================================================================

def parse_markdown(content: str, include_thinking: bool = True) -> list[ConversationSegment]:
    """
    Parse markdown conversation format.

    Handles perpetual-opus exports which use:
    - === H === / === C === for speaker blocks (also supports legacy === Human === / === Assistant ===)
    - <thinking> or markers for thinking blocks
    - <tool> / <tool_result> for tool interactions
    """
    segments = []
    lines = content.split('\n')
    current_speaker = None
    current_content = []
    current_start = 0
    current_type = "text"
    in_thinking = False

    # perpetual-opus export format patterns
    # Supports both old (Human/Assistant) and new (W/C) formats
    speaker_pattern = re.compile(r'^===\s*(Human|Assistant|System|W|C)\s*===\s*$', re.IGNORECASE)
    thinking_start = re.compile(r'^<thinking>|^\s*$', re.IGNORECASE)
    thinking_end = re.compile(r'^</thinking>|^\s*$', re.IGNORECASE)

    # Alternative patterns for other markdown formats
    alt_speaker_patterns = [
        re.compile(r'^(?:Human|User|H):\s*(.*)$', re.IGNORECASE),
        re.compile(r'^(?:Assistant|Claude|A):\s*(.*)$', re.IGNORECASE),
        re.compile(r'^\*\*(?:Human|User)\*\*:\s*(.*)$', re.IGNORECASE),
        re.compile(r'^\*\*(?:Assistant|Claude)\*\*:\s*(.*)$', re.IGNORECASE),
    ]

    def save_segment(end_line: int):
        nonlocal current_speaker, current_content, current_start, current_type
        if current_speaker and current_content:
            content_text = '\n'.join(current_content).strip()
            if content_text:
                # Skip thinking blocks if not wanted
                if current_type == "thinking" and not include_thinking:
                    return
                segments.append(ConversationSegment(
                    speaker=current_speaker,
                    content=content_text,
                    line_start=current_start,
                    line_end=end_line,
                    raw_text='\n'.join(lines[current_start:end_line + 1]),
                    content_type=current_type
                ))

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check for perpetual-opus speaker markers
        speaker_match = speaker_pattern.match(line)
        if speaker_match:
            save_segment(i - 1)
            speaker = speaker_match.group(1).lower()
            # Map both old (human/assistant) and new (w/c) formats
            if speaker in ("human", "w"):
                current_speaker = "human"
            elif speaker in ("assistant", "c"):
                current_speaker = "assistant"
            elif speaker == "system":
                current_speaker = "system"
            else:
                current_speaker = "unknown"
            current_content = []
            current_start = i + 1
            current_type = "text"
            in_thinking = False
            i += 1
            continue

        # Check for thinking block markers
        # Note: perpetual-opus exports use <thinking> tags, some exports use special chars
        thinking_marker = '<thinking>' in line.lower()
        if thinking_marker and not in_thinking:
            if current_speaker:
                save_segment(i - 1)
                current_content = []
                current_start = i
                current_type = "thinking"
                in_thinking = True
        elif in_thinking and '</thinking>' in line.lower():
            # End of thinking block
            current_content.append(line)
            save_segment(i)
            current_content = []
            current_start = i + 1
            current_type = "text"
            in_thinking = False
            i += 1
            continue

        # Check for alternative speaker patterns
        alt_match = None
        for pattern in alt_speaker_patterns:
            m = pattern.match(line)
            if m:
                alt_match = (pattern, m)
                break

        if alt_match:
            save_segment(i - 1)
            pattern, m = alt_match
            pattern_str = pattern.pattern.lower()
            if 'human' in pattern_str or 'user' in pattern_str:
                current_speaker = 'human'
            else:
                current_speaker = 'assistant'
            current_content = [m.group(1)] if m.groups() and m.group(1) else []
            current_start = i
            current_type = "text"
            i += 1
            continue

        # Regular content line
        if current_speaker:
            current_content.append(line)

        i += 1

    # Don't forget the last segment
    save_segment(len(lines) - 1)

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


# =============================================================================
# JSONL PARSER (perpetual-opus export format)
# =============================================================================

def parse_jsonl(content: str, include_thinking: bool = True) -> list[ConversationSegment]:
    """
    Parse JSONL conversation format.

    Handles perpetual-opus exports which have:
    - type: "message"
    - sender: "human" or "assistant"
    - content: array of content blocks with type (text, thinking, tool_use, tool_result)
    """
    segments = []
    lines = content.strip().split('\n')

    for i, line in enumerate(lines):
        if not line.strip():
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Skip non-message lines (metadata, etc.)
        if obj.get('type') != 'message':
            # But still try to extract if it looks like a message
            if 'content' not in obj and 'text' not in obj:
                continue

        # Get speaker
        speaker = obj.get('sender') or obj.get('role') or obj.get('from') or 'unknown'
        speaker = speaker.lower()
        if speaker in ['user']:
            speaker = 'human'
        elif speaker in ['claude', 'ai', 'bot']:
            speaker = 'assistant'

        # Extract content blocks
        content_field = obj.get('content')

        if isinstance(content_field, list):
            # perpetual-opus format: array of content blocks
            for block in content_field:
                if isinstance(block, dict):
                    block_type = block.get('type', 'text')

                    # Skip thinking if not wanted
                    if block_type == 'thinking' and not include_thinking:
                        continue

                    # Get the text content
                    text = block.get('text') or block.get('thinking') or block.get('content') or ''

                    if text:
                        segments.append(ConversationSegment(
                            speaker=speaker,
                            content=text,
                            line_start=i,
                            line_end=i,
                            raw_text=line,
                            content_type=block_type,
                            metadata={
                                'uuid': obj.get('uuid'),
                                'created_at': obj.get('created_at'),
                            }
                        ))
                elif isinstance(block, str):
                    segments.append(ConversationSegment(
                        speaker=speaker,
                        content=block,
                        line_start=i,
                        line_end=i,
                        raw_text=line
                    ))

        elif isinstance(content_field, str):
            # Simple string content
            segments.append(ConversationSegment(
                speaker=speaker,
                content=content_field,
                line_start=i,
                line_end=i,
                raw_text=line
            ))

        elif 'text' in obj:
            # Fallback: text field directly on object
            segments.append(ConversationSegment(
                speaker=speaker,
                content=obj['text'],
                line_start=i,
                line_end=i,
                raw_text=line
            ))

    return segments


# =============================================================================
# OTHER PARSERS
# =============================================================================

def parse_html(content: str, include_thinking: bool = True) -> list[ConversationSegment]:
    """Parse HTML, extract text, then parse as markdown."""
    extractor = HTMLTextExtractor()
    extractor.feed(content)
    text = extractor.get_text()
    return parse_markdown(text, include_thinking)


def parse_txt(content: str, include_thinking: bool = True) -> list[ConversationSegment]:
    """Parse plain text as markdown (same heuristics apply)."""
    return parse_markdown(content, include_thinking)


# =============================================================================
# UNIFIED PARSER
# =============================================================================

def parse_file(
    filepath: Path | str,
    include_thinking: bool = True
) -> list[ConversationSegment]:
    """
    Parse a file based on its extension.

    Args:
        filepath: Path to the file
        include_thinking: Whether to include thinking blocks in output

    Returns:
        List of conversation segments
    """
    filepath = Path(filepath)
    content = filepath.read_text(encoding='utf-8')
    suffix = filepath.suffix.lower()

    parsers = {
        '.md': parse_markdown,
        '.markdown': parse_markdown,
        '.jsonl': parse_jsonl,
        '.json': parse_jsonl,
        '.html': parse_html,
        '.htm': parse_html,
        '.txt': parse_txt,
    }

    parser = parsers.get(suffix, parse_markdown)
    return parser(content, include_thinking)


def parse_string(
    content: str,
    format: Literal["markdown", "jsonl", "html", "txt"] = "markdown",
    include_thinking: bool = True
) -> list[ConversationSegment]:
    """
    Parse a string in the specified format.

    Args:
        content: The content to parse
        format: The format of the content
        include_thinking: Whether to include thinking blocks

    Returns:
        List of conversation segments
    """
    parsers = {
        "markdown": parse_markdown,
        "jsonl": parse_jsonl,
        "html": parse_html,
        "txt": parse_txt,
    }
    parser = parsers.get(format, parse_markdown)
    return parser(content, include_thinking)
