"""Rich output for the CLI."""

from rich.console import Console
from rich.table import Table

from codemap.domain.models import EntryCandidate, Trace, TraceGraph

STATUS_STYLE = {"complete": "green", "partial": "yellow", "failed": "red", "running": "cyan"}


def candidates_table(candidates: list[EntryCandidate]) -> Table:
    table = Table(title="Entry points")
    table.add_column("#", justify="right")
    table.add_column("label")
    table.add_column("file:line")
    table.add_column("reason")
    for i, c in enumerate(candidates, 1):
        table.add_row(str(i), c.label, f"{c.anchor.file}:{c.anchor.start_line}", c.reason)
    return table


def traces_table(traces: list[Trace]) -> Table:
    table = Table(title="Traces")
    table.add_column("id", no_wrap=True)
    for name in ("created", "status", "cost", "question"):
        table.add_column(name)
    for t in traces:
        style = STATUS_STYLE[t.status]
        table.add_row(
            t.id,
            t.created_at.strftime("%Y-%m-%d %H:%M"),
            f"[{style}]{t.status}[/{style}]",
            f"${t.cost_usd:.4f}",
            t.question,
        )
    return table


def progress_line(message: str, hops: int, elapsed: float) -> str:
    return f"{message} | hops {hops} | {elapsed:.0f}s"


def summary_line(graph: TraceGraph) -> str:
    t = graph.trace
    phases = sum(1 for n in graph.nodes if n.level == 0)
    steps = sum(1 for n in graph.nodes if n.level == 1)
    style = STATUS_STYLE[t.status]
    return (
        f"[{style}]{t.status}[/{style}] | phases {phases} | steps {steps} | "
        f"tokens {t.input_tokens + t.output_tokens} | ${t.cost_usd:.4f} | trace {t.id}"
    )


def status_console(to_stderr: bool) -> Console:
    return Console(stderr=to_stderr, highlight=False)
