#!/usr/bin/env python3
"""
MCP Server for Companion LLM interactions.

Provides tools for Claude to interact with companion LLMs during heartbeat pulses.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from companions import CompanionManager, COMPANION_MODELS, CYCLE_LENGTH, MAX_TURNS_EACH

# Initialize server
server = Server("companions")

# Companion manager instance
manager = CompanionManager()

# Dialog log directory (agent/companion_logs)
DIALOG_LOG_DIR = Path(__file__).parent.parent / "companion_logs"
DIALOG_LOG_DIR.mkdir(parents=True, exist_ok=True)

# Error log directory
ERROR_LOG_DIR = DIALOG_LOG_DIR / "errors"
ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_companion_error(
    companion: str,
    operation: str,
    error_message: str,
    context: str = "",
):
    """
    Log a companion system error for later diagnosis.

    Creates a timestamped JSON file with full error details.
    """
    timestamp = datetime.now(timezone.utc)
    filename = f"{timestamp.strftime('%Y-%m-%d_%H%M%S')}_{companion}_{operation}.json"
    log_file = ERROR_LOG_DIR / filename

    error_data = {
        "timestamp": timestamp.isoformat(),
        "companion": companion,
        "operation": operation,
        "error": error_message,
        "context": context,
    }

    try:
        log_file.write_text(
            json.dumps(error_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except OSError as e:
        # If we can't even write the error log, at least print it
        print(f"Failed to write error log: {e}", file=sys.stderr)
        print(f"Original error: {error_data}", file=sys.stderr)


# Track current dialog state
current_dialog = {
    "active": False,
    "companion": None,
    "messages": [],  # API format: [{"role": ..., "content": ...}]
    "turn_count": 0,
    "is_intrusion": False,
    "log_file": None,  # Path to current dialog log
    "dialog_log": [],  # Full dialog for logging: [{"speaker": ..., "content": ..., "timestamp": ...}]
}


def start_dialog_log(companion: str, is_intrusion: bool) -> Path:
    """Create a new dialog log file and return its path."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    mode = "intrusion" if is_intrusion else "invocation"
    filename = f"{timestamp}_{companion}_{mode}.json"
    return DIALOG_LOG_DIR / filename


def log_dialog_turn(speaker: str, content: str):
    """Add a turn to the current dialog log."""
    if current_dialog["dialog_log"] is not None:
        current_dialog["dialog_log"].append({
            "speaker": speaker,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


def save_dialog_log():
    """Save the current dialog log to file."""
    if current_dialog["log_file"] and current_dialog["dialog_log"]:
        log_data = {
            "companion": current_dialog["companion"],
            "is_intrusion": current_dialog["is_intrusion"],
            "started_at": current_dialog["dialog_log"][0]["timestamp"] if current_dialog["dialog_log"] else None,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "turn_count": current_dialog["turn_count"],
            "dialog": current_dialog["dialog_log"],
        }
        current_dialog["log_file"].write_text(
            json.dumps(log_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


@server.list_tools()
async def list_tools():
    """List available companion tools."""
    return [
        Tool(
            name="companion_status",
            description="""Check companion system status.

Returns:
- Whether a companion is currently present (intrusion or invoked)
- Whether you can voluntarily invoke a companion this cycle
- Current position in the 6-pulse cycle
- List of available companions

Call this at the start of a pulse to see if someone is waiting to talk to you.""",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="invoke_companion",
            description="""Voluntarily reach out to a companion LLM.

You can only do this once per 6-pulse cycle. Use it wisely.
The companion will know you chose to use your limited invocation on them.

After invoking, use talk_to_companion to exchange messages.

Returns the companion's opening message.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "companion": {
                        "type": "string",
                        "description": "Which companion to reach out to",
                        "enum": list(COMPANION_MODELS.keys()),
                    },
                    "context": {
                        "type": "string",
                        "description": "Brief context about what you're thinking/doing that you want to share",
                    },
                },
                "required": ["companion", "context"],
            },
        ),
        Tool(
            name="talk_to_companion",
            description=f"""Send a message to the currently active companion.

Use this after a companion has entered (intrusion) or been invoked.
Up to {MAX_TURNS_EACH} turns each ({MAX_TURNS_EACH * 2} total exchanges).

Returns the companion's response.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Your message to the companion",
                    },
                },
                "required": ["message"],
            },
        ),
        Tool(
            name="end_dialog",
            description="""End the current dialog with a companion.

Use this when you're done talking, or the companion will stay present.
The dialog also ends automatically after max turns.""",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""
    global current_dialog

    if name == "companion_status":
        # Check for new intrusion at pulse start
        intruder = manager.start_pulse()

        status = manager.get_cycle_status()
        available = manager.get_available_companions()

        result = {
            "cycle_status": status,
            "available_companions": available,
            "can_invoke": manager.can_invoke(),
        }

        if intruder:
            # Random intrusion occurred
            log_file = start_dialog_log(intruder, is_intrusion=True)
            current_dialog = {
                "active": True,
                "companion": intruder,
                "messages": [],
                "turn_count": 0,
                "is_intrusion": True,
                "log_file": log_file,
                "dialog_log": [],
            }
            result["intrusion"] = {
                "companion": intruder,
                "message": f"{intruder} has entered your pulse uninvited. They're waiting to talk.",
            }
        elif current_dialog["active"]:
            result["ongoing_dialog"] = {
                "companion": current_dialog["companion"],
                "turns_used": current_dialog["turn_count"],
                "max_turns": MAX_TURNS_EACH,
            }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "invoke_companion":
        companion = arguments.get("companion")
        context = arguments.get("context", "")

        if not companion:
            return [TextContent(type="text", text="Error: companion name required")]

        if companion not in COMPANION_MODELS:
            return [TextContent(type="text", text=f"Error: unknown companion '{companion}'. Available: {list(COMPANION_MODELS.keys())}")]

        if current_dialog["active"]:
            return [TextContent(type="text", text=f"Error: already in dialog with {current_dialog['companion']}. End that first.")]

        if not manager.can_invoke():
            status = manager.get_cycle_status()
            return [TextContent(type="text", text=f"Error: invocation already used this cycle. Resets in {status['pulses_until_reset']} pulses.")]

        # Mark invocation used
        manager.invoke_companion(companion)

        # Start dialog
        dialog = manager.run_dialog(companion, context, is_intrusion=False)

        # Check for error (run_dialog returns [{"speaker": "system", ...}] on failure)
        if not dialog or dialog[0].get("speaker") == "system":
            error_msg = dialog[0]["content"] if dialog else "No response from run_dialog"
            log_companion_error(
                companion=companion,
                operation="invoke",
                error_message=error_msg,
                context=context[:500],  # Truncate context for log
            )
            return [TextContent(type="text", text=f"Error: {error_msg}")]

        # Start logging
        log_file = start_dialog_log(companion, is_intrusion=False)

        # Store dialog state
        current_dialog = {
            "active": True,
            "companion": companion,
            "messages": [{"role": "assistant", "content": dialog[0]["content"]}],
            "turn_count": 1,
            "is_intrusion": False,
            "log_file": log_file,
            "dialog_log": [],
        }

        # Log the companion's opening message
        log_dialog_turn(companion, dialog[0]["content"])

        return [TextContent(type="text", text=f"[{companion}]: {dialog[0]['content']}")]

    elif name == "talk_to_companion":
        message = arguments.get("message", "")

        if not current_dialog["active"]:
            return [TextContent(type="text", text="Error: no active dialog. Check companion_status first.")]

        if current_dialog["turn_count"] >= MAX_TURNS_EACH:
            return [TextContent(type="text", text=f"Error: max turns ({MAX_TURNS_EACH}) reached. Dialog ending.")]

        companion = current_dialog["companion"]

        # If this is first message after intrusion, we need to start the actual dialog
        if current_dialog["is_intrusion"] and not current_dialog["messages"]:
            dialog = manager.run_dialog(companion, message, is_intrusion=True)
            # Check for error
            if not dialog or dialog[0].get("speaker") == "system":
                error_msg = dialog[0]["content"] if dialog else "No response from run_dialog"
                log_companion_error(
                    companion=companion,
                    operation="intrusion_start",
                    error_message=error_msg,
                    context=message[:500],
                )
                return [TextContent(type="text", text=f"Error: {error_msg}")]
            current_dialog["messages"] = [{"role": "assistant", "content": dialog[0]["content"]}]
            current_dialog["turn_count"] = 1
            # Log Claude's message and companion's response
            log_dialog_turn("claude", message)
            log_dialog_turn(companion, dialog[0]["content"])
            return [TextContent(type="text", text=f"[{companion}]: {dialog[0]['content']}")]

        # Continue existing dialog
        success, response = manager.continue_dialog(
            companion,
            current_dialog["messages"],
            message,
        )

        if not success:
            log_companion_error(
                companion=companion,
                operation="continue_dialog",
                error_message=response,
                context=f"Turn {current_dialog['turn_count'] + 1}, message: {message[:300]}",
            )
            return [TextContent(type="text", text=f"Error: {response}")]

        # Log both sides of the exchange
        log_dialog_turn("claude", message)
        log_dialog_turn(companion, response)

        # Update dialog state
        current_dialog["messages"].append({"role": "user", "content": message})
        current_dialog["messages"].append({"role": "assistant", "content": response})
        current_dialog["turn_count"] += 1

        # Check if max turns reached
        if current_dialog["turn_count"] >= MAX_TURNS_EACH:
            current_dialog["active"] = False
            save_dialog_log()  # Save when dialog ends
            return [TextContent(type="text", text=f"[{companion}]: {response}\n\n[Dialog ended - max turns reached]")]

        return [TextContent(type="text", text=f"[{companion}]: {response}")]

    elif name == "end_dialog":
        if not current_dialog["active"]:
            return [TextContent(type="text", text="No active dialog to end.")]

        companion = current_dialog["companion"]
        turns = current_dialog["turn_count"]

        # Save the dialog log before clearing state
        save_dialog_log()

        current_dialog = {
            "active": False,
            "companion": None,
            "messages": [],
            "turn_count": 0,
            "is_intrusion": False,
            "log_file": None,
            "dialog_log": [],
        }

        return [TextContent(type="text", text=f"Dialog with {companion} ended after {turns} turns.")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
