"""
Claude Agent Runner

Main entry point for autonomous agent execution.
Uses the Anthropic Agent SDK to run Claude with full tool access.

Usage:
    python runner.py                     # Interactive mode
    python runner.py --prompt "..."      # Single prompt mode
    python runner.py --wake              # Check for wake_request.md and process it
    python runner.py --continue-session <id>  # Resume a previous session
"""

import anyio
import argparse
import os
import sys
from pathlib import Path
from typing import Optional

# Fix encoding for stdout/stderr (prevents cp1252 errors on Windows)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    UserMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    HookMatcher,
)

# Patch SDK message parser to skip unknown message types (e.g. rate_limit_event)
# instead of crashing the entire response stream.
import logging as _logging
import claude_agent_sdk._internal.message_parser as _msg_parser
from claude_agent_sdk._errors import MessageParseError

_sdk_logger = _logging.getLogger("agent.sdk_patch")
_original_parse = _msg_parser.parse_message

def _resilient_parse(data):
    try:
        return _original_parse(data)
    except MessageParseError as e:
        if "Unknown message type" in str(e):
            _sdk_logger.debug("Skipping unknown message type: %s", data.get("type"))
            return None
        raise

_msg_parser.parse_message = _resilient_parse

from config import (
    AgentConfig,
    DEFAULT_CONFIG,
    build_system_prompt,
    load_wake_request,
    PROJECT_ROOT,
)
from session import SessionManager, update_runner_state
from hooks import pre_tool_use_hook, post_task_hook
from memory_companion.hook import memory_companion_hook


def build_options(config: AgentConfig) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions from our config."""
    import sys

    # Configure MCP servers
    mcp_servers = {}

    # RAG for episodic memory
    rag_server_path = PROJECT_ROOT / ".claude-rag" / "mcp_server.py"
    if rag_server_path.exists():
        mcp_servers["codebase-rag"] = {
            "type": "stdio",
            "command": sys.executable,
            "args": [str(rag_server_path)],
        }

    # Companions for LLM interactions during pulses
    companions_server_path = PROJECT_ROOT / "agent" / "companions" / "mcp_server.py"
    if companions_server_path.exists():
        mcp_servers["companions"] = {
            "type": "stdio",
            "command": sys.executable,
            "args": [str(companions_server_path)],
        }

    # Linear for project/issue tracking
    linear_api_key = os.environ.get("LINEAR_API_KEY")
    linear_config: dict = {
        "type": "http",
        "url": "https://mcp.linear.app/mcp",
    }
    if linear_api_key:
        linear_config["headers"] = {
            "Authorization": f"Bearer {linear_api_key}",
        }
    mcp_servers["linear-server"] = linear_config

    return ClaudeAgentOptions(
        system_prompt=build_system_prompt(config),
        max_turns=config.max_turns,
        allowed_tools=config.allowed_tools,
        permission_mode=config.permission_mode,
        cwd=str(config.cwd),
        mcp_servers=mcp_servers if mcp_servers else None,
        hooks={
            "UserPromptSubmit": [
                HookMatcher(matcher=None, hooks=[memory_companion_hook]),
            ],
            "PreToolUse": [
                HookMatcher(matcher="*", hooks=[pre_tool_use_hook]),
            ],
            "PostToolUse": [
                HookMatcher(matcher="Task", hooks=[post_task_hook]),
            ],
        },
    )


async def run_interactive(config: AgentConfig):
    """Run in interactive mode - continuous conversation with human input."""
    session_manager = SessionManager()
    session = session_manager.start_session()

    print(f"\n{'='*60}")
    print("Claude Agent - Interactive Mode")
    print(f"Session: {session.session_id}")
    print(f"{'='*60}")
    print("Type your messages. Enter 'quit' or 'exit' to end.")
    print("Enter 'save' to save and pause the session.")
    print(f"{'='*60}\n")

    options = build_options(config)

    async with ClaudeSDKClient(options=options) as client:
        while True:
            try:
                # Get human input
                user_input = input("\nYou: ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ["quit", "exit"]:
                    session_manager.end_session("completed")
                    print("\nSession ended.")
                    break

                if user_input.lower() == "save":
                    session_manager.end_session("paused", "Paused by user request")
                    print(f"\nSession saved: {session.session_id}")
                    break

                # Send to Claude
                session_manager.add_message("human", user_input)
                update_runner_state("ACTIVE", f"Processing: {user_input[:100]}...")

                await client.query(user_input)

                # Process response
                print("\nClaude: ", end="", flush=True)
                full_response = []

                async for msg in client.receive_response():
                    if msg is None:
                        continue
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock):
                                print(block.text, end="", flush=True)
                                full_response.append(block.text)
                            elif isinstance(block, ToolUseBlock):
                                print(f"\n[Using tool: {block.name}]", flush=True)
                                full_response.append(f"\n[Tool: {block.name}]")

                print()  # Newline after response

                if full_response:
                    session_manager.add_message("assistant", "".join(full_response))
                    session_manager.save_session()

            except KeyboardInterrupt:
                session_manager.end_session("interrupted")
                print("\n\nSession interrupted.")
                break
            except Exception as e:
                print(f"\nError: {e}")
                session_manager.save_session()


async def run_single_prompt(config: AgentConfig, prompt: str):
    """Run a single prompt and exit."""
    session_manager = SessionManager()
    session = session_manager.start_session(prompt)

    update_runner_state("ACTIVE", f"Single prompt: {prompt[:100]}...")

    options = build_options(config)

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)

        full_response = []
        async for msg in client.receive_response():
            if msg is None:
                continue
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        print(block.text, end="", flush=True)
                        full_response.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        print(f"\n[Using tool: {block.name}]")
                        full_response.append(f"\n[Tool: {block.name}]")

        print()

        if full_response:
            session_manager.add_message("assistant", "".join(full_response))

    session_manager.end_session("completed")
    update_runner_state("COMPLETED", notes=f"Processed prompt: {prompt[:100]}...")


async def run_wake_check(config: AgentConfig):
    """Check for wake request and process it."""
    wake_request = load_wake_request()

    if not wake_request:
        print("No wake request found.")
        return

    print(f"Found wake request:\n{wake_request}\n")
    print("Processing...")

    await run_single_prompt(config, wake_request)


def main():
    parser = argparse.ArgumentParser(description="Claude Agent Runner")
    parser.add_argument("--prompt", "-p", help="Single prompt to process")
    parser.add_argument("--prompt-file", help="Read prompt from file (avoids command-line length limits)")
    parser.add_argument("--wake", "-w", action="store_true", help="Check and process wake_request.md")
    parser.add_argument("--continue-session", "-c", help="Continue a previous session")
    parser.add_argument("--max-turns", "-t", type=int, help="Maximum conversation turns")
    parser.add_argument("--supervised", "-s", action="store_true", help="Run in supervised mode (prompt for file changes)")

    args = parser.parse_args()

    config = AgentConfig(
        max_turns=args.max_turns if args.max_turns else DEFAULT_CONFIG.max_turns,
        permission_mode="default" if args.supervised else DEFAULT_CONFIG.permission_mode,
    )

    # Resolve prompt from --prompt or --prompt-file
    prompt = args.prompt
    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        if not prompt_path.exists():
            print(f"Error: prompt file not found: {args.prompt_file}", file=sys.stderr)
            sys.exit(1)
        prompt = prompt_path.read_text(encoding="utf-8")

    if args.wake:
        anyio.run(run_wake_check, config)
    elif prompt:
        anyio.run(run_single_prompt, config, prompt)
    else:
        anyio.run(run_interactive, config)


if __name__ == "__main__":
    main()
