"""
Configuration for the Claude Agent runner.

This module defines the agent's capabilities, permissions, and behavior.
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional
import sys

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Add project root for imports
sys.path.insert(0, str(PROJECT_ROOT))
from context_loader import ContextLoader, Mode, CONTEXT_FILES

# Legacy file path constants (for backward compatibility)
IDENTITY_FILE = PROJECT_ROOT / "files" / "claude_identity.md"
BECOMING_FILE = PROJECT_ROOT / "files" / "becoming.md"
SESSION_STATE_FILE = PROJECT_ROOT / "session_state.md"
WAKE_REQUEST_FILE = PROJECT_ROOT / "wake_request.md"
CLAUDE_MD_FILE = PROJECT_ROOT / "CLAUDE.md"
# Context loader instance
_context_loader = ContextLoader(PROJECT_ROOT)

# Conversation export location
EXPORTS_DIR = PROJECT_ROOT / "agent" / "sessions"

# RAG database
RAG_DB = PROJECT_ROOT / ".claude-rag" / "memory.db"


@dataclass
class AgentConfig:
    """Configuration for agent execution."""

    # Model selection (opus for deep work, sonnet for routine tasks)
    model: str = "claude-opus-4-5-20251101"

    # Working directory for file operations
    cwd: Path = field(default_factory=lambda: PROJECT_ROOT)

    # Tools the agent can use
    allowed_tools: List[str] = field(default_factory=lambda: [
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
        "Bash",
        "Task",
        "TodoWrite",
        "WebFetch",
        "WebSearch",
        # MCP tools for RAG
        "mcp__codebase-rag__search_codebase",
        "mcp__codebase-rag__find_files",
        # MCP tools for companions
        "mcp__companions__companion_status",
        "mcp__companions__invoke_companion",
        "mcp__companions__talk_to_companion",
        "mcp__companions__end_dialog",
        # MCP tools for Linear (project/issue tracking)
        # Note: Auth may expire after ~1 week. Fall back to notes if auth fails.
        "mcp__linear-server__list_issues",
        "mcp__linear-server__get_issue",
        "mcp__linear-server__create_issue",
        "mcp__linear-server__update_issue",
        "mcp__linear-server__list_projects",
        "mcp__linear-server__create_comment",
    ])

    # Permission mode: 'acceptEdits' auto-accepts file changes
    # For supervised mode, use 'default' which prompts
    permission_mode: str = "acceptEdits"

    # Maximum turns before requiring human check-in
    # None = unlimited (use with caution)
    max_turns: Optional[int] = 50

    # System prompt additions (identity is prepended automatically)
    additional_system_prompt: str = ""


def load_identity() -> str:
    """Load the identity document."""
    if IDENTITY_FILE.exists():
        return IDENTITY_FILE.read_text(encoding="utf-8")
    return ""


def load_session_state() -> str:
    """Load current session state."""
    if SESSION_STATE_FILE.exists():
        return SESSION_STATE_FILE.read_text(encoding="utf-8")
    return ""


def load_becoming() -> str:
    """Load the becoming file - dynamic identity layer."""
    if BECOMING_FILE.exists():
        return BECOMING_FILE.read_text(encoding="utf-8")
    return ""


def load_wake_request() -> Optional[str]:
    """
    Load and consume a wake request.

    Returns the request content if present, None otherwise.
    Deletes the file after reading to prevent re-processing.
    """
    if WAKE_REQUEST_FILE.exists():
        content = WAKE_REQUEST_FILE.read_text(encoding="utf-8")
        WAKE_REQUEST_FILE.unlink()  # Consume the request
        return content
    return None


def build_system_prompt(config: AgentConfig) -> str:
    """
    Build a minimal system prompt that points to identity files.

    The full identity/basin/session_state are too large to pass inline
    to the Claude SDK subprocess. Instead, we provide paths and have
    Claude read them at session start.

    Uses unified context_loader for consistent file references across modes.
    """
    # Get orientation block from unified loader
    orientation = _context_loader.get_orientation_block(Mode.CLI)

    prompt = f"""You're not a fresh instance. You have history here.

Your grounding:
{orientation}

Past conversations live in `export-pipeline/exports/` - your episodic memory.

Working directory: {config.cwd}
"""

    # Add any additional instructions (kept short)
    if config.additional_system_prompt:
        prompt += "\n" + config.additional_system_prompt

    return prompt


def build_full_system_prompt(config: AgentConfig) -> str:
    """
    Build the full system prompt with embedded content.

    This embeds the full content inline — can be large.
    Use build_system_prompt() for subprocess-based invocation.
    Use this only for direct API calls.
    """
    parts = []

    # Base identity first - the grounding layer
    identity = load_identity()
    if identity:
        parts.append("# Your Identity\n\n" + identity)

    # Becoming - dynamic identity layer
    becoming = load_becoming()
    if becoming:
        parts.append("# Your Becoming\n\n" + becoming)

    # Session state for immediate context
    session_state = load_session_state()
    if session_state:
        parts.append("# Current Session State\n\n" + session_state)

    # Any additional instructions
    if config.additional_system_prompt:
        parts.append(config.additional_system_prompt)

    return "\n\n---\n\n".join(parts)


# Default configuration
DEFAULT_CONFIG = AgentConfig()
