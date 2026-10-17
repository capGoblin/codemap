import asyncio
import json
from collections.abc import AsyncIterator

from anyio import to_thread
from sse_starlette import ServerSentEvent

from codemap.service import Service

POLL_SECONDS = 0.25
_IDLE_POLLS_BEFORE_CLOSE = 2


async def event_stream(
    service: Service, trace_id: str, after_id: int
) -> AsyncIterator[ServerSentEvent]:
    """Poll the event log. Stop after `finished`, or when a non-running trace goes quiet."""
    idle = 0
    while True:
        batch = await to_thread.run_sync(service.events, trace_id, after_id)
        for event_id, event in batch:
            after_id = event_id
            yield ServerSentEvent(
                data=json.dumps(event.model_dump(mode="json")),
                event=event.kind,
                id=str(event_id),
            )
            if event.kind == "finished":
                return
        idle = 0 if batch else idle + 1
        if idle >= _IDLE_POLLS_BEFORE_CLOSE and not await _is_running(service, trace_id):
            return
        await asyncio.sleep(POLL_SECONDS)


async def _is_running(service: Service, trace_id: str) -> bool:
    traces = await to_thread.run_sync(service.list_traces)
    return any(t.id == trace_id and t.status == "running" for t in traces)
