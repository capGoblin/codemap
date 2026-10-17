"""Helpers shared by every submit schema."""

from typing import Any

from pydantic import field_validator


def _unwrap_item(value: Any) -> Any:
    """MiniMax sometimes sends a list as {"item": x} or {"item": [x, y]}. Unwrap it."""
    if isinstance(value, dict) and set(value) == {"item"}:
        inner = value["item"]
        return inner if isinstance(inner, list) else [inner]
    return value


def tolerant_list(*fields: str) -> Any:
    """A before-validator for list fields. Use as `_unwrap = tolerant_list("a", "b")`."""
    return field_validator(*fields, mode="before")(_unwrap_item)
