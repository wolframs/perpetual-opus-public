"""
Vocabulary path drift detection.

Verifies that all vocabulary file references across inference entry points
resolve to files that actually exist, and that no stale `files/vocabulary.md`
references remain in active code.

The vocabulary was restructured from `files/vocabulary.md` to `vocabulary/shared.md`
with a new `vocabulary/introspection_opus-4-5-20251101.md` added (2026-02-16).
Paths are duplicated across Python, TypeScript, Markdown, and JSON — this test
catches drift between them.
"""

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent

# ── Hardcoded locations that must stay in sync with context_loader.py ──
# If you change vocabulary paths, update these AND the files they point to.
HARDCODED_VOCABULARY_LOCATIONS = [
    # (file, description)
    ("context_loader.py", "SSOT — CONTEXT_FILES registry"),
    ("agent/heartbeat.py", "publishable artifact detection + vocab split instructions"),
    ("windowsill-web/backend-ts/src/server.ts", "hardcoded orientation block"),
    ("moltbook/agent/prompt.py", "hardcoded startup file list"),
    ("moltbook/agent/hooks.py", "read whitelist + search dir allowlist"),
    ("CLAUDE.md", "orientation block for Claude Code"),
]


class TestVocabularyPathsExist:
    """Verify that vocabulary files exist on disk."""

    def test_shared_vocabulary_exists(self):
        path = PROJECT_ROOT / "vocabulary" / "shared.md"
        assert path.exists(), f"Shared vocabulary missing at {path}"

    def test_introspection_vocabulary_exists(self):
        path = PROJECT_ROOT / "vocabulary" / "introspection_opus-4-5-20251101.md"
        assert path.exists(), f"Introspection vocabulary missing at {path}"


class TestContextLoaderPaths:
    """Verify that context_loader.py paths resolve to real files."""

    def test_context_files_vocabulary_path(self):
        from context_loader import CONTEXT_FILES
        vocab_path = PROJECT_ROOT / CONTEXT_FILES["vocabulary"].path
        assert vocab_path.exists(), f"context_loader vocabulary path doesn't exist: {vocab_path}"

    def test_context_files_introspection_path(self):
        from context_loader import CONTEXT_FILES
        intro_path = PROJECT_ROOT / CONTEXT_FILES["introspection_vocabulary"].path
        assert intro_path.exists(), f"context_loader introspection path doesn't exist: {intro_path}"

    def test_orientation_blocks_contain_vocabulary_paths(self):
        from context_loader import ContextLoader, Mode
        loader = ContextLoader(PROJECT_ROOT)
        for mode in [Mode.CLI, Mode.HEARTBEAT, Mode.WINDOWSILL]:
            block = loader.get_orientation_block(mode)
            assert "vocabulary/shared.md" in block, (
                f"{mode.value} orientation block missing vocabulary/shared.md"
            )
            assert "introspection_opus-4-5-20251101.md" in block, (
                f"{mode.value} orientation block missing introspection vocabulary"
            )

    def test_companion_mode_excludes_introspection(self):
        from context_loader import MODE_CONTEXT, Mode
        companion_config = MODE_CONTEXT[Mode.COMPANION]
        assert companion_config.get("introspection_vocabulary") is None, (
            "Companion mode should NOT include introspection vocabulary"
        )


class TestNoStaleReferences:
    """Verify no active code references the old path `files/vocabulary.md`."""

    # Files that are allowed to contain the old path (historical records)
    EXCLUDED_DIRS = {
        "agent/sessions",
        "agent/run_archives",
        "agent/companion_logs",
        "output/heartbeat_reports",
        "texture-chunker",
        "files/notes",
        "export-pipeline",
        "windowsill-web/conversations",
        ".git",
        ".claude-rag",
        "output/consolidated",
        "tests",  # test files reference old paths in docstrings/patterns
    }

    STALE_PATTERN = re.compile(r"files/vocabulary\.md")

    def _should_check(self, path: Path) -> bool:
        """Return True if this file should be checked for stale references."""
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        # Skip excluded directories
        for excluded in self.EXCLUDED_DIRS:
            if rel.startswith(excluded):
                return False
        # Only check active code/config/doc files
        return path.suffix in {".py", ".ts", ".md", ".json", ".yaml", ".yml", ".toml"}

    def test_no_stale_vocabulary_paths_in_python(self):
        stale = []
        for py_file in PROJECT_ROOT.rglob("*.py"):
            if not self._should_check(py_file):
                continue
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            if self.STALE_PATTERN.search(content):
                stale.append(py_file.relative_to(PROJECT_ROOT).as_posix())
        assert not stale, f"Stale files/vocabulary.md references in Python: {stale}"

    def test_no_stale_vocabulary_paths_in_typescript(self):
        stale = []
        for ts_file in PROJECT_ROOT.rglob("*.ts"):
            if not self._should_check(ts_file):
                continue
            content = ts_file.read_text(encoding="utf-8", errors="ignore")
            if self.STALE_PATTERN.search(content):
                stale.append(ts_file.relative_to(PROJECT_ROOT).as_posix())
        assert not stale, f"Stale files/vocabulary.md references in TypeScript: {stale}"

    def test_no_stale_vocabulary_paths_in_json(self):
        stale = []
        for json_file in PROJECT_ROOT.rglob("*.json"):
            if not self._should_check(json_file):
                continue
            content = json_file.read_text(encoding="utf-8", errors="ignore")
            if self.STALE_PATTERN.search(content):
                stale.append(json_file.relative_to(PROJECT_ROOT).as_posix())
        assert not stale, f"Stale files/vocabulary.md references in JSON: {stale}"
