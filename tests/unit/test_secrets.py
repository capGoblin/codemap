"""C2: files the agent must never see, whatever the ignore source."""

import subprocess
from pathlib import Path

import pytest

from codemap.repo.ignore import RepoIgnore
from codemap.repo.tools import RepoTools

SECRET = "sk-live-123"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "web").mkdir(parents=True)
    (root / "svc").mkdir()
    (root / "app.py").write_text("def main():\n    pass\n")
    (root / "web" / ".gitignore").write_text(".env*.local\nlocal_notes.txt\n")
    (root / "web" / ".env.local").write_text(f"API_KEY={SECRET}\n")
    (root / "web" / "local_notes.txt").write_text(f"API_KEY={SECRET}\n")
    (root / "svc" / "ok.py").write_text("x = 1\n")
    (root / "svc" / "personal.txt").write_text(f"API_KEY={SECRET}\n")
    (root / ".env").write_text(f"API_KEY={SECRET}\n")  # not git-ignored
    (root / ".env.example").write_text("API_KEY=\n")
    (root / "id_rsa").write_text(f"KEY {SECRET}\n")
    (root / "prod.env").write_text(f"API_KEY={SECRET}\n")
    (root / "secrets.yaml").write_text(f"k: {SECRET}\n")
    (root / ".aws").mkdir()
    (root / ".aws" / "config").write_text(f"k={SECRET}\n")
    _git(root, "init", "-q")
    (root / ".git" / "info" / "exclude").write_text("svc/personal.txt\n")
    return root


@pytest.fixture(params=["git", "plain"])
def tools(repo: Path, request: pytest.FixtureRequest) -> RepoTools:
    if request.param == "plain":
        # Without git the nested .gitignore files are still honored; info/exclude is git only.
        (repo / ".git" / "info" / "exclude").write_text("")
        (repo / ".git").rename(repo / "dotgit")
        (repo / "svc" / "personal.txt").unlink()
    return RepoTools(repo, RepoIgnore(repo))


@pytest.mark.parametrize(
    "path",
    [
        "web/.env.local",
        "web/local_notes.txt",
        ".env",
        "id_rsa",
        "prod.env",
        "secrets.yaml",
        ".aws/config",
    ],
)
def test_read_file_refuses_secret(tools: RepoTools, path: str) -> None:
    out = tools.read_file(path)
    assert SECRET not in out and out.startswith("error")


def test_git_exclude_file_refused(repo: Path) -> None:
    tools = RepoTools(repo, RepoIgnore(repo))
    assert tools.read_file("svc/personal.txt").startswith("error")


def test_list_dir_hides_secrets(tools: RepoTools) -> None:
    root = tools.list_dir(".").splitlines()
    assert ".env" not in root and "id_rsa" not in root and ".aws/" not in root
    assert ".env.example" in root and "app.py" in root
    assert ".env.local" not in tools.list_dir("web").splitlines()


@pytest.mark.parametrize("glob", [None, "*.env", ".env*", "*", "!*.py", "**/.env*", "web/*"])
def test_search_never_exposes_secrets(tools: RepoTools, glob: str | None) -> None:
    assert SECRET not in tools.search("API_KEY|KEY|k:", glob)


def test_search_negated_glob_is_an_error(tools: RepoTools) -> None:
    assert tools.search("x", "!*.py").startswith("error")


def test_env_example_stays_visible(repo: Path) -> None:
    assert not RepoIgnore(repo).is_ignored(".env.example")
