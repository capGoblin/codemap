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


def test_search_clamps_max_results(repo: Path) -> None:
    (repo / "many.txt").write_text("hit\n" * 500)
    out = RepoTools(repo, RepoIgnore(repo)).search("hit", None, 10_000)
    assert len(out.splitlines()) == 200


@pytest.fixture
def cased(repo: Path) -> RepoTools:
    probe = repo / "app.py"
    if not (repo / "APP.PY").exists() or not probe.samefile(repo / "APP.PY"):
        pytest.skip("temp filesystem is case-sensitive")
    (repo / "svc" / "secret.txt").write_text(f"API_KEY={SECRET}\n")
    excluded = "svc/secret.txt\nsvc/personal.txt\nsvc/privdir/\n"
    (repo / ".git" / "info" / "exclude").write_text(excluded)
    (repo / "svc" / "privdir").mkdir()
    (repo / "svc" / "privdir" / "defs.py").write_text(f"def leak():\n    k = '{SECRET}'\n")
    return RepoTools(repo, RepoIgnore(repo))


@pytest.mark.parametrize(
    "path",
    [".ENV", "web/.ENV.LOCAL", "SVC/secret.txt", "svc/PRIVDIR/defs.py", ".GIT/config", "ID_RSA"],
)
def test_case_variants_are_refused(cased: RepoTools, path: str) -> None:
    out = cased.read_file(path)
    assert SECRET not in out and out.startswith("error")


def test_case_variant_dirs_and_outline_are_refused(cased: RepoTools) -> None:
    assert cased.list_dir("SVC/PRIVDIR").startswith("error")
    assert "leak" not in cased.outline("SVC/privdir/defs.py")
    assert "leak" not in cased.outline("svc/PRIVDIR/defs.py")
    assert cased.list_dir("SVC").splitlines() == ["ok.py"]


def test_case_variant_of_visible_file_still_reads(cased: RepoTools) -> None:
    assert "def main" in cased.read_file("APP.PY")


def test_python_search_does_not_follow_symlinks_into_ignored_files(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "normal.txt").symlink_to(repo / ".env")
    (repo / "svc" / "personal_link.py").symlink_to(repo / "web" / ".env.local")
    monkeypatch.setattr("codemap.repo.tools.shutil.which", lambda _name: None)
    tools = RepoTools(repo, RepoIgnore(repo))
    assert SECRET not in tools.search("API_KEY")


def test_tfvars_and_git_credentials_hidden(repo: Path) -> None:
    ignore = RepoIgnore(repo)
    assert ignore.is_ignored("infra/prod.tfvars") and ignore.is_ignored(".git-credentials")


def test_rg_search_stops_at_the_limit(repo: Path) -> None:
    (repo / "a.txt").write_text("hit\n" * 100)
    (repo / "b.txt").write_text("hit\n" * 100)
    out = RepoTools(repo, RepoIgnore(repo)).search("hit", None, 5).splitlines()
    assert len(out) == 5 and all(r.startswith("a.txt:") for r in out)
