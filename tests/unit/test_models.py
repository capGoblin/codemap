import pytest
from pydantic import ValidationError

from codemap.domain.models import Anchor, Effect, Node


def _anchor() -> Anchor:
    return Anchor(file="a.py", start_line=1, end_line=3, symbol="f")


def test_anchor_rejects_bad_range() -> None:
    with pytest.raises(ValidationError):
        Anchor(file="a.py", start_line=5, end_line=4, symbol="f")


def test_effect_roundtrip_json() -> None:
    effect = Effect(
        category="db",
        target="users",
        op="write",
        fields=("name", "email"),
        anchor=_anchor(),
    )
    assert Effect.model_validate_json(effect.model_dump_json()) == effect


def test_node_defaults() -> None:
    node = Node(
        id="n1",
        level=0,
        parent_id=None,
        order=0,
        title="t",
        does="d",
        input="i",
        output="o",
        boundary_reason="b",
        anchors=(_anchor(),),
    )
    assert node.stale is False
    assert node.warnings == ()
    hash(node)
