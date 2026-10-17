"""The one entry point for the CLI and the server (spec 3).

The Service keeps one reader connection for its own calls. Each trace thread and each
`expand_node` call builds its own context, and so its own connection.
"""

import logging
import subprocess
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from codemap.agents.limits import LimitReached
from codemap.agents.model import AnthropicModel, ChatModel, ModelError
from codemap.domain.events import Event
from codemap.domain.models import (
    EntryCandidate,
    Hop,
    Node,
    NodeDetail,
    NodeExplain,
    Trace,
    TraceGraph,
    TraceMode,
    TraceStatus,
)
from codemap.pipeline.context import TraceContext, build_context
from codemap.pipeline.detail import build_detail
from codemap.pipeline.explain import ALL_LEVELS, ExplainError, call_links, explain_node
from codemap.pipeline.resolve import ResolveLimitError, resolve_entry
from codemap.pipeline.run import ExpandError, expand_node, run_trace
from codemap.repo.anchors import is_stale
from codemap.repo.ignore import RepoIgnore
from codemap.repo.index import SymbolIndex
from codemap.repo.tools import RepoTools
from codemap.settings import Settings
from codemap.store.caches import SqliteSymbolCache
from codemap.store.db import open_db
from codemap.store.traces import TraceStore

__all__ = ["ExpandError", "ModelError", "ResolveLimitError", "Service"]

log = logging.getLogger(__name__)
_EXCLUDE_LINE = ".codemap/"


def _git(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout


def _exclude_codemap(root: Path) -> None:
    if not (root / ".git").is_dir():
        return
    exclude = root / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if _EXCLUDE_LINE in text.splitlines():
        return
    prefix = "" if not text or text.endswith("\n") else "\n"
    exclude.write_text(f"{text}{prefix}{_EXCLUDE_LINE}\n", encoding="utf-8")


class Service:
    def __init__(self, root: Path, settings: Settings, model: ChatModel | None = None) -> None:
        self.root = root
        self.settings = settings
        self._model = model
        conn = open_db(root / ".codemap" / "codemap.db")
        self._store = TraceStore(conn)
        self._tools = RepoTools(root, RepoIgnore(root))
        self._tools.index = SymbolIndex(self._tools, SqliteSymbolCache(conn))
        self._threads: dict[str, threading.Thread] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._store.mark_running_partial()
        _exclude_codemap(root)

    def resolve(self, question: str) -> list[EntryCandidate]:
        """Raises ModelError when the model call fails, ResolveLimitError on a run limit."""
        ctx = build_context(self.root, self.settings, "resolve", self._model)
        return resolve_entry(ctx, question)

    def _uncached_model(self) -> ChatModel:
        return self._model or AnthropicModel(
            self.settings.anthropic_base_url,
            self.settings.anthropic_auth_token.get_secret_value(),
            self.settings.model,
            self.settings.request_timeout_s,
        )

    def check_model(self) -> str | None:
        """Send one tiny request, not cached. Return an error message, or None when it works."""
        try:
            self._uncached_model().respond(
                system="Reply with ok.",
                messages=[{"role": "user", "content": "ping"}],
                tools=[],
                max_tokens=16,
            )
        except Exception as exc:
            token = self.settings.anthropic_auth_token.get_secret_value()
            message = str(exc) or type(exc).__name__
            return message.replace(token, "***") if token else message
        return None

    def start_trace(self, question: str, entry: EntryCandidate, mode: TraceMode) -> str:
        trace_id = uuid.uuid4().hex
        sha = _git(self.root, "rev-parse", "HEAD")
        status = _git(self.root, "status", "--porcelain")
        self._store.create_trace(
            Trace(
                id=trace_id,
                question=question,
                entry=entry.anchor,
                commit_sha=sha.strip() if sha else None,
                dirty=bool(status and status.strip()),
                status="running",
                mode=mode,
                created_at=datetime.now(UTC),
                model=self.settings.model,
            )
        )
        thread = threading.Thread(
            target=self._run, args=(trace_id, question, entry, mode), daemon=True
        )
        self._cancels[trace_id] = threading.Event()
        self._threads[trace_id] = thread
        thread.start()
        return trace_id

    def _run(self, trace_id: str, question: str, entry: EntryCandidate, mode: TraceMode) -> None:
        ctx = None
        try:
            ctx = build_context(
                self.root, self.settings, trace_id, self._model, cancel=self._cancels[trace_id]
            )
            run_trace(ctx, question, entry.anchor, mode)
        except Exception as exc:
            log.exception("trace %s failed", trace_id)
            self._fail(trace_id, exc, ctx)

    def _fail(self, trace_id: str, exc: Exception, ctx: TraceContext | None = None) -> None:
        cancelled = self._cancels[trace_id].is_set()
        has_work = bool(self._store.get_hops(trace_id))
        status: TraceStatus = "partial" if has_work or cancelled else "failed"
        if ctx is not None:
            budget = ctx.budget
            self._store.set_totals(
                trace_id, budget.input_tokens, budget.output_tokens, budget.cost_usd
            )
        self._store.set_status(trace_id, status)
        message = str(exc) or type(exc).__name__
        self._store.add_event(
            Event(
                trace_id=trace_id,
                kind="finished",
                message=message,
                data={"status": status},
                at=datetime.now(UTC),
            )
        )

    def cancel(self, trace_id: str) -> None:
        """Stop a running trace. The tool loop sees the event before its next model call.

        The trace ends as `partial` with its work kept.
        """
        thread, event = self._threads.get(trace_id), self._cancels.get(trace_id)
        if thread is None or event is None or not thread.is_alive():
            return
        event.set()
        self._store.set_status(trace_id, "partial")

    def wait(self, trace_id: str, timeout: float | None = None) -> TraceStatus:
        thread = self._threads.get(trace_id)
        if thread is not None:
            thread.join(timeout)
        trace = self._store.get_trace(trace_id)
        if trace is None:
            raise KeyError(trace_id)
        return trace.status

    def events(self, trace_id: str, after_id: int = 0) -> list[tuple[int, Event]]:
        return self._store.events_after(trace_id, after_id)

    def list_traces(self) -> list[Trace]:
        return self._store.list_traces()

    def get_graph(self, trace_id: str, depth: int = 1) -> TraceGraph:
        graph = self._store.get_graph(trace_id, depth)
        stale = {n.id for n in graph.nodes if any(is_stale(self._tools, a) for a in n.anchors)}
        self._store.set_stale(trace_id, stale)
        return self._store.get_graph(trace_id, depth)

    def expand_node(self, trace_id: str, node_id: str) -> TraceGraph:
        """Build the children of any node on the caller's thread. Raises KeyError if unknown.

        Returns the graph down to the level of the new children.
        """
        node = self._store.get_node(trace_id, node_id)
        if node is None:
            raise KeyError(node_id)
        ctx = build_context(self.root, self.settings, trace_id, self._model)
        expand_node(ctx, node_id)
        return self.get_graph(trace_id, depth=node.level + 1)

    def get_detail(self, trace_id: str, node_id: str) -> NodeDetail:
        """Code, calls and effects always; the explanation is made on first call, then stored."""
        return self._detail(trace_id, node_id, force=False)

    def regenerate_detail(self, trace_id: str, node_id: str) -> NodeDetail:
        """Make the explanation again. A stored one stays until the new one succeeds."""
        return self._detail(trace_id, node_id, force=True)

    def _detail(self, trace_id: str, node_id: str, force: bool) -> NodeDetail:
        node = self._store.get_node(trace_id, node_id)
        if node is None:
            raise KeyError(node_id)
        hops = self._store.get_hops(trace_id)
        explain = None if force else self._store.get_explain(trace_id, node_id)
        error = None
        if explain is None:
            explain, error = self._explain(trace_id, node, hops, force)
        if explain is None:
            explain = self._store.get_explain(trace_id, node_id)
        nodes = self._store.get_graph(trace_id, ALL_LEVELS).nodes
        return NodeDetail(
            explain=explain,
            explain_error=error,
            functions=tuple(build_detail(self._tools, node, hops)),
            calls=call_links(node, nodes, hops),
            effects=node.effects,
        )

    def _explain(
        self, trace_id: str, node: Node, hops: list[Hop], force: bool
    ) -> tuple[NodeExplain | None, str | None]:
        try:
            ctx = build_context(self.root, self.settings, trace_id, self._model)
            if force:
                ctx.model = self._uncached_model()  # a retry must reach the model
            explain = explain_node(ctx, node, hops, node.effects)
        except (ModelError, LimitReached, ExplainError) as exc:
            return None, str(exc) or type(exc).__name__
        self._store.save_explain(trace_id, node.id, explain)
        return explain, None
