import shutil
from pathlib import Path

import pytest

from codemap.repo.ignore import RepoIgnore
from codemap.repo.sandbox import OutsideRepoError
from codemap.repo.tools import RepoTools

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(FIXTURE, dest)
    return dest


@pytest.fixture
def tools(repo: Path) -> RepoTools:
    return RepoTools(repo, RepoIgnore(repo))


def test_list_dir_hides_ignored(tools: RepoTools) -> None:
    rows = tools.list_dir(".").splitlines()
    assert "app/" in rows
    assert "data/" in rows
    assert "node_modules/" not in rows
    assert "build/" not in rows


def test_read_file_pages(repo: Path, tools: RepoTools) -> None:
    (repo / "big.txt").write_text("".join(f"line{i}\n" for i in range(1, 1001)))
    first = tools.read_file("big.txt").splitlines()
    assert first[0] == "1: line1"
    assert first[399] == "400: line400"
    assert first[-1] == "... 600 more lines; call read_file with start=401"
    second = tools.read_file("big.txt", start=401).splitlines()
    assert second[0] == "401: line401"
    assert second[399] == "800: line800"
    assert second[-1].endswith("start=801")
    last = tools.read_file("big.txt", start=801).splitlines()
    assert last[0] == "801: line801"
    assert last[-1] == "1000: line1000"
    assert len(last) == 200


def test_read_file_end_and_long_line(repo: Path, tools: RepoTools) -> None:
    (repo / "min.txt").write_text("a" * 5000 + "\nb\nc\n")
    out = tools.read_file("min.txt", start=1, end=2).splitlines()
    assert out == ["1: " + "a" * 2000, "2: b"]


def test_read_file_binary(tools: RepoTools) -> None:
    assert tools.read_file("data/blob.bin") == "binary file, not shown"


def test_file_text(tools: RepoTools) -> None:
    assert "def upload" in tools.file_text("app/api.py")


def test_file_text_raises(tools: RepoTools) -> None:
    with pytest.raises(OutsideRepoError):
        tools.file_text("../x")
    with pytest.raises(FileNotFoundError):
        tools.file_text("missing.py")


def test_search_finds_call(tools: RepoTools) -> None:
    assert "app/api.py" in tools.search("accept_document")


def test_search_skips_ignored(tools: RepoTools) -> None:
    assert "node_modules" not in tools.search("ignored")
    assert "build/out.py" not in tools.search("ignored")


def test_search_python_fallback(tools: RepoTools, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = tools.search("accept_document")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    out = tools.search("accept_document")
    assert "app/api.py" in out
    assert out.splitlines()[0].startswith("app/")
    assert sorted(out.splitlines()) == sorted(expected.splitlines())


def test_search_glob_and_max(tools: RepoTools) -> None:
    out = tools.search("def ", glob="*.py", max_results=2)
    assert len(out.splitlines()) == 2


def test_tool_returns_error_text_outside_root(tools: RepoTools) -> None:
    for out in (
        tools.read_file("../x"),
        tools.read_file("/etc/passwd"),
        tools.list_dir(".."),
        tools.read_file("missing.py"),
    ):
        assert out.startswith("error:")


def test_read_file_ignored_path(tools: RepoTools) -> None:
    for path in ("build/out.py", "node_modules/x.js"):
        assert tools.read_file(path).startswith("error: path is ignored")
        with pytest.raises(OutsideRepoError, match="path is ignored"):
            tools.file_text(path)


def test_list_dir_ignored_dir(tools: RepoTools) -> None:
    assert tools.list_dir("node_modules").startswith("error: path is ignored")


def test_read_file_dot_git(repo: Path, tools: RepoTools) -> None:
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[core]\n")
    assert tools.read_file(".git/config").startswith("error: path is ignored")
