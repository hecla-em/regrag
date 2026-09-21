"""Reading the checkout the running code came from."""

import subprocess
from pathlib import Path

import pytest

from app.core import git
from app.core.git import read_git_commit


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


def edit_the_tracked_file(repo: Path) -> None:
    (repo / "tracked.txt").write_text("two")


def add_an_untracked_file(repo: Path) -> None:
    (repo / "scratch.txt").write_text("notes")


def tag_head(repo: Path) -> None:
    _git(repo, "tag", "v1")


@pytest.mark.parametrize(
    ("change", "dirty"),
    [
        pytest.param(None, False, id="a clean checkout"),
        pytest.param(edit_the_tracked_file, True, id="an edited tracked file is dirty"),
        pytest.param(add_an_untracked_file, False, id="an untracked file is not"),
        pytest.param(tag_head, False, id="a tag on HEAD still reads as the commit"),
    ],
)
def test_a_checkout_reads_as_its_full_commit_and_whether_tracked_files_were_edited(
    repo: Path, change, dirty: bool
):
    if change is not None:
        change(repo)

    commit, read_dirty = read_git_commit()

    assert commit is not None and len(commit) == 40
    assert read_dirty is dirty


def test_outside_a_checkout_nothing_is_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The image ships without .git, so a run there records no commit rather than failing."""
    monkeypatch.setattr(git, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))

    assert read_git_commit() == (None, False)
