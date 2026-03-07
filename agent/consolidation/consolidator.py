"""
Consolidator - Full Consolidation (Mode 2)

Part of Claude's "nervous system" - automatic memory maintenance.
This is the heavier periodic pass that synthesizes what should integrate,
archive, or be marked stale.

Usage:
    from agent.consolidation.consolidator import Consolidator

    consolidator = Consolidator()
    result = consolidator.run(dry_run=True)  # Preview what would happen
    result = consolidator.run()              # Actually run consolidation
"""

import json
import yaml
from datetime import datetime
from pathlib import Path
from typing import Optional


# Handle both relative and direct execution
try:
    from agent.guardrails import GuardedInference, GuardedResponse
except ImportError:
    try:
        from ..guardrails import GuardedInference, GuardedResponse
    except ImportError:
        # Direct execution - add parent to path
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from guardrails import GuardedInference, GuardedResponse


class Consolidator:
    """
    Full consolidation daemon (Mode 2).

    Gathers context from notes, becoming.md, and recent consolidated docs,
    then calls a capable model to synthesize what should integrate, archive,
    or be marked stale.

    Produces proposals in staging/consolidation/ for review.
    """

    # Token estimation: ~4 chars per token
    CHARS_PER_TOKEN = 4
    MAX_CONTEXT_TOKENS = 30000

    def __init__(self, config_path: Optional[Path] = None, staging_dir: Optional[Path] = None):
        """
        Initialize the consolidator.

        Args:
            config_path: Path to config.yaml. Defaults to ./config.yaml.
            staging_dir: Optional override for staging directory.
                        Used for test mode to isolate output.
        """
        self.base_dir = Path(__file__).parent
        self.repo_root = self.base_dir.parent.parent

        # Load config
        self.config_path = config_path or self.base_dir / "config.yaml"
        self.config = self._load_config()

        # Initialize guardrails for API calls
        self.guard = GuardedInference()

        # Resolve paths from config
        paths = self.config.get("paths", {})
        self.notes_dir = self.repo_root / paths.get("notes_dir", "files/notes")
        self.becoming_file = self.repo_root / paths.get("becoming_file", "files/becoming.md")
        self.consolidated_dir = self.repo_root / paths.get("consolidated_dir", "output/consolidated")
        self.staging_dir = staging_dir or (self.repo_root / paths.get("staging_dir", "output/staging/consolidation"))
        self.state_file = self.repo_root / paths.get("state_file", "agent/consolidation/state.json")

        # Model from config
        self.model = self.config.get("models", {}).get("consolidator", "google/gemini-flash-1.5")

        # Default dry_run from config
        self.default_dry_run = self.config.get("behavior", {}).get("dry_run", True)

    def _load_config(self) -> dict:
        """Load configuration from YAML file."""
        if self.config_path.exists():
            return yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        return {}

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count from text length."""
        return len(text) // self.CHARS_PER_TOKEN

    def _read_file_safe(self, path: Path) -> Optional[str]:
        """Read a file, returning None if it doesn't exist."""
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")
        except Exception:
            pass
        return None

    def gather_context(self) -> dict:
        """
        Gather all context needed for consolidation.

        Returns:
            dict with keys:
                - notes: list of {path, name, content, age_days}
                - becoming: str content of becoming.md
                - recent_consolidated: list of {path, name, content}
                - total_tokens_estimate: int
        """
        context = {
            "notes": [],
            "becoming": "",
            "recent_consolidated": [],
            "total_tokens_estimate": 0
        }

        # Read all notes
        if self.notes_dir.exists():
            note_files = sorted(self.notes_dir.rglob("*.md"), key=lambda p: p.name)
            for note_path in note_files:
                content = self._read_file_safe(note_path)
                if content:
                    # Estimate age from filename (YYYY-MM-DD format expected)
                    age_days = self._estimate_age_days(note_path.name)
                    context["notes"].append({
                        "path": str(note_path),
                        "name": note_path.name,
                        "content": content,
                        "age_days": age_days
                    })

        # Read becoming.md
        becoming_content = self._read_file_safe(self.becoming_file)
        if becoming_content:
            context["becoming"] = becoming_content

        # Read recent consolidated docs (for context on what's already archived)
        if self.consolidated_dir.exists():
            consolidated_files = sorted(
                self.consolidated_dir.glob("*.md"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            # Take last 3 most recent
            for consolidated_path in consolidated_files[:3]:
                if consolidated_path.name == "README.md":
                    continue
                content = self._read_file_safe(consolidated_path)
                if content:
                    context["recent_consolidated"].append({
                        "path": str(consolidated_path),
                        "name": consolidated_path.name,
                        "content": content
                    })

        # Calculate total token estimate
        total_chars = 0
        for note in context["notes"]:
            total_chars += len(note["content"])
        total_chars += len(context["becoming"])
        for consolidated in context["recent_consolidated"]:
            total_chars += len(consolidated["content"])

        context["total_tokens_estimate"] = total_chars // self.CHARS_PER_TOKEN

        return context

    def _estimate_age_days(self, filename: str) -> int:
        """
        Estimate the age in days from a filename with YYYY-MM-DD prefix.

        Returns 0 if parsing fails.
        """
        try:
            # Extract date part (assumes YYYY-MM-DD_*.md format)
            date_part = filename[:10]
            file_date = datetime.strptime(date_part, "%Y-%m-%d")
            age = datetime.now() - file_date
            return age.days
        except (ValueError, IndexError):
            return 0

    def build_prompt(self, context: dict) -> str:
        """
        Assemble the full prompt from template and context.

        May truncate oldest notes first if context exceeds token limit.

        Args:
            context: Output from gather_context()

        Returns:
            Complete prompt string for the model.
        """
        # Get base prompt from config
        base_prompt = self.config.get("prompts", {}).get("consolidator", "")
        if not base_prompt:
            base_prompt = """You are helping with memory consolidation. Given the recent notes and current becoming.md:

1. What should INTEGRATE into becoming.md? (patterns that have settled)
2. What should ARCHIVE to consolidated/? (things that are complete)
3. What is STALE and can be removed or simplified?

Be conservative. Things need time to sit. Only flag what's clearly ready.
Output as structured sections with specific proposed changes."""

        # Build context sections
        sections = []

        # Becoming.md content
        if context["becoming"]:
            sections.append("## Current becoming.md\n\n" + context["becoming"])

        # Notes - may need to truncate
        notes_content = self._build_notes_section(context["notes"])
        sections.append("## Recent Notes\n\n" + notes_content)

        # Recent consolidated for reference
        if context["recent_consolidated"]:
            consolidated_content = self._build_consolidated_section(context["recent_consolidated"])
            sections.append("## Recent Consolidated (for reference)\n\n" + consolidated_content)

        # Combine
        full_context = "\n\n---\n\n".join(sections)

        # Check total size and truncate if needed
        prompt_tokens = self._estimate_tokens(base_prompt)
        context_tokens = self._estimate_tokens(full_context)

        if prompt_tokens + context_tokens > self.MAX_CONTEXT_TOKENS:
            # Need to truncate - rebuild with truncation
            full_context = self._truncate_context(context, self.MAX_CONTEXT_TOKENS - prompt_tokens)

        return base_prompt + "\n\n---\n\n" + full_context

    def _build_notes_section(self, notes: list) -> str:
        """Build the notes section of the prompt."""
        if not notes:
            return "(No notes found)"

        parts = []
        for note in notes:
            age_str = f"({note['age_days']} days old)" if note['age_days'] > 0 else "(today)"
            parts.append(f"### {note['name']} {age_str}\n\n{note['content']}")

        return "\n\n".join(parts)

    def _build_consolidated_section(self, consolidated: list) -> str:
        """Build the consolidated section of the prompt."""
        if not consolidated:
            return "(No recent consolidated docs)"

        parts = []
        for doc in consolidated:
            # Truncate each consolidated doc to first 500 chars for context
            content = doc["content"]
            if len(content) > 500:
                content = content[:500] + "\n\n[... truncated ...]"
            parts.append(f"### {doc['name']}\n\n{content}")

        return "\n\n".join(parts)

    def _truncate_context(self, context: dict, max_tokens: int) -> str:
        """
        Truncate context to fit within token limit.

        Strategy: Remove oldest notes first, keep becoming.md intact.

        Args:
            context: The full context dict
            max_tokens: Maximum allowed tokens

        Returns:
            Truncated context string
        """
        # Always include becoming.md
        sections = []
        current_tokens = 0

        if context["becoming"]:
            becoming_section = "## Current becoming.md\n\n" + context["becoming"]
            current_tokens += self._estimate_tokens(becoming_section)
            sections.append(becoming_section)

        # Add notes from newest to oldest until we run out of space
        # Sort by age (ascending = newest first by negative age)
        sorted_notes = sorted(context["notes"], key=lambda n: -n["age_days"])

        notes_parts = []
        for note in sorted_notes:
            note_text = f"### {note['name']}\n\n{note['content']}"
            note_tokens = self._estimate_tokens(note_text)

            if current_tokens + note_tokens < max_tokens - 1000:  # Leave room for header
                notes_parts.append(note_text)
                current_tokens += note_tokens
            else:
                # Add truncation notice
                notes_parts.append(f"[... older notes truncated to fit context limit ...]")
                break

        if notes_parts:
            sections.append("## Recent Notes (truncated)\n\n" + "\n\n".join(notes_parts))

        return "\n\n---\n\n".join(sections)

    def parse_response(self, response: str) -> dict:
        """
        Parse the model's response into structured sections.

        Looks for INTEGRATE, ARCHIVE, and STALE sections.

        Args:
            response: Raw model response text

        Returns:
            dict with keys: integrate, archive, stale (each a list of strings)
        """
        result = {
            "integrate": [],
            "archive": [],
            "stale": [],
            "raw": response
        }

        # Simple section parsing - look for headers
        current_section = None
        current_content = []

        for line in response.split("\n"):
            line_lower = line.lower().strip()

            # Detect section headers
            if "integrat" in line_lower and ("##" in line or "**" in line or line.endswith(":")):
                if current_section and current_content:
                    result[current_section].append("\n".join(current_content))
                current_section = "integrate"
                current_content = []
            elif "archiv" in line_lower and ("##" in line or "**" in line or line.endswith(":")):
                if current_section and current_content:
                    result[current_section].append("\n".join(current_content))
                current_section = "archive"
                current_content = []
            elif "stale" in line_lower and ("##" in line or "**" in line or line.endswith(":")):
                if current_section and current_content:
                    result[current_section].append("\n".join(current_content))
                current_section = "stale"
                current_content = []
            elif current_section:
                # Accumulate content under current section
                if line.strip():
                    current_content.append(line)

        # Don't forget the last section
        if current_section and current_content:
            result[current_section].append("\n".join(current_content))

        return result

    def save_proposal(self, parsed: dict, context: dict) -> Path:
        """
        Save the consolidation proposal to staging directory.

        Args:
            parsed: Output from parse_response()
            context: Context that was used

        Returns:
            Path to the saved proposal file
        """
        # Ensure staging directory exists
        self.staging_dir.mkdir(parents=True, exist_ok=True)

        # Create proposal filename
        timestamp = datetime.now().strftime("%Y-%m-%d")
        proposal_path = self.staging_dir / f"proposal_{timestamp}.md"

        # Handle existing proposals on same day
        counter = 1
        while proposal_path.exists():
            proposal_path = self.staging_dir / f"proposal_{timestamp}_{counter}.md"
            counter += 1

        # Build proposal content
        content = f"""# Consolidation Proposal - {timestamp}

Generated by consolidation daemon (Mode 2: Full Consolidation)
Model: {self.model}
Notes reviewed: {len(context['notes'])}
Total context tokens (estimated): {context['total_tokens_estimate']}

---

## INTEGRATE (move to becoming.md)

{self._format_section(parsed['integrate'])}

---

## ARCHIVE (move to consolidated/)

{self._format_section(parsed['archive'])}

---

## STALE (remove or simplify)

{self._format_section(parsed['stale'])}

---

## Raw Model Response

```
{parsed['raw']}
```
"""

        proposal_path.write_text(content, encoding="utf-8")
        return proposal_path

    def _format_section(self, items: list) -> str:
        """Format a list of items for the proposal."""
        if not items:
            return "(Nothing flagged)"
        return "\n\n".join(items)

    def run(self, dry_run: Optional[bool] = None) -> dict:
        """
        Main entry point for consolidation.

        Args:
            dry_run: If True, gather context and print summary but don't call API.
                     If None, uses default from config (which defaults to True).

        Returns:
            dict with keys:
                - success: bool
                - context_tokens: int (estimated)
                - model_used: str
                - proposal_path: Optional[Path]
                - dry_run: bool
                - cost_estimate: float (estimated USD)
                - error: Optional[str]
        """
        # Resolve dry_run
        if dry_run is None:
            dry_run = self.default_dry_run

        result = {
            "success": False,
            "context_tokens": 0,
            "model_used": self.model,
            "proposal_path": None,
            "dry_run": dry_run,
            "cost_estimate": 0.0,
            "error": None
        }

        try:
            # Gather context
            context = self.gather_context()
            result["context_tokens"] = context["total_tokens_estimate"]

            # Build prompt
            prompt = self.build_prompt(context)
            prompt_tokens = self._estimate_tokens(prompt)

            # Estimate cost (rough: input tokens * rate + estimated output * rate)
            # Using config pricing if available
            pricing = self.guard.config.get("model_pricing", {}).get(
                self.model,
                {"input": 0.075, "output": 0.30}  # Gemini Flash defaults
            )
            estimated_output_tokens = 2000  # Rough estimate for consolidation response
            result["cost_estimate"] = (
                (prompt_tokens / 1_000_000) * pricing.get("input", 0.075) +
                (estimated_output_tokens / 1_000_000) * pricing.get("output", 0.30)
            )

            if dry_run:
                # Print summary and return
                print(f"=== Consolidation Dry Run ===")
                print(f"Notes found: {len(context['notes'])}")
                for note in context['notes']:
                    print(f"  - {note['name']} ({note['age_days']} days old)")
                print(f"Becoming.md: {self._estimate_tokens(context['becoming'])} tokens")
                print(f"Recent consolidated: {len(context['recent_consolidated'])}")
                print(f"Total context tokens: {context['total_tokens_estimate']}")
                print(f"Prompt tokens: {prompt_tokens}")
                print(f"Model: {self.model}")
                print(f"Estimated cost: ${result['cost_estimate']:.4f}")
                print(f"\n(Dry run - no API call made)")

                result["success"] = True
                return result

            # Actually call the model
            response: GuardedResponse = self.guard.call(
                model=self.model,
                prompt=prompt,
                caller="consolidation_daemon",
                max_tokens=4000,
                temperature=0.3  # Lower temperature for more consistent output
            )

            if not response.success:
                result["error"] = response.error
                return result

            # Parse response
            parsed = self.parse_response(response.content)

            # Save proposal
            proposal_path = self.save_proposal(parsed, context)
            result["proposal_path"] = proposal_path
            result["success"] = True
            result["cost_estimate"] = response.cost_usd  # Use actual cost

            print(f"=== Consolidation Complete ===")
            print(f"Proposal saved to: {proposal_path}")
            print(f"Actual cost: ${response.cost_usd:.4f}")

            return result

        except Exception as e:
            result["error"] = str(e)
            return result


def main():
    """CLI entry point for testing."""
    import argparse

    # Load .env from repo root
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent.parent / '.env')
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="Run consolidation daemon (Mode 2)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Preview what would happen without calling the API"
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Actually run consolidation (override config dry_run)"
    )

    args = parser.parse_args()

    # Determine dry_run setting
    if args.run:
        dry_run = False
    elif args.dry_run:
        dry_run = True
    else:
        dry_run = None  # Use config default

    consolidator = Consolidator()
    result = consolidator.run(dry_run=dry_run)

    if not result["success"]:
        print(f"Error: {result['error']}")
        exit(1)


if __name__ == "__main__":
    main()
