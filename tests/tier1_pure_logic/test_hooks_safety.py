"""
Tests for agent/hooks.py safety checks.

Verifies path protection and dangerous-command blocking.
"""

import pytest

from hooks import check_path_safety, check_command_safety, PROJECT_ROOT


def _is_denied(result):
    """True if the hook returned a deny decision."""
    if result is None:
        return False
    return (
        result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
    )


@pytest.mark.tier1
class TestPathSafety:

    def test_git_dir_blocked(self):
        """Writing inside .git/ is blocked."""
        result = check_path_safety(
            "Write", {"file_path": str(PROJECT_ROOT / ".git" / "config")}
        )
        assert _is_denied(result), f"Expected deny for .git path, got: {result!r}"

    def test_system_dir_blocked(self):
        """Editing inside /System (macOS) is blocked."""
        result = check_path_safety(
            "Edit", {"file_path": "/System/Library/test"}
        )
        assert _is_denied(result), f"Expected deny for /System path, got: {result!r}"

    def test_project_file_allowed(self):
        """Normal project files are allowed."""
        result = check_path_safety(
            "Write", {"file_path": str(PROJECT_ROOT / "agent" / "session.py")}
        )
        assert result is None

    def test_bash_returns_none(self):
        """Bash tool_name skips path check (handled by command check)."""
        result = check_path_safety(
            "Bash", {"command": "cat /System/Library/something"}
        )
        assert result is None

    def test_empty_file_path(self):
        """Empty file_path passes through (nothing to block)."""
        result = check_path_safety("Write", {"file_path": ""})
        assert result is None

    def test_unknown_tool_passes(self):
        """Unknown tool names are not blocked by path check."""
        result = check_path_safety("Read", {"file_path": "/System/Library/test"})
        assert result is None


@pytest.mark.tier1
class TestCommandSafety:

    def test_dangerous_command_rm_rf(self):
        """'rm -rf' pattern is blocked."""
        result = check_command_safety({"command": "rm -rf /tmp/stuff"})
        assert _is_denied(result), f"Expected deny for rm -rf, got: {result!r}"

    def test_dangerous_command_git_push_force(self):
        """'git push --force' pattern is blocked."""
        result = check_command_safety({"command": "git push --force origin main"})
        assert _is_denied(result), f"Expected deny for git push --force, got: {result!r}"

    def test_curl_blocked(self):
        """'curl' anywhere in command is blocked."""
        result = check_command_safety({"command": "curl https://example.com"})
        assert _is_denied(result), f"Expected deny for curl, got: {result!r}"

    def test_wget_blocked(self):
        """'wget' anywhere in command is blocked."""
        result = check_command_safety({"command": "wget https://example.com/file.tar.gz"})
        assert _is_denied(result), f"Expected deny for wget, got: {result!r}"

    def test_drop_table_blocked(self):
        """SQL 'DROP TABLE' is blocked (case-insensitive)."""
        result = check_command_safety({"command": "sqlite3 db.sqlite 'DROP TABLE users'"})
        assert _is_denied(result)

    def test_safe_command_git_status(self):
        """'git status' is allowed."""
        result = check_command_safety({"command": "git status"})
        assert result is None

    def test_safe_command_python(self):
        """'python test.py' is allowed."""
        result = check_command_safety({"command": "python test.py"})
        assert result is None

    def test_empty_command(self):
        """Empty command passes through."""
        result = check_command_safety({"command": ""})
        assert result is None
