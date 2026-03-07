"""
Session management for the Claude Agent.

Handles conversation persistence, state tracking, and session lifecycle.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
import hashlib

# Handle both package import (python -m agent...) and direct import (from runner.py)
try:
    from .config import PROJECT_ROOT, EXPORTS_DIR, SESSION_STATE_FILE
except ImportError:
    from config import PROJECT_ROOT, EXPORTS_DIR, SESSION_STATE_FILE


@dataclass
class SessionMessage:
    """A single message in the session."""
    role: str  # 'human', 'assistant', 'system'
    content: str
    timestamp: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Session:
    """A conversation session."""
    session_id: str
    started_at: str
    messages: List[SessionMessage] = field(default_factory=list)
    status: str = "active"  # active, paused, completed
    summary: Optional[str] = None

    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None):
        """Add a message to the session."""
        self.messages.append(SessionMessage(
            role=role,
            content=content,
            timestamp=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {}
        ))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "status": self.status,
            "summary": self.summary,
            "messages": [asdict(m) for m in self.messages]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        """Create from dictionary."""
        messages = [SessionMessage(**m) for m in data.get("messages", [])]
        return cls(
            session_id=data["session_id"],
            started_at=data["started_at"],
            status=data.get("status", "active"),
            summary=data.get("summary"),
            messages=messages
        )


class SessionManager:
    """Manages session lifecycle and persistence."""

    def __init__(self, exports_dir: Optional[Path] = None):
        self.exports_dir = exports_dir or EXPORTS_DIR
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.current_session: Optional[Session] = None

    def start_session(self, initial_prompt: Optional[str] = None) -> Session:
        """Start a new session."""
        now = datetime.now(timezone.utc)
        session_id = self._generate_session_id(now)

        self.current_session = Session(
            session_id=session_id,
            started_at=now.isoformat()
        )

        if initial_prompt:
            self.current_session.add_message("human", initial_prompt)

        return self.current_session

    def _generate_session_id(self, timestamp: datetime) -> str:
        """Generate a unique session ID."""
        # Format: YYYY-MM-DD_HHMMSS_hash
        time_part = timestamp.strftime("%Y-%m-%d_%H%M%S")
        hash_part = hashlib.sha256(str(timestamp.timestamp()).encode()).hexdigest()[:8]
        return f"{time_part}_{hash_part}"

    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None):
        """Add a message to the current session."""
        if self.current_session:
            self.current_session.add_message(role, content, metadata)

    def save_session(self):
        """Save the current session to disk."""
        if not self.current_session:
            return

        session_dir = self.exports_dir / self.current_session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Save as JSON (can be converted to JSONL for RAG later)
        session_file = session_dir / "session.json"
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(self.current_session.to_dict(), f, indent=2, ensure_ascii=False)

    def end_session(self, status: str = "completed", summary: Optional[str] = None):
        """End the current session."""
        if self.current_session:
            self.current_session.status = status
            self.current_session.summary = summary
            self.save_session()
            self.current_session = None

    def load_session(self, session_id: str) -> Optional[Session]:
        """Load a session from disk."""
        session_file = self.exports_dir / session_id / "session.json"
        if session_file.exists():
            with open(session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return Session.from_dict(data)
        return None

    def list_sessions(self) -> List[str]:
        """List all saved session IDs."""
        if not self.exports_dir.exists():
            return []
        return [d.name for d in self.exports_dir.iterdir() if d.is_dir()]


def update_runner_state(status: str, current_task: Optional[str] = None, notes: Optional[str] = None):
    """
    Update the runner's state file (NOT session_state.md).

    session_state.md is managed by Claude instances for breadcrumb recovery.
    This file tracks the runner/heartbeat status separately.
    """
    runner_state_file = PROJECT_ROOT / "agent" / "runner_state.md"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    content = f"""# Runner State

*Last updated: {now}*

## Status: {status}

"""
    if current_task:
        content += f"""### Current Task

{current_task}

"""

    if notes:
        content += f"""### Notes

{notes}

"""

    content += """---

*This file is automatically updated by the agent runner.*
"""

    runner_state_file.write_text(content, encoding="utf-8")
