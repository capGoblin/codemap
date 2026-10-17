from fastapi import APIRouter, Header, HTTPException, Query
from sse_starlette import EventSourceResponse
from starlette.concurrency import run_in_threadpool

from codemap import __version__
from codemap.domain.models import FunctionDetail, Trace, TraceGraph
from codemap.server.schemas import Health
from codemap.server.sse import event_stream
from codemap.service import Service


def make_router(service: Service) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> Health:
        return Health(version=__version__)

    @router.get("/traces")
    def list_traces() -> list[Trace]:
        return service.list_traces()

    @router.get("/traces/{trace_id}")
    def get_graph(trace_id: str, depth: int = Query(1, ge=0)) -> TraceGraph:
        return service.get_graph(trace_id, depth)

    @router.get("/traces/{trace_id}/events", response_class=EventSourceResponse)
    async def events(
        trace_id: str,
        after: int = Query(0, ge=0),
        last_event_id: str | None = Header(None),
    ) -> EventSourceResponse:
        await run_in_threadpool(service.get_graph, trace_id, 0)  # 404 before streaming
        if last_event_id is not None and last_event_id.isdigit():
            after = int(last_event_id)
        return EventSourceResponse(event_stream(service, trace_id, after))

    @router.post("/traces/{trace_id}/nodes/{node_id}/expand")
    def expand(trace_id: str, node_id: str) -> TraceGraph:
        graph = service.get_graph(trace_id, 1)
        if not any(n.id == node_id for n in graph.nodes):
            raise KeyError(node_id)
        has_children = any(n.parent_id == node_id for n in graph.nodes)
        if graph.trace.mode != "lazy" and has_children:
            raise HTTPException(409, "node is already expanded")
        return service.expand_node(trace_id, node_id)

    @router.get("/traces/{trace_id}/nodes/{node_id}/detail")
    def detail(trace_id: str, node_id: str) -> list[FunctionDetail]:
        return service.get_detail(trace_id, node_id)

    return router
