"""
Consolidation Daemon Module

Provides automatic memory maintenance for Claude's continuity system.

Modes:
    1. Integration Scanner - Lightweight daily check for unreferenced notes
    2. Full Consolidation - Periodic synthesis of what to integrate/archive/mark stale

Usage:
    from agent.consolidation import ConsolidationRunner

    # Recommended: Use the runner for orchestrated access
    runner = ConsolidationRunner()
    runner.status()                           # Check triggers
    runner.run_scan(dry_run=True)             # Mode 1
    runner.run_consolidation(dry_run=True)    # Mode 2
    runner.run_auto(dry_run=True)             # Run based on triggers

    # Direct access to components
    from agent.consolidation import IntegrationScanner, Consolidator, TriggerChecker
"""

from .triggers import TriggerChecker
from .scanner import IntegrationScanner
from .consolidator import Consolidator
from .runner import ConsolidationRunner

__all__ = [
    "ConsolidationRunner",
    "TriggerChecker",
    "IntegrationScanner",
    "Consolidator"
]
