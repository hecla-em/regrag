"""The checkout the running code came from: its commit, and whether it had local edits."""

import subprocess

from app.core.config import PROJECT_ROOT
from app.core.models import FrozenModel


class GitState(FrozenModel):
    """commit: HEAD, or None outside a checkout. dirty: tracked files had uncommitted edits."""

    commit: str | None = None
    dirty: bool = False


def _run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def read_git_state() -> GitState:
    """HEAD and whether tracked files changed; empty where there is no checkout, as in the image."""
    try:
        commit = _run_git("rev-parse", "HEAD")
        dirty = bool(_run_git("status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.CalledProcessError):
        return GitState()
    return GitState(commit=commit, dirty=dirty)
