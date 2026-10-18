"""Run one trace per target repo and report scale numbers.

python -m evals.run_smoke evals/smoke.json
"""

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from codemap.agents.model import ChatModel
from codemap.domain.models import Anchor, EntryCandidate
from codemap.service import Service
from codemap.settings import load_settings

ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path(__file__).resolve().parents[1] / "docs/notes/eval-results.md"
_HOP = re.compile(r"^(\S+?):\d+-\d+ ")


class SmokeEntry(BaseModel):
    repo: str
    question: str
    entry: Anchor
    note: str = ""


class SmokeRow(BaseModel):
    repo: str
    status: str
    phases: int
    steps: int
    hops: int
    cost_usd: float
    wall_s: float
    files_read: int


def resolve_repo(repo: str) -> Path:
    """A relative repo path is relative to the codemap checkout."""
    path = Path(repo)
    return path if path.is_absolute() else (ROOT / path).resolve()


def load_smoke(path: Path) -> list[SmokeEntry]:
    return [SmokeEntry.model_validate(item) for item in json.loads(path.read_text())]


def run_smoke(path: Path, model: ChatModel | None = None) -> list[SmokeRow]:
    """Trace every entry in the file. `model` is for tests."""
    settings = load_settings()
    rows = []
    for item in load_smoke(path):
        root = resolve_repo(item.repo)
        service = Service(root, settings, model)
        entry = EntryCandidate(anchor=item.entry, label="smoke", reason="pinned")
        started = time.monotonic()
        trace_id = service.start_trace(item.question, entry, "eager")
        service.wait(trace_id)
        wall = time.monotonic() - started
        graph = service.get_graph(trace_id, depth=2)
        # files_read: distinct files named in hop_found events and in stored node anchors.
        files = {a.file for n in graph.nodes for a in n.anchors}
        for _, event in service.events(trace_id):
            if event.kind == "hop_found" and (m := _HOP.match(event.message)):
                files.add(m.group(1))
        hops = sum(e.kind == "hop_found" for _, e in service.events(trace_id))
        rows.append(
            SmokeRow(
                repo=root.name,
                status=graph.trace.status,
                phases=sum(n.level == 0 for n in graph.nodes),
                steps=sum(n.level > 0 for n in graph.nodes),
                hops=hops,
                cost_usd=graph.trace.cost_usd,
                wall_s=round(wall, 1),
                files_read=len(files),
            )
        )
    return rows


def format_table(rows: list[SmokeRow]) -> str:
    head = "| repo | status | phases | steps | hops | cost_usd | wall_s | files_read |"
    lines = [head, "|" + " --- |" * 8]
    lines += [
        f"| {r.repo} | {r.status} | {r.phases} | {r.steps} | {r.hops} "
        f"| {r.cost_usd:.4f} | {r.wall_s} | {r.files_read} |"
        for r in rows
    ]
    return "\n".join(lines)


def append_results(rows: list[SmokeRow], model: str, results: Path = RESULTS) -> None:
    results.parent.mkdir(parents=True, exist_ok=True)
    with results.open("a", encoding="utf-8") as out:
        out.write(f"\n## Smoke run {date.today().isoformat()} ({model})\n\n{format_table(rows)}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run_smoke")
    parser.add_argument("smoke", type=Path)
    args = parser.parse_args(argv)
    rows = run_smoke(args.smoke)
    print(format_table(rows))
    append_results(rows, load_settings().model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
