"""Reading the checkout the running code came from."""

import subprocess
from pathlib import Path

import pytest

from app.core import git
from app.core.git import GitState, read_git_state


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A one-commit checkout standing in for the project root."""
    _git(tmp_path, "init")
    (tmp_path / "tracked.txt").write_text("one")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "one")
    monkeypatch.setattr(git, "PROJECT_ROOT", tmp_path)
    return tmp_path


def test_a_clean_checkout_reads_its_commit(repo: Path):
    state = read_git_state()

    assert state.commit is not None
    assert len(state.commit) == 40
    assert state.dirty is False


def test_an_edited_tracked_file_marks_the_checkout_dirty(repo: Path):
    (repo / "tracked.txt").write_text("two")

    assert read_git_state().dirty is True


def test_an_untracked_file_leaves_the_checkout_clean(repo: Path):
    (repo / "scratch.txt").write_text("notes")

    assert read_git_state().dirty is False


def test_outside_a_checkout_nothing_is_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The image ships without .git, so a run there records no commit rather than failing."""
    monkeypatch.setattr(git, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))

    assert read_git_state() == GitState()
