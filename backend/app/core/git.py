"""The checkout the running code came from: its commit, and whether it had local edits."""

import subprocess

from app.core.config import PROJECT_ROOT

DIRTY_SUFFIX = "-dirty"


def read_git_commit() -> tuple[str | None, bool]:
    """HEAD, and whether tracked files had uncommitted edits; (None, False) outside a checkout."""
    try:
        described = subprocess.run(
            ["git", "describe", "--always", "--dirty", "--abbrev=40", "--exclude=*"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None, False
    return described.removesuffix(DIRTY_SUFFIX), described.endswith(DIRTY_SUFFIX)
