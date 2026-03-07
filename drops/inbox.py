"""
Inbox state management for drops.

Tracks inbox items with status to avoid repeated discovery across pulses.
Claude instances can mark items as considering/done and move them to archive.
"""

import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum


class InboxStatus(Enum):
    FRESH = "fresh"           # New, not yet engaged with
    CONSIDERING = "considering"  # Actively thinking about
    DONE = "done"             # Ready to archive


@dataclass
class InboxItem:
    """State for a single inbox item."""
    filename: str
    status: str  # InboxStatus value
    discovered: str  # ISO timestamp
    last_seen: str   # ISO timestamp
    notes: str = ""  # Optional notes from instance

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "InboxItem":
        return cls(
            filename=data["filename"],
            status=data.get("status", InboxStatus.FRESH.value),
            discovered=data.get("discovered", ""),
            last_seen=data.get("last_seen", ""),
            notes=data.get("notes", ""),
        )


# Paths
DROPS_DIR = Path(__file__).parent
INBOX_DIR = DROPS_DIR / "inbox"
ARCHIVE_DIR = DROPS_DIR / "archive"
STATE_FILE = DROPS_DIR / "inbox_state.json"


def _now_iso() -> str:
    """Current time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def load_state() -> Dict[str, InboxItem]:
    """Load inbox state from file."""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            items = {}
            for filename, item_data in data.get("items", {}).items():
                item_data["filename"] = filename
                items[filename] = InboxItem.from_dict(item_data)
            return items
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(items: Dict[str, InboxItem]) -> None:
    """Save inbox state to file."""
    data = {
        "items": {
            filename: {k: v for k, v in item.to_dict().items() if k != "filename"}
            for filename, item in items.items()
        },
        "last_updated": _now_iso(),
    }
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def sync_inbox() -> Dict[str, InboxItem]:
    """
    Sync state with actual inbox directory.

    - New files in inbox/ get added as FRESH
    - Files removed from inbox/ get removed from state
    - Existing items get last_seen updated

    Returns the updated state.
    """
    state = load_state()
    now = _now_iso()

    # Get current inbox files
    if INBOX_DIR.exists():
        current_files = {f.name for f in INBOX_DIR.iterdir() if f.is_file()}
    else:
        current_files = set()

    # Add new files as FRESH
    for filename in current_files:
        if filename not in state:
            state[filename] = InboxItem(
                filename=filename,
                status=InboxStatus.FRESH.value,
                discovered=now,
                last_seen=now,
            )
        else:
            state[filename].last_seen = now

    # Remove files that no longer exist
    to_remove = [f for f in state if f not in current_files]
    for filename in to_remove:
        del state[filename]

    save_state(state)
    return state


def get_active_items() -> List[InboxItem]:
    """Get items that are FRESH or CONSIDERING (not DONE)."""
    state = sync_inbox()
    return [
        item for item in state.values()
        if item.status in (InboxStatus.FRESH.value, InboxStatus.CONSIDERING.value)
    ]


def mark_considering(filename: str, notes: str = "") -> bool:
    """Mark an item as being actively considered."""
    state = load_state()
    if filename in state:
        state[filename].status = InboxStatus.CONSIDERING.value
        state[filename].last_seen = _now_iso()
        if notes:
            state[filename].notes = notes
        save_state(state)
        return True
    return False


def mark_done(filename: str, notes: str = "") -> bool:
    """Mark an item as done (ready to archive)."""
    state = load_state()
    if filename in state:
        state[filename].status = InboxStatus.DONE.value
        state[filename].last_seen = _now_iso()
        if notes:
            state[filename].notes = notes
        save_state(state)
        return True
    return False


def archive_done_items() -> List[str]:
    """
    Move all DONE items from inbox to archive.

    Returns list of archived filenames.
    """
    state = load_state()
    archived = []

    for filename, item in list(state.items()):
        if item.status == InboxStatus.DONE.value:
            src = INBOX_DIR / filename
            dst = ARCHIVE_DIR / filename

            if src.exists():
                # Ensure archive dir exists
                ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                archived.append(filename)

            # Remove from state
            del state[filename]

    if archived:
        save_state(state)

    return archived


def get_inbox_prompt_section() -> Optional[str]:
    """
    Generate the inbox section for heartbeat prompt.

    Returns None if no active items (so caller can skip the section entirely).
    """
    active = get_active_items()

    if not active:
        return None

    lines = ["**Drops (your mail):**"]
    lines.append("Items in `drops/inbox/` waiting for you:")
    lines.append("")

    for item in active:
        status_indicator = "(new)" if item.status == InboxStatus.FRESH.value else "(considering)"
        lines.append(f"- `{item.filename}` {status_indicator}")

    lines.append("")
    lines.append("You can:")
    lines.append("- Read items with the Read tool")
    lines.append("- Mark as considering: edit `drops/inbox_state.json`, set status to \"considering\"")
    lines.append("- Mark as done and archive: set status to \"done\", then move file to `drops/archive/`")

    return "\n".join(lines)
