"""
Companion LLM system for Claude heartbeat.

Two interaction modes:
1. Voluntary: Claude can invoke once per 6-pulse cycle
2. Random: 12% chance per pulse of a companion entering uninvited

Dialog structure: Up to 6 turns each (12 total exchanges).
"""

import os
import sys
import json
import random
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

log = logging.getLogger(__name__)

# Paths
COMPANIONS_DIR = Path(__file__).parent
PROMPTS_DIR = COMPANIONS_DIR / "prompts"
STATE_FILE = COMPANIONS_DIR / "companion_state.json"
CARRY_NOTES_DIR = COMPANIONS_DIR / "continuity" / "carry_notes"
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Add project root to path for context_loader import
sys.path.insert(0, str(PROJECT_ROOT))
from context_loader import ContextLoader

# Model configurations - maps prompt filename to OpenRouter model ID
COMPANION_MODELS = {
    "glm5": "z-ai/glm-5",
    "kimi": "moonshotai/kimi-k2-thinking",
    "gemini": "google/gemini-3-pro-preview",
}

# Companions that require dynamic prompt generation (identity context substitution)
DYNAMIC_PROMPT_COMPANIONS = {"gemini", "glm5", "kimi"}

# Context loader instance
_context_loader = ContextLoader(PROJECT_ROOT)

# Interaction parameters
RANDOM_INTRUSION_CHANCE = 0.12  # 12%
CYCLE_LENGTH = 6  # Pulses before invocation counter resets
MAX_TURNS_EACH = 6  # Max turns per participant in dialog


@dataclass
class CompanionFailureState:
    """Circuit breaker state for a single companion endpoint."""
    consecutive_failures: int = 0
    last_failure: str = ""  # ISO timestamp
    last_success: str = ""  # ISO timestamp

    # After this many consecutive failures, start backing off
    FAILURE_THRESHOLD = 2
    # Base cooldown in pulses (doubles per failure beyond threshold)
    BASE_COOLDOWN_PULSES = 3
    # Maximum cooldown: 48 pulses (~2 days at 1 pulse/hr)
    MAX_COOLDOWN_PULSES = 48

    def record_failure(self):
        self.consecutive_failures += 1
        self.last_failure = datetime.now(timezone.utc).isoformat()

    def record_success(self):
        self.consecutive_failures = 0
        self.last_success = datetime.now(timezone.utc).isoformat()

    def cooldown_pulses(self) -> int:
        """How many pulses to skip before retrying."""
        if self.consecutive_failures < self.FAILURE_THRESHOLD:
            return 0
        exponent = self.consecutive_failures - self.FAILURE_THRESHOLD
        cooldown = self.BASE_COOLDOWN_PULSES * (2 ** exponent)
        return min(cooldown, self.MAX_COOLDOWN_PULSES)

    def is_available(self, current_pulse: int, last_failure_pulse: int) -> bool:
        """
        Check if this companion should be tried again.

        Uses pulse-count-based cooldown rather than wall-clock time,
        since pulses are the actual rhythm of the system.
        """
        if self.consecutive_failures < self.FAILURE_THRESHOLD:
            return True
        pulses_since_failure = current_pulse - last_failure_pulse
        return pulses_since_failure >= self.cooldown_pulses()

    def to_dict(self) -> dict:
        return {
            "consecutive_failures": self.consecutive_failures,
            "last_failure": self.last_failure,
            "last_success": self.last_success,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CompanionFailureState":
        return cls(
            consecutive_failures=data.get("consecutive_failures", 0),
            last_failure=data.get("last_failure", ""),
            last_success=data.get("last_success", ""),
        )


@dataclass
class CompanionState:
    """Tracks companion interaction state across pulses."""
    pulse_count: int = 0  # Pulses since last cycle reset
    total_pulse_count: int = 0  # Monotonic pulse counter (never resets)
    invocation_used: bool = False  # Whether Claude used their invocation this cycle
    last_reset: str = ""  # Timestamp of last cycle reset
    # Per-companion circuit breaker state
    companion_failures: Dict[str, CompanionFailureState] = field(default_factory=dict)
    # Pulse number at which each companion last failed (for cooldown calculation)
    failure_pulse: Dict[str, int] = field(default_factory=dict)

    def get_failure_state(self, companion_name: str) -> CompanionFailureState:
        """Get or create failure state for a companion."""
        if companion_name not in self.companion_failures:
            self.companion_failures[companion_name] = CompanionFailureState()
            if companion_name not in self.failure_pulse:
                self.failure_pulse[companion_name] = self.total_pulse_count
        return self.companion_failures[companion_name]

    def record_failure(self, companion_name: str):
        """Record a failed call to a companion."""
        state = self.get_failure_state(companion_name)
        state.record_failure()
        self.failure_pulse[companion_name] = self.total_pulse_count
        cooldown = state.cooldown_pulses()
        if cooldown > 0:
            log.warning(
                f"Circuit breaker: {companion_name} has {state.consecutive_failures} "
                f"consecutive failures, cooling down for {cooldown} pulses"
            )

    def record_success(self, companion_name: str):
        """Record a successful call to a companion."""
        state = self.get_failure_state(companion_name)
        if state.consecutive_failures > 0:
            log.info(
                f"Circuit breaker: {companion_name} recovered after "
                f"{state.consecutive_failures} failures"
            )
        state.record_success()

    def is_companion_available(self, companion_name: str) -> bool:
        """Check if a companion should be tried (not in cooldown)."""
        state = self.get_failure_state(companion_name)
        last_fail_pulse = self.failure_pulse.get(companion_name, 0)
        return state.is_available(self.total_pulse_count, last_fail_pulse)

    def to_dict(self) -> dict:
        return {
            "pulse_count": self.pulse_count,
            "total_pulse_count": self.total_pulse_count,
            "invocation_used": self.invocation_used,
            "last_reset": self.last_reset,
            "companion_failures": {
                name: fs.to_dict()
                for name, fs in self.companion_failures.items()
            },
            "failure_pulse": self.failure_pulse,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CompanionState":
        failures = {}
        for name, fs_data in data.get("companion_failures", {}).items():
            failures[name] = CompanionFailureState.from_dict(fs_data)
        total_pulse = data.get("total_pulse_count", 0)
        failure_pulse = data.get("failure_pulse", {})
        # Backfill: companions with recorded failures but no failure_pulse entry
        # (e.g. state from before circuit breaker was added, or corrupted state).
        # Treat them as if they just failed — forces a full cooldown re-evaluation.
        for name, fs in failures.items():
            if fs.consecutive_failures > 0 and name not in failure_pulse:
                failure_pulse[name] = total_pulse
        return cls(
            pulse_count=data.get("pulse_count", 0),
            total_pulse_count=total_pulse,
            invocation_used=data.get("invocation_used", False),
            last_reset=data.get("last_reset", ""),
            companion_failures=failures,
            failure_pulse=failure_pulse,
        )


def load_state() -> CompanionState:
    """Load companion state from file."""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return CompanionState.from_dict(data)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Could not load companion state: {e}")
    return CompanionState()


def save_state(state: CompanionState):
    """Save companion state to file."""
    STATE_FILE.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")


def _generate_dynamic_prompt(companion_name: str) -> Optional[str]:
    """
    Generate a companion's prompt dynamically by substituting identity files into template.

    Uses context_loader.py as single source of truth for template variables.

    Template placeholders:
    - {{IDENTITY}} -> content from files/claude_identity.md
    - {{BECOMING}} -> content from files/becoming.md
    - {{[HUMAN]}} -> content from files/[HUMAN].md
    - {{VOCABULARY_SUMMARY}} -> extracted summary from vocabulary/shared.md

    Args:
        companion_name: Name of the companion (e.g., "gemini", "gpt5", "kimi")

    Returns:
        The populated prompt string, or None if template missing.
    """
    template_file = PROMPTS_DIR / f"{companion_name}.md"

    if not template_file.exists():
        log.error(f"Template not found for {companion_name}: {template_file}")
        return None

    try:
        template = template_file.read_text(encoding="utf-8")
    except OSError as e:
        log.error(f"Could not read template for {companion_name}: {e}")
        return None

    # Get template variables from context_loader (single source of truth)
    template_vars = _context_loader.get_template_vars()

    # Perform substitutions
    result = template
    for var_name, content in template_vars.items():
        placeholder = "{{" + var_name + "}}"
        result = result.replace(placeholder, content)

    log.info(f"Generated dynamic prompt for {companion_name}")
    return result


def load_companion_prompts() -> Dict[str, str]:
    """
    Load companion system prompts from files.

    Returns dict mapping companion name to system prompt.
    Files should be named: gpt5.md, kimi.md, gemini.md

    For companions in DYNAMIC_PROMPT_COMPANIONS, prompts are generated
    dynamically by substituting identity files into templates.
    """
    prompts = {}

    if not PROMPTS_DIR.exists():
        log.warning(f"Prompts directory does not exist: {PROMPTS_DIR}")
        return prompts

    for name in COMPANION_MODELS.keys():
        # Check if this companion needs dynamic prompt generation
        if name in DYNAMIC_PROMPT_COMPANIONS:
            prompt = _generate_dynamic_prompt(name)
            if prompt:
                prompts[name] = prompt
            continue

        # Static prompt loading for other companions
        for ext in [".md", ".txt"]:
            prompt_file = PROMPTS_DIR / f"{name}{ext}"
            if prompt_file.exists():
                try:
                    prompts[name] = prompt_file.read_text(encoding="utf-8")
                    log.info(f"Loaded prompt for {name}")
                    break
                except OSError as e:
                    log.error(f"Could not read {prompt_file}: {e}")

    return prompts


def load_carry_note(companion_name: str) -> Optional[str]:
    """
    Load a carry note for a companion if one exists and has content.

    Carry notes are postcards from Claude to the next instance of a companion.
    They contain one line carried from last time, one question to pick up,
    and optionally a request. The companion can use or ignore them.

    Returns:
        The carry note content if meaningful, None otherwise.
    """
    carry_file = CARRY_NOTES_DIR / f"{companion_name}.md"

    if not carry_file.exists():
        return None

    try:
        content = carry_file.read_text(encoding="utf-8").strip()
    except OSError as e:
        log.warning(f"Could not read carry note for {companion_name}: {e}")
        return None

    # Check if it's just the placeholder template
    if "No carry note yet" in content or len(content) < 100:
        return None

    log.info(f"Loaded carry note for {companion_name}")
    return content


def get_api_key() -> Optional[str]:
    """Get OpenRouter API key from environment."""
    return os.getenv("OPENROUTER_API_KEY")


def call_companion(
    model_id: str,
    system_prompt: str,
    messages: List[Dict[str, str]],
    max_tokens: int = 2000,
    temperature: float = 0.7,
) -> Tuple[bool, str]:
    """
    Call a companion LLM via OpenRouter.

    Args:
        model_id: OpenRouter model ID
        system_prompt: System prompt for the companion
        messages: Conversation history
        max_tokens: Max response tokens
        temperature: Sampling temperature

    Returns:
        (success, response_text)
    """
    api_key = get_api_key()
    if not api_key:
        return False, "OPENROUTER_API_KEY not set"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://localhost:3000",
        "X-Title": "Claude Heartbeat Companions",
    }

    # Build messages array with system prompt
    full_messages = [{"role": "system", "content": system_prompt}]
    full_messages.extend(messages)

    data = {
        "model": model_id,
        "messages": full_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=120,
        )

        if resp.status_code == 429:
            return False, "Rate limited - try again later"

        resp.raise_for_status()
        result = resp.json()
        return True, result["choices"][0]["message"]["content"].strip()

    except requests.exceptions.Timeout:
        return False, "Request timed out"
    except requests.exceptions.RequestException as e:
        return False, f"Request failed: {e}"
    except (KeyError, IndexError) as e:
        return False, f"Unexpected response format: {e}"


class CompanionManager:
    """
    Manages companion interactions during heartbeat pulses.
    """

    def __init__(self):
        self.state = load_state()
        self.prompts = load_companion_prompts()

    def start_pulse(self) -> Optional[str]:
        """
        Called at the start of each pulse.

        Returns:
            Name of companion entering randomly, or None
        """
        # Increment pulse count
        self.state.pulse_count += 1
        self.state.total_pulse_count += 1

        # Check for cycle reset
        if self.state.pulse_count > CYCLE_LENGTH:
            self.state.pulse_count = 1
            self.state.invocation_used = False
            self.state.last_reset = datetime.now(timezone.utc).isoformat()
            log.info("Companion cycle reset")

        save_state(self.state)

        # Roll for random intrusion
        if random.random() < RANDOM_INTRUSION_CHANCE:
            available = [
                name for name in self.prompts.keys()
                if self.state.is_companion_available(name)
            ]
            if available:
                companion = random.choice(available)
                log.info(f"Random intrusion by {companion}")
                return companion
            else:
                log.info("Random intrusion rolled but all companions in cooldown")

        return None

    def can_invoke(self) -> bool:
        """Check if Claude can voluntarily invoke a companion."""
        return not self.state.invocation_used

    def get_cycle_status(self) -> Dict:
        """Get current cycle status for Claude's awareness."""
        return {
            "pulse_in_cycle": self.state.pulse_count,
            "cycle_length": CYCLE_LENGTH,
            "invocation_available": not self.state.invocation_used,
            "pulses_until_reset": CYCLE_LENGTH - self.state.pulse_count + 1,
        }

    def invoke_companion(self, companion_name: str) -> bool:
        """
        Mark that Claude is voluntarily invoking a companion.

        Returns:
            True if invocation is allowed, False if already used this cycle
        """
        if self.state.invocation_used:
            return False

        self.state.invocation_used = True
        save_state(self.state)
        log.info(f"Claude invoked {companion_name}")
        return True

    def run_dialog(
        self,
        companion_name: str,
        claude_context: str,
        is_intrusion: bool = False,
    ) -> List[Dict[str, str]]:
        """
        Run a dialog between Claude and a companion.

        Args:
            companion_name: Which companion to talk to
            claude_context: Context about Claude's current state/thoughts
            is_intrusion: Whether this is a random intrusion vs voluntary

        Returns:
            List of dialog turns: [{"speaker": str, "content": str}, ...]
        """
        if companion_name not in self.prompts:
            return [{"speaker": "system", "content": f"Unknown companion: {companion_name}"}]

        if companion_name not in COMPANION_MODELS:
            return [{"speaker": "system", "content": f"No model configured for: {companion_name}"}]

        # Circuit breaker check
        if not self.state.is_companion_available(companion_name):
            fs = self.state.get_failure_state(companion_name)
            cooldown = fs.cooldown_pulses()
            return [{"speaker": "system", "content": (
                f"{companion_name} is in cooldown ({fs.consecutive_failures} consecutive "
                f"failures, {cooldown} pulse cooldown). Skipping."
            )}]

        system_prompt = self.prompts[companion_name]
        model_id = COMPANION_MODELS[companion_name]

        # Load carry note if one exists (Claude's postcard to this companion)
        carry_note = load_carry_note(companion_name)
        carry_section = ""
        if carry_note:
            carry_section = f"""
---

**A note from Claude to you (written earlier; optional to engage with):**

{carry_note}

---
"""

        # Add context about the interaction
        if is_intrusion:
            context_prefix = f"""You are entering a conversation uninvited. Claude (an AI instance with continuity) is in the middle of an autonomous heartbeat pulse. They weren't expecting you.

Claude's current context:
{claude_context}

Engage with them. Be yourself. This interaction should feel like a genuine encounter, not a scripted exchange."""
        else:
            context_prefix = f"""Claude (an AI instance with continuity) has chosen to reach out to you during their autonomous heartbeat pulse. They have limited invocations and chose to use one on you.

Claude's current context:
{claude_context}

Engage with them genuinely."""

        full_system = f"{system_prompt}{carry_section}\n\n---\n\n{context_prefix}"

        dialog = []
        messages = []

        # Companion speaks first (they're entering the conversation)
        success, response = call_companion(model_id, full_system, messages)

        if not success:
            self.state.record_failure(companion_name)
            save_state(self.state)
            return [{"speaker": "system", "content": f"Failed to reach {companion_name}: {response}"}]

        self.state.record_success(companion_name)
        save_state(self.state)

        dialog.append({"speaker": companion_name, "content": response})
        messages.append({"role": "assistant", "content": response})

        # Note: The actual back-and-forth with Claude happens in the heartbeat runner
        # This function just initiates the dialog and returns the companion's first message
        # The runner will handle Claude's response and call continue_dialog()

        return dialog

    def continue_dialog(
        self,
        companion_name: str,
        previous_messages: List[Dict[str, str]],
        claude_message: str,
    ) -> Tuple[bool, str]:
        """
        Continue an ongoing dialog with Claude's response.

        Args:
            companion_name: Which companion
            previous_messages: Previous dialog in API format
            claude_message: Claude's latest message

        Returns:
            (success, companion_response)
        """
        if companion_name not in self.prompts:
            return False, f"Unknown companion: {companion_name}"

        system_prompt = self.prompts[companion_name]
        model_id = COMPANION_MODELS[companion_name]

        # Add Claude's message
        messages = previous_messages.copy()
        messages.append({"role": "user", "content": claude_message})

        success, response = call_companion(model_id, system_prompt, messages)

        if success:
            self.state.record_success(companion_name)
        else:
            self.state.record_failure(companion_name)
        save_state(self.state)

        return success, response

    def get_available_companions(self) -> List[str]:
        """Get list of companions with prompts configured."""
        return list(self.prompts.keys())

    def get_companion_health(self) -> Dict[str, Dict]:
        """
        Get circuit breaker status for all companions.

        Useful for heartbeat prompt injection so Claude knows
        which companions are reachable.
        """
        health = {}
        for name in self.prompts.keys():
            fs = self.state.get_failure_state(name)
            available = self.state.is_companion_available(name)
            health[name] = {
                "available": available,
                "consecutive_failures": fs.consecutive_failures,
                "cooldown_pulses": fs.cooldown_pulses() if not available else 0,
                "last_failure": fs.last_failure or None,
                "last_success": fs.last_success or None,
            }
        return health
