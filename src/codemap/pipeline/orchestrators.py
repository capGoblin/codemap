"""Collapse orchestrator points: functions that only call other path points in sequence.

An orchestrator is an edge, not a child. Its callees become the children directly.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from codemap.domain.models import Anchor, Effect
from codemap.domain.rules import anchor_contains
from codemap.repo.calls import calls_in
from codemap.repo.tools import RepoTools

MIN_CALLS = 3
MAX_SHARE = 0.25  # the orchestrator's lines, as a share of its callees' lines combined


@dataclass(frozen=True)
class Orchestrator:
    anchor: Anchor
    callees: tuple[Anchor, ...]  # in the order the body calls them


def _lines(anchor: Anchor) -> int:
    return anchor.end_line - anchor.start_line + 1


def _short(symbol: str) -> str:
    return symbol.rsplit(".", 1)[-1]


def find_orchestrators(
    tools: RepoTools, points: Sequence[Anchor], effects: Sequence[Effect]
) -> list[Orchestrator]:
    """Points with >= 3 call sites to other points, <= 25% of their lines, and no effects."""
    by_name: dict[str, list[Anchor]] = {}
    for p in points:
        by_name.setdefault(_short(p.symbol), []).append(p)
    found: list[Orchestrator] = []
    for p in points:
        if any(anchor_contains(p, e.anchor) for e in effects):
            continue
        callees: list[Anchor] = []
        sites = calls_in(tools, p)
        for site in sites:
            for target in by_name.get(site.name, []):
                if target != p and target not in callees:
                    callees.append(target)
        n_sites = sum(1 for s in sites if s.name in by_name and s.name != _short(p.symbol))
        if n_sites < MIN_CALLS or len(callees) < MIN_CALLS:
            continue
        if _lines(p) <= MAX_SHARE * sum(_lines(c) for c in callees):
            found.append(Orchestrator(p, tuple(callees)))
    return found


def flatten_points(
    tools: RepoTools, points: Sequence[Anchor], effects: Sequence[Effect]
) -> tuple[list[Anchor], list[Orchestrator]]:
    """The points without their orchestrators, and the orchestrators that were removed."""
    orchestrators = find_orchestrators(tools, points, effects)
    gone = {o.anchor for o in orchestrators}
    return [p for p in points if p not in gone], orchestrators


def orchestrator_note(orchestrators: Sequence[Orchestrator]) -> str:
    """Context for the model: each folded orchestrator and the order it calls its callees."""
    return "\n".join(
        f"- {o.anchor.file}:{o.anchor.start_line}-{o.anchor.end_line} {o.anchor.symbol} "
        f"calls, in order: {', '.join(c.symbol for c in o.callees)}"
        for o in orchestrators
    )
