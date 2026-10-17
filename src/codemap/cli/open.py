"""The `open` command. Serving the browser UI arrives in Plan 2."""

from codemap.cli import render
from codemap.service import Service


def list_traces(service: Service, trace_id: str | None) -> int:
    console = render.status_console(to_stderr=False)
    traces = service.list_traces()
    if trace_id is not None:
        if trace_id not in {t.id for t in traces}:
            console.print(f"unknown trace {trace_id}")
            return 1
        console.print(f"trace {trace_id}: the browser view is not available yet")
        return 0
    if not traces:
        console.print("no traces for this repo yet")
        return 0
    console.print(render.traces_table(traces))
    return 0
