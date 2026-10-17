from pathlib import Path

from codemap.domain.models import Anchor, Hop, Node
from codemap.pipeline.detail import build_detail
from codemap.repo.ignore import RepoIgnore
from codemap.repo.index import MemorySymbolCache, SymbolIndex
from codemap.repo.tools import RepoTools

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"

UPLOAD = Anchor(file="app/api.py", start_line=5, end_line=8, symbol="upload")
ACCEPT = Anchor(file="app/documents.py", start_line=12, end_line=14, symbol="accept_document")


def make_tools() -> RepoTools:
    tools = RepoTools(FIXTURE, RepoIgnore(FIXTURE))
    tools.index = SymbolIndex(tools, MemorySymbolCache())
    return tools


def node(*anchors: Anchor) -> Node:
    return Node(
        id="n1", level=1, parent_id=None, order=0, title="t", does="", input="", output="",
        boundary_reason="", anchors=anchors,
    )  # fmt: skip


def hop() -> Hop:
    return Hop(id="h1", caller=UPLOAD, callee=ACCEPT, kind="call", hop_type="direct")


def test_detail_code_and_calls() -> None:
    (d,) = build_detail(make_tools(), node(UPLOAD), [hop()])
    assert d.calls == ("accept_document",)
    assert d.code.splitlines()[0] == "def upload(request):"
    assert d.code.splitlines()[-1].strip() == 'return {"id": doc.id}'
    assert "def upload" in d.signature


def test_detail_one_entry_per_anchor_and_no_calls_for_callee() -> None:
    a, b = build_detail(make_tools(), node(UPLOAD, ACCEPT), [hop()])
    assert (a.anchor, b.anchor) == (UPLOAD, ACCEPT)
    assert b.calls == ()


def test_detail_unreadable_file_does_not_raise() -> None:
    ghost = Anchor(file="app/ghost.py", start_line=1, end_line=2, symbol="x")
    (d,) = build_detail(make_tools(), node(ghost), [])
    assert d.code == ""
    assert d.signature.startswith("unavailable: ")


def test_detail_outside_repo_does_not_raise() -> None:
    bad = Anchor(file="../x.py", start_line=1, end_line=2, symbol="x")
    (d,) = build_detail(make_tools(), node(bad), [])
    assert d.code == "" and d.signature.startswith("unavailable: ")


def test_detail_calls_use_overlap_skip_rejected_and_dedupe() -> None:
    spelled = UPLOAD.model_copy(update={"symbol": "Api.upload", "start_line": 6})
    other = Anchor(file="app/queue.py", start_line=6, end_line=7, symbol="enqueue")
    hops = [
        hop(),
        hop().model_copy(update={"id": "h2", "caller": spelled}),
        hop().model_copy(update={"id": "h3", "callee": other, "verdict": "rejected"}),
    ]
    (d,) = build_detail(make_tools(), node(UPLOAD), hops)
    assert d.calls == ("accept_document",)
