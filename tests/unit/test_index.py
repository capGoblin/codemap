import shutil
from pathlib import Path

import pytest

from codemap.repo import index as index_module
from codemap.repo.ignore import RepoIgnore
from codemap.repo.index import MemorySymbolCache, SymbolIndex
from codemap.repo.tools import RepoTools

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(FIXTURE, dest)
    return dest


@pytest.fixture
def tools(repo: Path) -> RepoTools:
    found = RepoTools(repo, RepoIgnore(repo))
    found.index = SymbolIndex(found, MemorySymbolCache())
    return found


def _names(tools: RepoTools, path: str) -> dict[str, int]:
    assert tools.index is not None
    return {s.name: s.start_line for s in tools.index.outline(path)}


def test_outline_python(tools: RepoTools) -> None:
    names = _names(tools, "app/worker.py")
    assert names["parse_document"] == 1 + 8
    assert names["ocr"] == 5


def test_outline_python_class_and_method(tools: RepoTools, repo: Path) -> None:
    (repo / "m.py").write_text("class A:\n    def run(self, default=1):\n        pass\n")
    assert _names(tools, "m.py") == {"A": 1, "run": 2}


def test_outline_typescript(tools: RepoTools, repo: Path) -> None:
    (repo / "a.ts").write_text(
        "class Svc {\n  run(x: number) { return x }\n}\nfunction go() {}\nconst f = () => 1\n"
    )
    assert _names(tools, "a.ts") == {"Svc": 1, "run": 2, "go": 4}


def test_outline_go(tools: RepoTools, repo: Path) -> None:
    (repo / "a.go").write_text("package a\nfunc (s S) Run() {}\nfunc Main() {}\n")
    assert _names(tools, "a.go") == {"Run": 2, "Main": 3}


def test_outline_rust_impl(tools: RepoTools, repo: Path) -> None:
    (repo / "a.rs").write_text("struct S;\nimpl S {\n    fn go(&self) {}\n}\n")
    assert _names(tools, "a.rs") == {"S": 2, "go": 3}


def test_outline_unknown_ext_fallback(tools: RepoTools, repo: Path) -> None:
    (repo / "x.zzz").write_text("one\nfunction foo()\n")
    symbols = tools.index.outline("x.zzz")  # type: ignore[union-attr]
    assert [(s.name, s.start_line, s.end_line) for s in symbols] == [("foo", 2, 2)]


def test_outline_missing_grammar_falls_back(
    tools: RepoTools, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_: str) -> None:
        raise RuntimeError("no grammar")

    monkeypatch.setattr(index_module.tslp, "get_parser", boom)
    assert _names(tools, "app/worker.py") == {"ocr": 5, "parse_document": 9}


def test_outline_cached(tools: RepoTools, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = index_module.tslp.get_parser

    def spy(name: str) -> object:
        calls.append(name)
        return real(name)

    monkeypatch.setattr(index_module.tslp, "get_parser", spy)
    assert tools.index is not None
    first = tools.index.outline("app/worker.py")
    assert tools.index.outline("app/worker.py") == first
    assert calls == ["python"]


def test_outline_ignored_file(tools: RepoTools) -> None:
    assert tools.index.outline("build/out.py") == []  # type: ignore[union-attr]


def test_find_definition(tools: RepoTools) -> None:
    assert tools.index is not None
    hits = tools.index.find_definition("queue.enqueue")
    assert [(p, s.name) for p, s in hits] == [("app/queue.py", "enqueue")]


def test_tool_text(tools: RepoTools) -> None:
    assert "app/worker.py:9-12 function_definition parse_document" in tools.outline("app/worker.py")
    assert tools.find_definition("enqueue").startswith("app/queue.py:")
    assert tools.find_definition("nope_zzz").startswith("no definition")


def test_outline_file_starting_with_error_prefix(tools: RepoTools, repo: Path) -> None:
    (repo / "e.py").write_text("error: not a failure\ndef real():\n    pass\n")
    assert _names(tools, "e.py") == {"real": 2}
