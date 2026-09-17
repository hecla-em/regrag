"""The checkout the running code came from: its commit, and whether it had local edits."""

import subprocess

from app.core.config import PROJECT_ROOT

DIRTY_SUFFIX = "-dirty"
GIT_TIMEOUT_SECONDS = 5


def read_git_commit() -> tuple[str | None, bool]:
    """HEAD, and whether tracked files had uncommitted edits; (None, False) outside a checkout
    or when git does not answer in time."""
    try:
        described = subprocess.run(
            ["git", "describe", "--always", "--dirty", "--abbrev=40", "--exclude=*"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=GIT_TIMEOUT_SECONDS,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None, False
    return described.removesuffix(DIRTY_SUFFIX), described.endswith(DIRTY_SUFFIX)
