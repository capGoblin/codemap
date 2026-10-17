"""The `open` command and the shared browser launch."""

import contextlib
import threading
import webbrowser

import typer

from codemap.cli import render
from codemap.server.run import serve_in_background
from codemap.service import Service


def block_until_interrupt() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        threading.Event().wait()


def serve_and_open(service: Service, trace_id: str) -> None:
    """Serve the UI, open the trace in the browser and block until Ctrl-C."""
    console = render.status_console(to_stderr=False)
    url = f"{serve_in_background(service)}/traces/{trace_id}"
    webbrowser.open(url)
    console.print(f"serving {url} | press Ctrl-C to stop")
    block_until_interrupt()


def open_trace(service: Service, trace_id: str | None) -> int:
    console = render.status_console(to_stderr=False)
    traces = service.list_traces()
    if trace_id is None:
        if not traces:
            console.print("no traces for this repo yet")
            return 0
        console.print(render.traces_table(traces))
        number = typer.prompt("Pick trace", default=1, type=int, err=True)
        if not 1 <= number <= len(traces):
            console.print(f"pick must be between 1 and {len(traces)}")
            return 2
        trace_id = traces[number - 1].id
    elif trace_id not in {t.id for t in traces}:
        console.print(f"unknown trace {trace_id}")
        return 1
    serve_and_open(service, trace_id)
    return 0
