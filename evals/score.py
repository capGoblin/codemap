"""Compare a produced TraceGraph with a hand-written expected trace."""

from dataclasses import dataclass

from codemap.domain.models import Anchor, Node, TraceGraph
from evals.expected import ExpectedNode, ExpectedTrace

Lines = set[tuple[str, int]]


@dataclass(frozen=True)
class Score:
    off_path_nodes: int
    phase_agreement: float
    step_agreement: float
    effect_recall: float
    effect_extra: int
    status: str


def _lines(anchors: list[Anchor] | tuple[Anchor, ...]) -> Lines:
    return {(a.file, n) for a in anchors for n in range(a.start_line, a.end_line + 1)}


def _iou(a: Lines, b: Lines) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _agreement(actual: list[Lines], expected: list[Lines]) -> float:
    """Mean IoU of matched pairs * matched count / max(n) = sum of IoU / max(n)."""
    biggest = max(len(actual), len(expected))
    if biggest == 0:
        return 1.0
    return sum(_iou(actual[i], expected[j]) for i, j in _match(actual, expected)) / biggest


def _match(actual: list[Lines], expected: list[Lines]) -> list[tuple[int, int]]:
    """Greedy one-to-one match by IoU."""
    pairs = sorted(
        ((_iou(a, e), i, j) for i, a in enumerate(actual) for j, e in enumerate(expected)),
        reverse=True,
    )
    used_a: set[int] = set()
    used_e: set[int] = set()
    out = []
    for iou, i, j in pairs:
        if iou > 0 and i not in used_a and j not in used_e:
            used_a.add(i)
            used_e.add(j)
            out.append((i, j))
    return out


def _all_spans(nodes: list[ExpectedNode]) -> Lines:
    out: Lines = set()
    for n in nodes:
        out |= _lines(n.spans) | _all_spans(n.steps)
    return out


def score(graph: TraceGraph, expected: ExpectedTrace) -> Score:
    nodes = sorted(graph.nodes, key=lambda n: n.order)
    phases = [n for n in nodes if n.level == 0]
    exp_lines = [_lines(p.spans) for p in expected.phases]
    act_lines = [_lines(p.anchors) for p in phases]

    expected_all = _all_spans(expected.phases)
    off_path = sum(1 for n in nodes if not (_lines(n.anchors) & expected_all))

    step_scores = []
    for i, j in _match(act_lines, exp_lines):
        steps: list[Node] = [n for n in nodes if n.parent_id == phases[i].id]
        step_scores.append(
            _agreement(
                [_lines(s.anchors) for s in steps],
                [_lines(s.spans) for s in expected.phases[j].steps],
            )
        )
    step_agreement = sum(step_scores) / len(step_scores) if step_scores else 0.0

    actual_fx = {(e.category, e.target, e.op) for n in nodes for e in n.effects}
    want_fx = {(e.category, e.target, e.op) for e in expected.effects}
    recall = len(actual_fx & want_fx) / len(want_fx) if want_fx else 1.0

    return Score(
        off_path_nodes=off_path,
        phase_agreement=_agreement(act_lines, exp_lines),
        step_agreement=step_agreement,
        effect_recall=recall,
        effect_extra=len(actual_fx - want_fx),
        status=graph.trace.status,
    )


def format_score(s: Score) -> str:
    return (
        f"| {s.status} | off_path={s.off_path_nodes} | phase={s.phase_agreement:.2f} "
        f"| step={s.step_agreement:.2f} | effect_recall={s.effect_recall:.2f} "
        f"| effect_extra={s.effect_extra} |"
    )
