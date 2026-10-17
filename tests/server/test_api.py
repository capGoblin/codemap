import json
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from codemap import __version__
from codemap.server.app import create_app
from codemap.server.run import serve_in_background
from codemap.service import Service
from conftest import MakeTrace


def sse_messages(client: TestClient, url: str, **kw: object) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    with client.stream("GET", url, **kw) as r:  # type: ignore[arg-type]
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if not line:
                if cur:
                    out.append(cur)
                    cur = {}
            elif not line.startswith(":"):
                key, _, value = line.partition(":")
                cur[key] = value.strip()
    return out


def test_health(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {"version": __version__}


def test_openapi_path(client: TestClient) -> None:
    schema = client.get("/api/v1/openapi.json").json()
    assert "TraceGraph" in schema["components"]["schemas"]
    assert client.get("/docs").status_code == 404


def test_list_traces(client: TestClient, make_trace: MakeTrace) -> None:
    trace_id = make_trace("eager")
    assert [t["id"] for t in client.get("/api/v1/traces").json()] == [trace_id]


def test_graph_depth0_vs_1(client: TestClient, make_trace: MakeTrace) -> None:
    trace_id = make_trace("eager")
    d0 = client.get(f"/api/v1/traces/{trace_id}?depth=0").json()
    d1 = client.get(f"/api/v1/traces/{trace_id}?depth=1").json()
    assert len(d0["nodes"]) < len(d1["nodes"])


def test_graph_unknown_404(client: TestClient) -> None:
    r = client.get("/api/v1/traces/nope")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_detail_has_code(client: TestClient, make_trace: MakeTrace) -> None:
    trace_id = make_trace("eager")
    nodes = client.get(f"/api/v1/traces/{trace_id}").json()["nodes"]
    node = next(n for n in nodes if n["title"] == "accept")
    body = client.get(f"/api/v1/traces/{trace_id}/nodes/{node['id']}/detail").json()
    assert any("def accept_document" in d["code"] for d in body["functions"])
    assert body["explain"]["steps"][0]["file"] == "app/documents.py"
    assert body["explain_error"] is None


def test_detail_regenerate(client: TestClient, make_trace: MakeTrace) -> None:
    trace_id = make_trace("eager")
    nodes = client.get(f"/api/v1/traces/{trace_id}").json()["nodes"]
    node = next(n for n in nodes if n["title"] == "accept")
    r = client.post(f"/api/v1/traces/{trace_id}/nodes/{node['id']}/detail/regenerate")
    assert r.status_code == 200
    assert r.json()["explain"]["steps"]
    missing = client.post(f"/api/v1/traces/{trace_id}/nodes/nope/detail/regenerate")
    assert missing.status_code == 404


def test_detail_unknown_node_404(client: TestClient, make_trace: MakeTrace) -> None:
    trace_id = make_trace("eager")
    assert client.get(f"/api/v1/traces/{trace_id}/nodes/nope/detail").status_code == 404


def test_events_sse_ends_with_finished(client: TestClient, make_trace: MakeTrace) -> None:
    trace_id = make_trace("eager")
    msgs = sse_messages(client, f"/api/v1/traces/{trace_id}/events")
    assert msgs[-1]["event"] == "finished"
    assert json.loads(msgs[-1]["data"])["kind"] == "finished"
    assert [int(m["id"]) for m in msgs] == sorted(int(m["id"]) for m in msgs)


def test_events_resume_after(client: TestClient, make_trace: MakeTrace) -> None:
    trace_id = make_trace("eager")
    url = f"/api/v1/traces/{trace_id}/events"
    all_ids = [int(m["id"]) for m in sse_messages(client, url)]
    assert len(all_ids) > 1
    cut = all_ids[0]
    assert [int(m["id"]) for m in sse_messages(client, f"{url}?after={cut}")] == all_ids[1:]
    resumed = sse_messages(client, url, headers={"Last-Event-ID": str(cut)})
    assert [int(m["id"]) for m in resumed] == all_ids[1:]


def test_events_unknown_trace_404(client: TestClient) -> None:
    assert client.get("/api/v1/traces/nope/events").status_code == 404


def test_expand_lazy_then_409_when_eager(client: TestClient, make_trace: MakeTrace) -> None:
    lazy = make_trace("lazy")
    phase = next(
        n for n in client.get(f"/api/v1/traces/{lazy}").json()["nodes"] if n["title"] == "intake"
    )
    r = client.post(f"/api/v1/traces/{lazy}/nodes/{phase['id']}/expand")
    assert r.status_code == 200
    assert {"accept", "queue"} <= {n["title"] for n in r.json()["nodes"]}


def test_expand_eager_with_children_409(client: TestClient, make_trace: MakeTrace) -> None:
    eager = make_trace("eager")
    phase = next(
        n for n in client.get(f"/api/v1/traces/{eager}").json()["nodes"] if n["title"] == "intake"
    )
    assert client.post(f"/api/v1/traces/{eager}/nodes/{phase['id']}/expand").status_code == 409


def test_expand_unknown_404(client: TestClient, make_trace: MakeTrace) -> None:
    trace_id = make_trace("lazy")
    assert client.post(f"/api/v1/traces/{trace_id}/nodes/nope/expand").status_code == 404


def test_spa_fallback_and_cache_headers(service: Service, tmp_path: Path) -> None:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>spa</html>")
    (static / "assets" / "app-abc123.js").write_text("x")
    c = TestClient(create_app(service, static))
    r = c.get("/traces/x")
    assert (r.status_code, r.text) == (200, "<html>spa</html>")
    assert r.headers["cache-control"] == "no-cache"
    assert c.get("/").headers["cache-control"] == "no-cache"
    asset = c.get("/assets/app-abc123.js")
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert c.get("/api/v1/nope").status_code == 404
    assert c.get("/api/v1/nope").headers["content-type"].startswith("application/json")


def test_no_static_dir_root_404(client: TestClient) -> None:
    assert client.get("/").status_code == 404


def test_bound_localhost(service: Service) -> None:
    url = serve_in_background(service)
    assert url.startswith("http://127.0.0.1:")
    assert httpx.get(f"{url}/api/v1/health").json() == {"version": __version__}


def test_stream_ends_for_quiet_non_running_trace(service: Service, make_trace: MakeTrace) -> None:
    import asyncio

    from codemap.server.sse import event_stream

    trace_id = make_trace("eager")
    last_id = service.events(trace_id)[-1][0]

    async def drain() -> list[object]:
        return [e async for e in event_stream(service, trace_id, last_id)]

    assert asyncio.run(asyncio.wait_for(drain(), 5)) == []


class _StepsFail:
    """Fail every step split. Walk and phase split answers come from the scripted model."""

    def __init__(self, inner: object) -> None:
        self.inner = inner

    def respond(self, *, system: str, **kw: Any) -> Any:
        from codemap.agents.model import ModelError
        from codemap.pipeline.context import prompt

        if system == prompt("split_steps"):
            raise ModelError("rate limited")
        return self.inner.respond(system=system, **kw)  # type: ignore[attr-defined]


def _failed_trace(service: Service, mode: str) -> str:
    from conftest import RoutedModel as Good

    service._model = _StepsFail(Good())  # type: ignore[assignment]
    entry = service.resolve("app/api.py:upload")[0]
    trace_id = service.start_trace("q", entry, mode)  # type: ignore[arg-type]
    assert service.wait(trace_id, 30) == ("partial" if mode == "eager" else "complete")
    return trace_id


def test_expand_failure_is_502_with_reason(client: TestClient, service: Service) -> None:
    trace_id = _failed_trace(service, "lazy")
    phase = client.get(f"/api/v1/traces/{trace_id}").json()["nodes"][0]
    r = client.post(f"/api/v1/traces/{trace_id}/nodes/{phase['id']}/expand")
    assert r.status_code == 502
    assert "rate limited" in r.json()["detail"]


def test_expand_eager_phase_without_steps_can_retry(client: TestClient, service: Service) -> None:
    from conftest import RoutedModel as Good

    trace_id = _failed_trace(service, "eager")
    nodes = client.get(f"/api/v1/traces/{trace_id}").json()["nodes"]
    assert all(n["level"] == 0 for n in nodes)
    assert any("steps unavailable" in w for w in nodes[0]["warnings"])
    service._model = Good()  # type: ignore[assignment]
    r = client.post(f"/api/v1/traces/{trace_id}/nodes/{nodes[0]['id']}/expand")
    assert r.status_code == 200
    assert {"accept", "queue"} <= {n["title"] for n in r.json()["nodes"]}
