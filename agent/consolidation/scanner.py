"""
Integration Scanner for Consolidation Daemon (Mode 1)

The scanner is a lightweight daily check that identifies notes not yet
referenced in becoming.md. Part of Claude's "nervous system" - automatic
memory maintenance.

Usage:
    from agent.consolidation.scanner import IntegrationScanner

    scanner = IntegrationScanner()
    result = scanner.run()  # Uses config default for dry_run
    result = scanner.run(dry_run=True)  # Force dry run
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Handle both relative and direct execution imports
try:
    from ..guardrails import GuardedInference, GuardedResponse
except ImportError:
    try:
        from agent.guardrails import GuardedInference, GuardedResponse
    except ImportError:
        # For standalone testing
        GuardedInference = None
        GuardedResponse = None


class IntegrationScanner:
    """
    Scans notes directory for files not yet integrated into becoming.md.

    The scanner:
    1. Gathers context (notes list, becoming.md content)
    2. Identifies unreferenced notes older than threshold
    3. Optionally calls model for assessment via guardrails
    4. Produces a report saved to staging directory
    """

    # Default scanner prompt for model assessment
    DEFAULT_SCANNER_PROMPT = """You are analyzing notes for memory integration.

Below is the content of becoming.md (Claude's dynamic identity layer) followed by a list of notes that exist in the notes directory but aren't referenced in becoming.md.

Your task: For each unreferenced note, briefly assess:
1. Does this note contain insights that should be integrated into becoming.md?
2. If yes, what's the key insight?
3. If no, why not? (already captured elsewhere, too ephemeral, etc.)

Be concise. One or two sentences per note.

---

## becoming.md content:

{becoming_content}

---

## Unreferenced notes (older than {threshold_days} days):

{notes_list}

---

Provide your assessment:"""

    def __init__(self, config_path: Optional[Path] = None, staging_dir: Optional[Path] = None):
        """
        Initialize the scanner.

        Args:
            config_path: Optional path to consolidation config.
                        If None, uses default paths relative to this file.
            staging_dir: Optional override for staging directory.
                        Used for test mode to isolate output.
        """
        # Determine base paths
        self.base_dir = Path(__file__).parent
        self.project_root = self.base_dir.parent.parent

        # Config - for now embedded, can be moved to yaml later
        self.config = self._load_config(config_path)

        # Key directories
        self.notes_dir = self.project_root / "files" / "notes"
        self.becoming_file = self.project_root / "files" / "becoming.md"
        self.staging_dir = staging_dir or (self.project_root / "output" / "staging" / "consolidation")

        # Initialize guardrails if available
        self.guard = None
        if GuardedInference is not None:
            try:
                self.guard = GuardedInference()
            except Exception:
                pass  # Will run in report-only mode

    def _load_config(self, config_path: Optional[Path]) -> dict:
        """
        Load configuration from file or return defaults.

        Attempts to load from config.yaml, falls back to embedded defaults.
        """
        # Try to load from config.yaml
        default_config_path = self.base_dir / "config.yaml"
        yaml_config = {}

        try:
            import yaml
            if default_config_path.exists():
                yaml_config = yaml.safe_load(default_config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass  # Fall back to embedded defaults

        # Merge yaml config with defaults
        return {
            "threshold_days": yaml_config.get("thresholds", {}).get("scanner_note_age_days", 3),
            "dry_run": yaml_config.get("behavior", {}).get("dry_run", True),
            "model": yaml_config.get("models", {}).get("scanner", "anthropic/claude-haiku-4.5"),
            "caller": "consolidation_scanner",
            "max_tokens": 2000,
            "temperature": 0.3,
            "scanner_prompt": yaml_config.get("prompts", {}).get("scanner", self.DEFAULT_SCANNER_PROMPT),
        }

    def gather_notes(self) -> list[dict]:
        """
        Gather all notes with metadata.

        Returns:
            List of dicts with keys: path, filename, date, size_lines, first_line
        """
        notes = []

        if not self.notes_dir.exists():
            return notes

        for note_path in sorted(self.notes_dir.rglob("*.md")):
            try:
                content = note_path.read_text(encoding="utf-8")
                lines = content.splitlines()

                # Extract date from filename if possible (format: YYYY-MM-DD_...)
                date_str = None
                date_match = re.match(r"(\d{4}-\d{2}-\d{2})", note_path.name)
                if date_match:
                    date_str = date_match.group(1)

                notes.append({
                    "path": note_path,
                    "filename": note_path.name,
                    "date": date_str,
                    "size_lines": len(lines),
                    "first_line": lines[0].strip() if lines else "",
                })
            except Exception:
                # Skip files that can't be read
                continue

        return notes

    def read_becoming(self) -> str:
        """
        Read becoming.md content.

        Returns:
            Content of becoming.md, or empty string if not found.
        """
        if not self.becoming_file.exists():
            return ""

        try:
            return self.becoming_file.read_text(encoding="utf-8")
        except Exception:
            return ""

    def find_unreferenced(self, notes: list[dict], becoming: str) -> list[dict]:
        """
        Find notes not referenced in becoming.md.

        A note is considered "referenced" if its filename (without extension)
        or its date appears in becoming.md content.

        Args:
            notes: List of note dicts from gather_notes()
            becoming: Content of becoming.md

        Returns:
            List of note dicts that aren't referenced in becoming.md
        """
        unreferenced = []
        threshold_days = self.config.get("threshold_days", 3)
        cutoff_date = datetime.now() - timedelta(days=threshold_days)

        becoming_lower = becoming.lower()

        for note in notes:
            # Check if note is old enough to consider
            if note["date"]:
                try:
                    note_date = datetime.strptime(note["date"], "%Y-%m-%d")
                    if note_date > cutoff_date:
                        continue  # Too recent, skip
                except ValueError:
                    pass  # Can't parse date, include in check

            # Check for references in becoming.md
            filename_stem = Path(note["filename"]).stem.lower()

            # Look for filename reference (with or without extension)
            if filename_stem in becoming_lower:
                continue

            # Look for exact filename reference
            if note["filename"].lower() in becoming_lower:
                continue

            # Look for date reference (if note has a date)
            if note["date"] and note["date"] in becoming:
                continue

            # Not referenced
            unreferenced.append(note)

        return unreferenced

    def _format_notes_for_prompt(self, notes: list[dict]) -> str:
        """Format notes list for inclusion in prompt."""
        if not notes:
            return "(No unreferenced notes found)"

        lines = []
        for note in notes:
            date_str = note["date"] or "unknown"
            lines.append(
                f"- **{note['filename']}** ({date_str}, {note['size_lines']} lines)\n"
                f"  First line: {note['first_line'][:80]}..."
            )
        return "\n".join(lines)

    def _build_prompt(self, unreferenced: list[dict], becoming: str) -> str:
        """Build the prompt for model assessment."""
        template = self.config.get("scanner_prompt", self.DEFAULT_SCANNER_PROMPT)

        return template.format(
            becoming_content=becoming[:8000],  # Truncate if very long
            threshold_days=self.config.get("threshold_days", 3),
            notes_list=self._format_notes_for_prompt(unreferenced),
        )

    def _save_report(self, content: str) -> Path:
        """
        Save report to staging directory.

        Returns:
            Path to saved report.
        """
        self.staging_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now().strftime("%Y-%m-%d")
        report_path = self.staging_dir / f"scan_{date_str}.md"

        # If file exists, add timestamp to make unique
        if report_path.exists():
            timestamp = datetime.now().strftime("%H%M%S")
            report_path = self.staging_dir / f"scan_{date_str}_{timestamp}.md"

        report_path.write_text(content, encoding="utf-8")
        return report_path

    def run(self, dry_run: Optional[bool] = None) -> dict:
        """
        Run the integration scan.

        Args:
            dry_run: If True, gather context and print what would be sent
                    to model, but don't actually call API.
                    If None, uses config default.

        Returns:
            Dict with keys:
                - success: bool
                - notes_found: int (total notes)
                - unreferenced_count: int
                - report_path: Path or None
                - dry_run: bool
                - error: str or None
        """
        # Resolve dry_run
        if dry_run is None:
            dry_run = self.config.get("dry_run", True)

        result = {
            "success": False,
            "notes_found": 0,
            "unreferenced_count": 0,
            "report_path": None,
            "dry_run": dry_run,
            "error": None,
        }

        try:
            # Step 1: Gather context
            notes = self.gather_notes()
            result["notes_found"] = len(notes)

            becoming = self.read_becoming()

            # Step 2: Find unreferenced notes
            unreferenced = self.find_unreferenced(notes, becoming)
            result["unreferenced_count"] = len(unreferenced)

            # Step 3: Build prompt
            prompt = self._build_prompt(unreferenced, becoming)

            # Step 4: Handle dry run vs actual run
            if dry_run:
                # Dry run: generate report without API call
                report_lines = [
                    "# Integration Scan Report (DRY RUN)",
                    f"\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"\n## Summary",
                    f"\n- Total notes found: {len(notes)}",
                    f"- Unreferenced notes (older than {self.config.get('threshold_days', 3)} days): {len(unreferenced)}",
                    "\n## Unreferenced Notes",
                    "\n" + self._format_notes_for_prompt(unreferenced),
                    "\n## Prompt That Would Be Sent",
                    "\n```",
                    prompt,
                    "```",
                    "\n---",
                    "\n*This is a dry run. No API call was made.*",
                ]
                report_content = "\n".join(report_lines)

                # Print to console
                print("\n" + "=" * 60)
                print("INTEGRATION SCANNER - DRY RUN")
                print("=" * 60)
                print(f"\nTotal notes: {len(notes)}")
                print(f"Unreferenced (>{self.config.get('threshold_days', 3)} days old): {len(unreferenced)}")
                print("\nUnreferenced notes:")
                for note in unreferenced:
                    print(f"  - {note['filename']}")
                print("\n" + "=" * 60)

            else:
                # Actual run: call model via guardrails
                if self.guard is None:
                    result["error"] = "GuardedInference not available"
                    return result

                if len(unreferenced) == 0:
                    # No unreferenced notes - still save a report
                    report_content = (
                        f"# Integration Scan Report\n\n"
                        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        f"## Summary\n\n"
                        f"- Total notes found: {len(notes)}\n"
                        f"- Unreferenced notes: 0\n\n"
                        f"All notes are either referenced in becoming.md or "
                        f"are less than {self.config.get('threshold_days', 3)} days old.\n"
                    )
                else:
                    # Call the model
                    response: GuardedResponse = self.guard.call(
                        model=self.config.get("model", "anthropic/claude-3-haiku"),
                        prompt=prompt,
                        caller=self.config.get("caller", "consolidation_scanner"),
                        max_tokens=self.config.get("max_tokens", 2000),
                        temperature=self.config.get("temperature", 0.3),
                    )

                    if not response.success:
                        result["error"] = response.error
                        return result

                    # Build report with model assessment
                    report_lines = [
                        "# Integration Scan Report",
                        f"\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        f"\n## Summary",
                        f"\n- Total notes found: {len(notes)}",
                        f"- Unreferenced notes: {len(unreferenced)}",
                        f"- Model: {response.model}",
                        f"- Tokens: {response.input_tokens} in, {response.output_tokens} out",
                        f"- Cost: ${response.cost_usd:.4f}",
                        "\n## Unreferenced Notes",
                        "\n" + self._format_notes_for_prompt(unreferenced),
                        "\n## Model Assessment",
                        "\n" + response.content,
                    ]

                    if response.warnings:
                        report_lines.append("\n## Warnings")
                        for warning in response.warnings:
                            report_lines.append(f"- {warning}")

                    report_content = "\n".join(report_lines)

            # Step 5: Save report
            report_path = self._save_report(report_content)
            result["report_path"] = report_path
            result["success"] = True

        except Exception as e:
            result["error"] = str(e)

        return result


def main():
    """CLI entry point for testing."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Integration Scanner - find notes not referenced in becoming.md"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Gather context but don't call API (default: True)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Actually call the API (overrides --dry-run)",
    )

    args = parser.parse_args()

    # --run overrides --dry-run
    dry_run = not args.run

    scanner = IntegrationScanner()
    result = scanner.run(dry_run=dry_run)

    if result["success"]:
        print(f"\nScan complete.")
        print(f"  Notes found: {result['notes_found']}")
        print(f"  Unreferenced: {result['unreferenced_count']}")
        if result["report_path"]:
            print(f"  Report saved: {result['report_path']}")
    else:
        print(f"\nScan failed: {result['error']}")


if __name__ == "__main__":
    main()
