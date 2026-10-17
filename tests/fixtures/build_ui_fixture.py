"""Build a finished ScriptedModel trace in a temp copy of sample_repo for the browser e2e test.

Run: uv run python tests/fixtures/build_ui_fixture.py
Prints {"repo": <path>, "trace_id": <id>} as JSON on stdout.
"""

import json
import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(TESTS), str(TESTS / "unit")]

from test_service import ACCEPT, PARSE, STORE, RoutedModel, make, trace  # noqa: E402

from codemap.domain.models import Edge, Node  # noqa: E402
from codemap.repo.anchors import with_hash  # noqa: E402
from fakes import resp, tool_use  # noqa: E402


def effect(category: str, target: str, op: str, anchor: dict, id: str) -> object:  # noqa: A002
    spec = {
        "category": category,
        "target": target,
        "op": op,
        "anchor": anchor,
    }
    return resp(tool_use("record_effect", spec, id))


class EffectfulModel(RoutedModel):
    """The routed model, plus recorded reads and writes so the UI has data to show."""

    def __init__(self) -> None:
        super().__init__()
        w = self.walk
        w[1:1] = [effect("db", "document", "write", ACCEPT, "e1")]
        w[6:6] = [
            effect("object_store", "normalized/<id>", "write", PARSE, "e2"),
            effect("db", "document", "read", STORE, "e3"),
            effect("db", "document_page", "write", STORE, "e4"),
        ]


def add_third_level(svc, trace_id: str) -> None:  # noqa: ANN001
    """Split the step "accept" (the one the scripted explanation fits) into two sub-steps (level 2).

    The scripted model only splits phases, so the third level is stored directly.
    """
    graph = svc.get_graph(trace_id, 99)
    step = next(n for n in graph.nodes if n.title == "accept")
    anchor = step.anchors[0]
    mid = (anchor.start_line + anchor.end_line) // 2

    def span(start: int, end: int) -> dict[str, int]:
        return {"start_line": start, "end_line": end}

    def child(i: int, title: str, summary: str, start: int, end: int) -> Node:
        return Node(
            id=f"{step.id}-sub{i}", level=2, parent_id=step.id, order=i, title=title,
            summary=summary, does="d", input="i", output="o", boundary_reason="b",
            anchors=(with_hash(svc._tools, anchor.model_copy(update=span(start, end))),),
        )  # fmt: skip

    a = child(0, "First half", "Run the first lines of this step.", anchor.start_line, mid)
    b = child(1, "Second half", "Run the rest and return the result.", mid + 1, anchor.end_line)
    svc._store.replace_children(
        trace_id, step.id, [a, b], [Edge(source_id=a.id, target_id=b.id, kind="call")]
    )


def store_explanations(svc, trace_id: str) -> None:  # noqa: ANN001
    """Make every node's explanation now, with the scripted model.

    The dev server has no scripted model, so the browser test reads these stored ones.
    """
    for n in svc.get_graph(trace_id, 99).nodes:
        svc.get_detail(trace_id, n.id)


def main() -> None:
    svc, repo = make(Path(tempfile.mkdtemp(prefix="codemap-ui-")), EffectfulModel())
    trace_id = trace(svc)
    add_third_level(svc, trace_id)
    store_explanations(svc, trace_id)
    print(json.dumps({"repo": str(repo), "trace_id": trace_id}))


if __name__ == "__main__":
    main()
