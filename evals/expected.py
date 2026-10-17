"""Hand-written expected traces. Stored as JSON, one file per target repo."""

from pathlib import Path

from pydantic import BaseModel, Field

from codemap.domain.models import Anchor, EffectCategory, EffectOp


class ExpectedEffect(BaseModel):
    category: EffectCategory
    target: str
    op: EffectOp


class ExpectedNode(BaseModel):
    title: str
    spans: list[Anchor]
    steps: list["ExpectedNode"] = Field(default_factory=list)


class ExpectedTrace(BaseModel):
    repo: str
    commit: str
    question: str
    entry: Anchor
    phases: list[ExpectedNode]
    effects: list[ExpectedEffect]


def _spans(nodes: list[ExpectedNode]):
    for n in nodes:
        yield from n.spans
        yield from _spans(n.steps)


def load_expected(path: Path, repo_root: Path) -> ExpectedTrace:
    """Load an expected file. Fail at once if a span points to a missing file."""
    exp = ExpectedTrace.model_validate_json(path.read_text())
    for span in [exp.entry, *_spans(exp.phases)]:
        if not (repo_root / span.file).is_file():
            raise ValueError(f"expected file {path.name}: missing path {span.file}")
    return exp
