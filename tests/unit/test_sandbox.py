import shutil
from pathlib import Path

import pytest

from codemap.repo.ignore import RepoIgnore
from codemap.repo.sandbox import OutsideRepoError, resolve_inside

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(FIXTURE, dest)
    return dest


def test_rejects_parent_escape(repo: Path) -> None:
    with pytest.raises(OutsideRepoError):
        resolve_inside(repo, "../x")


def test_rejects_absolute(repo: Path) -> None:
    with pytest.raises(OutsideRepoError):
        resolve_inside(repo, "/etc/passwd")


def test_rejects_symlink_out(repo: Path, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("s")
    (repo / "link.txt").symlink_to(secret)
    with pytest.raises(OutsideRepoError):
        resolve_inside(repo, "link.txt")


def test_accepts_inside_path(repo: Path) -> None:
    assert resolve_inside(repo, "app/api.py") == (repo / "app/api.py").resolve()


def test_ignore_defaults_and_gitignore(repo: Path) -> None:
    ignore = RepoIgnore(repo)
    assert ignore.is_ignored("node_modules/x.js")
    assert ignore.is_ignored("build/out.py")
    assert ignore.is_ignored("app/__pycache__/a.pyc")
    assert ignore.is_ignored("x.min.js")
    assert not ignore.is_ignored("app/api.py")
