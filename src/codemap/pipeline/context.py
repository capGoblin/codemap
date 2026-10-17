"""Pipeline context, the read-only tool set shared by every agent, and prompt loading."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from codemap.agents.limits import Budget, Limits
from codemap.agents.loop import Tool
from codemap.agents.model import AnthropicModel, ChatModel
from codemap.agents.recording import CachedModel
from codemap.domain.events import Event
from codemap.repo.ignore import RepoIgnore
from codemap.repo.index import SymbolIndex
from codemap.repo.tools import RepoTools
from codemap.settings import Settings
from codemap.store.caches import SqliteCallCache, SqliteSymbolCache, SqliteVerdictCache
from codemap.store.db import open_db
from codemap.store.traces import TraceStore


@dataclass
class TraceContext:
    """Everything one trace run shares.

    `emit` writes through `store`. The store connection belongs to the pipeline thread.
    Split workers on other threads must not call `emit`. They share the store connection
    only through the caches, and its lock makes that safe.

    `cancel` is shared with `budget`, so the tool loop stops before its next model call.
    """

    root: Path
    tools: RepoTools
    model: ChatModel
    budget: Budget
    store: TraceStore
    verdicts: SqliteVerdictCache
    settings: Settings
    emit: Callable[[Event], object]
    trace_id: str
    cancel: threading.Event = field(default_factory=threading.Event)


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


def read_tools(tools: RepoTools) -> list[Tool]:
    """The five read-only tools every agent gets."""
    text = {"type": "string"}
    number = {"type": "integer"}
    return [
        Tool(
            "list_dir",
            "List a directory. Directories end with '/'. Ignored paths are hidden.",
            _schema({"path": text}, []),
            lambda a: tools.list_dir(a.get("path", ".")),
        ),
        Tool(
            "read_file",
            "Read numbered lines of a file, one page (400 lines) at most. "
            "If more lines remain, the result gives the next start.",
            _schema({"path": text, "start": number, "end": number}, ["path"]),
            lambda a: tools.read_file(a["path"], a.get("start", 1), a.get("end")),
        ),
        Tool(
            "search",
            "Regex search over the repo. Rows are path:line: text. Optional glob filter.",
            _schema({"pattern": text, "glob": text, "max_results": number}, ["pattern"]),
            lambda a: tools.search(a["pattern"], a.get("glob"), a.get("max_results", 50)),
        ),
        Tool(
            "find_definition",
            "Find where a symbol is defined. Rows are path:start-end kind name signature.",
            _schema({"symbol": text}, ["symbol"]),
            lambda a: tools.find_definition(a["symbol"]),
        ),
        Tool(
            "outline",
            "List the symbols of one file with line ranges and signatures.",
            _schema({"path": text}, ["path"]),
            lambda a: tools.outline(a["path"]),
        ),
    ]


def prompt(name: str) -> str:
    return (resources.files("codemap") / "prompts" / f"{name}.md").read_text(encoding="utf-8")


def build_context(
    root: Path,
    settings: Settings,
    trace_id: str,
    model: ChatModel | None = None,
    db_path: Path | None = None,
    cancel: threading.Event | None = None,
) -> TraceContext:
    conn = open_db(db_path or root / ".codemap" / "codemap.db")
    store = TraceStore(conn)
    limits = Limits(
        wall_seconds=settings.max_wall_seconds,
        max_tokens=settings.max_tokens_total,
        max_cost_usd=settings.max_cost_usd,
        max_tool_calls=settings.max_tool_calls,
    )
    cancel = cancel or threading.Event()
    budget = Budget(limits, settings.price_in_per_mtok, settings.price_out_per_mtok, cancel=cancel)
    inner = model or AnthropicModel(
        settings.anthropic_base_url,
        settings.anthropic_auth_token.get_secret_value(),
        settings.model,
        settings.request_timeout_s,
    )
    tools = RepoTools(root, RepoIgnore(root))
    tools.index = SymbolIndex(tools, SqliteSymbolCache(conn))
    return TraceContext(
        root=root,
        tools=tools,
        model=CachedModel(inner, SqliteCallCache(conn)),
        budget=budget,
        store=store,
        verdicts=SqliteVerdictCache(conn),
        settings=settings,
        emit=store.add_event,
        trace_id=trace_id,
        cancel=cancel,
    )
