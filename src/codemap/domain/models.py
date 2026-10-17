from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

EffectCategory = Literal[
    "db", "object_store", "queue", "cache", "file", "workflow", "http", "other"
]
EffectOp = Literal["read", "write"]
EdgeKind = Literal["call", "async", "error", "branch"]
HopType = Literal["direct", "indirect"]
Verdict = Literal["code_checked", "confirmed", "unsure", "rejected"]
TraceStatus = Literal["running", "complete", "partial", "failed"]
TraceMode = Literal["eager", "lazy"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Anchor(_Frozen):
    file: str
    start_line: int
    end_line: int
    symbol: str
    content_hash: str = ""

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if not 1 <= self.start_line <= self.end_line:
            raise ValueError("anchor needs 1 <= start_line <= end_line")
        return self


class Effect(_Frozen):
    category: EffectCategory
    target: str
    op: EffectOp
    fields: tuple[str, ...] = ()
    anchor: Anchor


class Hop(_Frozen):
    id: str
    caller: Anchor
    callee: Anchor
    kind: EdgeKind
    hop_type: HopType
    wiring: Anchor | None = None
    verdict: Verdict | None = None
    evidence: str = ""


class Bridge(_Frozen):
    """A join between two path components that have no recorded code link."""

    from_anchor: Anchor
    to_anchor: Anchor


class Node(_Frozen):
    id: str
    level: int
    parent_id: str | None
    order: int
    title: str
    summary: str = ""
    does: str
    input: str
    output: str
    boundary_reason: str
    anchors: tuple[Anchor, ...]
    effects: tuple[Effect, ...] = ()
    parallel_group: int | None = None
    stale: bool = False
    warnings: tuple[str, ...] = ()


class Edge(_Frozen):
    source_id: str
    target_id: str
    kind: EdgeKind


class Trace(_Frozen):
    id: str
    question: str
    entry: Anchor
    commit_sha: str | None
    dirty: bool
    status: TraceStatus
    mode: TraceMode
    created_at: datetime
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class EntryCandidate(_Frozen):
    anchor: Anchor
    label: str
    reason: str


class TraceGraph(_Frozen):
    trace: Trace
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]


class FunctionDetail(_Frozen):
    anchor: Anchor
    signature: str
    code: str
    calls: tuple[str, ...]


class VerifierResult(_Frozen):
    verdict: Verdict
    evidence: str
    suggested_callee: Anchor | None = None


class ExplainStep(_Frozen):
    text: str
    lines: tuple[int, int]
    file: str


class IoSide(_Frozen):
    type: str = ""
    fields: tuple[str, ...] = ()
    node_id: str | None = None


class NodeExplain(_Frozen):
    steps: tuple[ExplainStep, ...] = ()
    input: IoSide = IoSide()
    output: IoSide = IoSide()


class CallLink(_Frozen):
    symbol: str
    node_id: str | None = None


class NodeDetail(_Frozen):
    explain: NodeExplain | None = None
    explain_error: str | None = None
    functions: tuple[FunctionDetail, ...] = ()
    calls: tuple[CallLink, ...] = ()
    effects: tuple[Effect, ...] = ()
