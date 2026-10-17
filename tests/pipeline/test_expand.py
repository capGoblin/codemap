import shutil
from datetime import UTC, datetime
from pathlib import Path

from codemap.domain.models import Anchor, Node, Trace
from codemap.pipeline.context import build_context
from codemap.pipeline.expand import expand_static
from codemap.repo.calls import calls_in
from codemap.settings import Settings
from fakes import ScriptedModel

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"
UPLOAD = Anchor(file="app/api.py", start_line=5, end_line=8, symbol="upload")


def make_ctx(tmp_path: Path):  # noqa: ANN201
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    ctx = build_context(repo, Settings(), "t1", model=ScriptedModel([]))
    ctx.store.create_trace(
        Trace(
            id="t1", question="q", entry=UPLOAD, commit_sha=None, dirty=False,
            status="running", mode="eager", created_at=datetime.now(UTC), model="m",
        )
    )  # fmt: skip
    return ctx


def phase(anchor: Anchor) -> Node:
    return Node(
        id="p", level=0, parent_id=None, order=0, title="intake", does="", input="", output="",
        boundary_reason="", anchors=(anchor,),
    )  # fmt: skip


def test_calls_in_python(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    sites = calls_in(ctx.tools, UPLOAD)
    assert [(s.name, s.line) for s in sites] == [("accept_document", 6), ("enqueue", 7)]
    inner = Anchor(file="app/documents.py", start_line=12, end_line=14, symbol="accept_document")
    got = [(s.name, s.full) for s in calls_in(ctx.tools, inner)]
    assert ("insert", "db.insert") in got and ("Doc", "Doc") in got


def test_expand_static_follows_calls_without_the_model(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    result = expand_static(ctx, phase(UPLOAD), [], max_depth=3, max_points=80)
    names = {h.callee.symbol for h in result.hops}
    assert {"accept_document", "enqueue", "insert", "Doc"} <= names
    assert all(h.verdict == "code_checked" and h.kind == "call" for h in result.hops)
    assert all(h.callee.content_hash for h in result.hops)
    assert all(
        "node_modules" not in h.callee.file and "build" not in h.callee.file for h in result.hops
    )
    assert len({(h.callee.file, h.callee.start_line) for h in result.hops}) == len(result.hops)


def test_expand_static_respects_point_cap(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    assert len(expand_static(ctx, phase(UPLOAD), [], max_points=2).hops) == 2


def write_repo(tmp_path: Path, files: dict[str, str]):  # noqa: ANN201
    repo = tmp_path / "r"
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    return build_context(repo, Settings(), "t1", model=ScriptedModel([]))


def test_calls_in_typescript_and_go(tmp_path: Path) -> None:
    ctx = write_repo(
        tmp_path,
        {
            "a.ts": (
                "function f(x) {\n  console.log(x);\n  const y = svc.load(x);\n  return g(y);\n}\n"
            ),
            "b.go": "package b\nfunc F() {\n\tn := len(xs)\n\tstore.Save(n)\n\tdo(n)\n}\n",
        },
    )
    ts = calls_in(ctx.tools, Anchor(file="a.ts", start_line=1, end_line=5, symbol="f"))
    assert [(s.name, s.line) for s in ts] == [("load", 3), ("g", 4)]
    go = calls_in(ctx.tools, Anchor(file="b.go", start_line=2, end_line=6, symbol="F"))
    assert [(s.name, s.line) for s in go] == [("Save", 4), ("do", 5)]


def test_expand_static_skips_ignored_and_unknown(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    # node_modules/x.js and build/out.py are ignored; ocr is never called from upload
    result = expand_static(ctx, phase(UPLOAD), [], max_points=80)
    assert not [h for h in result.hops if h.callee.file.startswith(("node_modules", "build"))]


def test_disambiguation_same_file_then_import(tmp_path: Path) -> None:
    ctx = write_repo(
        tmp_path,
        {
            "app/main.py": (
                "from app import good\n\n\ndef run():\n    helper()\n    other()\n\n\n"
                "def helper():\n    return 1\n"
            ),
            "app/good.py": "def other():\n    return 1\n",
            "lib/bad.py": "def other():\n    return 2\n\n\ndef helper():\n    return 3\n",
        },
    )
    main = Anchor(file="app/main.py", start_line=4, end_line=6, symbol="run")
    from codemap.pipeline.expand import pick_definition

    helper = ctx.tools.index.find_definition("helper")  # type: ignore[union-attr]
    other = ctx.tools.index.find_definition("other")  # type: ignore[union-attr]
    site = calls_in(ctx.tools, main)
    by_name = {s.name: s for s in site}
    assert pick_definition(ctx, "app/main.py", by_name["helper"], helper)[0] == "app/main.py"  # type: ignore[index]
    assert pick_definition(ctx, "app/main.py", by_name["other"], other)[0] == "app/good.py"  # type: ignore[index]
