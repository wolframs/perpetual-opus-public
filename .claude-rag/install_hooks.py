#!/usr/bin/env python3
"""
Git Hook Installer for Claude Code RAG
Discovers all git repos in indexed directories and installs hooks
to trigger re-indexing on branch switch, pull, and merge.
"""

import os
import sys
import json
import stat
from pathlib import Path

# Load configuration
CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)

DIRECTORIES = CONFIG["indexing"]["directories"]
REINDEX_SCRIPT = Path(__file__).parent / "reindex_repo.py"
MAX_DEPTH = 4  # Max depth to search for .git directories

# Find the venv python (same repo, .venv/bin/python3)
_REPO_ROOT = Path(__file__).parent.parent
_VENV_PYTHON = _REPO_ROOT / ".venv" / "bin" / "python3"
PYTHON_CMD = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else "python3"

# Marker for idempotent installs
HOOK_MARKER = "# --- Claude RAG hook (do not remove this marker) ---"
HOOK_END_MARKER = "# --- End Claude RAG hook ---"

# post-checkout hook: $3=1 means branch switch (not file checkout)
POST_CHECKOUT_SNIPPET = f'''
{HOOK_MARKER}
if [ "$3" = "1" ]; then
    REPO_PATH=$(git rev-parse --show-toplevel)
    "{PYTHON_CMD}" "{REINDEX_SCRIPT}" "$REPO_PATH" &
fi
{HOOK_END_MARKER}
'''

POST_CHECKOUT_TEMPLATE = f'''#!/bin/sh
{HOOK_MARKER}
if [ "$3" = "1" ]; then
    REPO_PATH=$(git rev-parse --show-toplevel)
    "{PYTHON_CMD}" "{REINDEX_SCRIPT}" "$REPO_PATH" &
fi
{HOOK_END_MARKER}
'''

# post-merge hook: always triggers (runs after git pull/merge)
POST_MERGE_SNIPPET = f'''
{HOOK_MARKER}
REPO_PATH=$(git rev-parse --show-toplevel)
"{PYTHON_CMD}" "{REINDEX_SCRIPT}" "$REPO_PATH" &
{HOOK_END_MARKER}
'''

POST_MERGE_TEMPLATE = f'''#!/bin/sh
{HOOK_MARKER}
REPO_PATH=$(git rev-parse --show-toplevel)
"{PYTHON_CMD}" "{REINDEX_SCRIPT}" "$REPO_PATH" &
{HOOK_END_MARKER}
'''


def find_git_repos(directories: list[str], max_depth: int = MAX_DEPTH) -> list[Path]:
    """Find all git repositories in the given directories."""
    repos = []

    for directory in directories:
        dir_path = Path(directory)
        if not dir_path.exists():
            print(f"  Warning: Directory not found: {directory}")
            continue

        # Walk directory tree up to max_depth
        for root, dirs, files in os.walk(dir_path):
            root_path = Path(root)
            depth = len(root_path.relative_to(dir_path).parts)

            if depth > max_depth:
                dirs.clear()  # Don't recurse deeper
                continue

            if ".git" in dirs:
                repos.append(root_path)
                dirs.remove(".git")  # Don't recurse into .git

    return repos


def install_hook(repo_path: Path, hook_name: str, snippet: str, template: str) -> str:
    """
    Install a git hook in a repository.
    Returns: "installed", "updated", "exists", or "error: <message>"
    """
    hooks_dir = repo_path / ".git" / "hooks"
    hook_file = hooks_dir / hook_name

    if not hooks_dir.exists():
        return f"error: hooks directory not found"

    try:
        if hook_file.exists():
            # Read existing hook
            content = hook_file.read_text(encoding="utf-8")

            # Check if our hook is already installed
            if HOOK_MARKER in content:
                return "exists"

            # Append our hook snippet
            new_content = content.rstrip() + "\n" + snippet
            hook_file.write_text(new_content, encoding="utf-8")
            return "updated"
        else:
            # Create new hook file
            hook_file.write_text(template, encoding="utf-8")
            # Make executable (important on Unix, no-op on Windows but doesn't hurt)
            hook_file.chmod(hook_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            return "installed"

    except Exception as e:
        return f"error: {e}"


def main():
    print("Claude RAG Git Hook Installer")
    print("=" * 40)
    print(f"Reindex script: {REINDEX_SCRIPT}")
    print(f"Hooks: post-checkout (branch switch), post-merge (pull/merge)")
    print(f"Searching directories:")
    for d in DIRECTORIES:
        print(f"  - {d}")
    print()

    # Find all git repos
    print("Discovering git repositories...")
    repos = find_git_repos(DIRECTORIES)
    print(f"Found {len(repos)} git repositories\n")

    if not repos:
        print("No repositories found.")
        return

    # Hook configurations
    hooks = [
        ("post-checkout", POST_CHECKOUT_SNIPPET, POST_CHECKOUT_TEMPLATE),
        ("post-merge", POST_MERGE_SNIPPET, POST_MERGE_TEMPLATE),
    ]

    # Install hooks
    total_installed = 0
    total_updated = 0
    total_exists = 0
    total_errors = 0

    for repo in sorted(repos):
        results = []
        for hook_name, snippet, template in hooks:
            result = install_hook(repo, hook_name, snippet, template)
            results.append((hook_name, result))

        # Summarize per repo
        statuses = [r[1] for r in results]
        if all(s == "exists" for s in statuses):
            print(f"  [EXISTS]    {repo}")
            total_exists += 1
        elif any(s.startswith("error") for s in statuses):
            error_hooks = [r[0] for r in results if r[1].startswith("error")]
            print(f"  [ERROR]     {repo}: {', '.join(error_hooks)}")
            total_errors += 1
        elif any(s == "installed" for s in statuses):
            installed_hooks = [r[0] for r in results if r[1] == "installed"]
            print(f"  [INSTALLED] {repo} ({', '.join(installed_hooks)})")
            total_installed += 1
        else:
            updated_hooks = [r[0] for r in results if r[1] == "updated"]
            print(f"  [UPDATED]   {repo} ({', '.join(updated_hooks)})")
            total_updated += 1

    # Summary
    print()
    print("=" * 40)
    print("Summary:")
    print(f"  Installed: {total_installed}")
    print(f"  Updated:   {total_updated}")
    print(f"  Exists:    {total_exists}")
    print(f"  Errors:    {total_errors}")
    print()

    if total_installed > 0 or total_updated > 0:
        print("Hooks will trigger re-indexing on:")
        print("  - git checkout <branch>")
        print("  - git pull")
        print("  - git merge")


if __name__ == "__main__":
    main()
