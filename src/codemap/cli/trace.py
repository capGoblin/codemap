"""The `trace` command."""

import time

import typer
from rich.console import Console
from rich.live import Live

from codemap.cli import render
from codemap.service import ModelError, Service

POLL_SECONDS = 0.25
EXIT_NO_ENTRY = 1
EXIT_MODEL = 2
EXIT_INTERRUPTED = 130


def _pick(console: Console, count: int, pick: int | None) -> int:
    if pick is None:
        pick = typer.prompt("Pick entry point", default=1, type=int, err=True)
    if not 1 <= pick <= count:
        console.print(f"pick must be between 1 and {count}")
        raise typer.Exit(2)
    return pick - 1


def _follow(service: Service, trace_id: str, console: Console) -> None:
    """Show the latest event, a hop count and elapsed time until the trace finishes."""
    started = time.monotonic()
    after, hops, message, done = 0, 0, "starting", False
    with Live(console=console, transient=True, refresh_per_second=4) as live:
        while not done:
            for event_id, event in service.events(trace_id, after):
                after = event_id
                hops += event.kind == "hop_found"
                message = event.message
                done = event.kind == "finished"
            live.update(render.progress_line(message, hops, time.monotonic() - started))
            if not done:
                service.wait(trace_id, POLL_SECONDS)


def run_trace(service: Service, question: str, lazy: bool, pick: int | None, as_json: bool) -> None:
    console = render.status_console(to_stderr=as_json)
    try:
        candidates = service.resolve(question)
    except ModelError as exc:
        console.print(f"model call failed: {exc}\nRun `codemap doctor` to check your setup.")
        raise typer.Exit(EXIT_MODEL) from exc
    if not candidates:
        console.print(f'no entry point found for "{question}"')
        raise typer.Exit(EXIT_NO_ENTRY)
    console.print(render.candidates_table(candidates))
    entry = candidates[_pick(console, len(candidates), pick)]
    trace_id = service.start_trace(question, entry, "lazy" if lazy else "eager")
    try:
        _follow(service, trace_id, console)
    except KeyboardInterrupt:
        service.mark_partial(trace_id)
        console.print(f"stopped | partial | trace {trace_id}")
        raise typer.Exit(EXIT_INTERRUPTED) from None
    graph = service.get_graph(trace_id, depth=1)
    console.print(render.summary_line(graph), soft_wrap=True)
    if as_json:
        typer.echo(graph.model_dump_json(indent=2))
    if graph.trace.status == "failed":
        raise typer.Exit(1)
