"""
Claude Agent - Autonomous execution layer for perpetual Claude.

This package provides the infrastructure to run Claude autonomously
using the Anthropic Agent SDK, with session management, safety hooks,
and integration with the existing identity/memory systems.
"""

from .config import AgentConfig, DEFAULT_CONFIG, load_identity, load_wake_request
from .session import Session, SessionManager, update_runner_state
from .hooks import pre_tool_use_hook

__all__ = [
    "AgentConfig",
    "DEFAULT_CONFIG",
    "load_identity",
    "load_wake_request",
    "Session",
    "SessionManager",
    "update_runner_state",
    "pre_tool_use_hook",
]
