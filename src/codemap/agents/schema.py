"""Helpers shared by every submit schema."""

from typing import Any

from pydantic import field_validator


def _unwrap_item(value: Any) -> Any:
    """Some models wrap a list as {"item": x} or {"item": [x, y]}. Unwrap it."""
    if isinstance(value, dict) and set(value) == {"item"}:
        inner = value["item"]
        return inner if isinstance(inner, list) else [inner]
    return value


def unwrap_items(value: Any) -> Any:
    """Recursively replace {"item": x} wrappers (any depth) with lists."""
    if isinstance(value, list):
        return [unwrap_items(v) for v in value]
    if isinstance(value, dict):
        out = {k: unwrap_items(v) for k, v in value.items()}
        return _unwrap_item(out)
    return value


def tolerant_list(*fields: str) -> Any:
    """A before-validator for list fields. Use as `_unwrap = tolerant_list("a", "b")`."""
    return field_validator(*fields, mode="before")(_unwrap_item)
