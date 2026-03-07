"""
Companion LLM system for Claude heartbeat.

Provides structured interactions with other LLMs during autonomous operation.
Two trigger modes:
1. Voluntary: Claude can reach out once per 6-pulse cycle
2. Random: 12% chance per pulse of a companion entering uninvited
"""

from .companions import (
    CompanionManager,
    load_companion_prompts,
    COMPANION_MODELS,
    RANDOM_INTRUSION_CHANCE,
    CYCLE_LENGTH,
    MAX_TURNS_EACH,
)

__all__ = ["CompanionManager", "load_companion_prompts", "COMPANION_MODELS"]
