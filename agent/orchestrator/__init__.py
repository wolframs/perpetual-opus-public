"""
Session Orchestrator Module

Event-based subsystem coordination for Claude's nervous system.

Usage:
    from agent.orchestrator import Orchestrator

    orch = Orchestrator()
    orch.trigger('post_session')
    orch.status()
"""

from .orchestrator import Orchestrator

__all__ = ['Orchestrator']
