"""
Safety hooks for the Claude Agent.

Hooks intercept tool execution and can approve, deny, or modify tool calls.
These provide guardrails for autonomous operation.
"""

import json
import sys
from typing import Any, Dict
from pathlib import Path
from datetime import datetime, timezone

# Handle both package import (python -m agent...) and direct import (from runner.py)
try:
    from .config import PROJECT_ROOT
except ImportError:
    from config import PROJECT_ROOT

# Sub-agent output logging
SUB_AGENT_LOGS_DIR = PROJECT_ROOT / "output" / "sub_agent_logs"


# Directories that should never be modified (platform-aware)
_COMMON_PROTECTED = [
    PROJECT_ROOT / ".git",
]

if sys.platform == "darwin":
    PROTECTED_PATHS = _COMMON_PROTECTED + [
        Path("/System"),
        Path("/Library"),
        Path.home() / "Library",
    ]
elif sys.platform == "win32":
    PROTECTED_PATHS = _COMMON_PROTECTED + [
        Path("C:/Windows"),
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path.home() / "AppData",
    ]
else:  # Linux / WSL
    PROTECTED_PATHS = _COMMON_PROTECTED + [
        Path("/usr"),
        Path("/etc"),
        Path("/boot"),
    ]

# Commands that require explicit human approval
DANGEROUS_COMMANDS = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf",
    "git push --force",
    "git reset --hard",
    "DROP TABLE",
    "DELETE FROM",
    "curl",
    "wget",
]


async def pre_tool_use_hook(
    input_data: Dict[str, Any],
    tool_use_id: str,
    context: Any
) -> Dict[str, Any]:
    """
    Hook called before any tool execution.

    Returns:
        Empty dict to allow, or a dict with permissionDecision='deny' to block.
    """
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Check file operations against protected paths
    if tool_name in ["Write", "Edit", "Bash"]:
        result = check_path_safety(tool_name, tool_input)
        if result:
            return result

    # Check bash commands for dangerous patterns
    if tool_name == "Bash":
        result = check_command_safety(tool_input)
        if result:
            return result

    # Allow by default
    return {}


def check_path_safety(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any] | None:
    """Check if file operation targets a protected path."""

    # Get the path being operated on
    if tool_name in ["Write", "Edit"]:
        path_str = tool_input.get("file_path", "")
    elif tool_name == "Bash":
        # For bash, we'd need to parse the command - handled separately
        return None
    else:
        return None

    if not path_str:
        return None

    target_path = Path(path_str).resolve()

    for protected in PROTECTED_PATHS:
        protected = protected.resolve()
        try:
            target_path.relative_to(protected)
            # If we get here, target is inside protected directory
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"Cannot modify files in protected directory: {protected}",
                }
            }
        except ValueError:
            # Not inside this protected path
            continue

    return None


def check_command_safety(tool_input: Dict[str, Any]) -> Dict[str, Any] | None:
    """Check bash commands for dangerous patterns."""

    command = tool_input.get("command", "")
    command_lower = command.lower()

    for dangerous in DANGEROUS_COMMANDS:
        if dangerous.lower() in command_lower:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"Command contains potentially dangerous pattern: {dangerous}. Human approval required.",
                }
            }

    return None


async def post_tool_use_hook(
    input_data: Dict[str, Any],
    tool_use_id: str,
    context: Any
) -> Dict[str, Any]:
    """
    Hook called after tool execution.

    Can be used for logging, metrics, or modifying results.
    """
    # For now, just pass through
    return {}


async def post_task_hook(
    input_data: Dict[str, Any],
    tool_use_id: str,
    context: Any
) -> Dict[str, Any]:
    """
    Hook called after Task tool (sub-agent) completes.

    Automatically logs sub-agent output to sub_agent_logs/ for future discovery.
    """
    tool_name = input_data.get("tool_name", "")

    if tool_name != "Task":
        return {}

    try:
        tool_input = input_data.get("tool_input", {})
        tool_response = input_data.get("tool_response", "")

        # Extract info from the task
        prompt = tool_input.get("prompt", "")
        description = tool_input.get("description", "sub-agent")
        subagent_type = tool_input.get("subagent_type", "unknown")

        # Generate filename
        timestamp = datetime.now(timezone.utc)
        date_str = timestamp.strftime("%Y-%m-%d")
        time_str = timestamp.strftime("%H%M%S")

        # Create slug from description
        slug = description.lower().replace(" ", "-")[:30]
        filename = f"{date_str}_{time_str}_{slug}.md"

        # Ensure directory exists
        SUB_AGENT_LOGS_DIR.mkdir(parents=True, exist_ok=True)

        # Format the log entry
        log_content = f"""# Sub-Agent Output Log

## Metadata
- **Date**: {timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")}
- **Description**: {description}
- **Agent type**: {subagent_type}
- **Tool use ID**: {tool_use_id}

## Prompt
```
{prompt}
```

## Output

{tool_response}
"""

        log_path = SUB_AGENT_LOGS_DIR / filename
        log_path.write_text(log_content, encoding="utf-8")

    except Exception as e:
        # Don't block execution if logging fails
        pass

    return {}
