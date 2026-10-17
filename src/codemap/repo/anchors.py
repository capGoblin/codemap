"""Anchor hashing and checks against the files on disk."""

import hashlib
import re

from codemap.domain.models import Anchor
from codemap.repo.tools import FILE_ERROR_PREFIX, RepoTools


def hash_range(text: str, start: int, end: int) -> str:
    lines = [line.rstrip() for line in text.splitlines()[start - 1 : end]]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _range_text(tools: RepoTools, anchor: Anchor) -> tuple[str, str | None]:
    """Return (text of the range, error message)."""
    text = tools.file_text(anchor.file)
    if text.startswith(FILE_ERROR_PREFIX):
        return "", text.removeprefix(FILE_ERROR_PREFIX)
    lines = text.splitlines()
    if anchor.end_line > len(lines):
        return "", f"range {anchor.start_line}-{anchor.end_line} is past end of {anchor.file}"
    return text, None


def check_anchor(tools: RepoTools, anchor: Anchor) -> str | None:
    text, error = _range_text(tools, anchor)
    if error:
        return error
    name = anchor.symbol.rsplit(".", 1)[-1]
    body = "\n".join(text.splitlines()[anchor.start_line - 1 : anchor.end_line])
    if name and not re.search(rf"\b{re.escape(name)}\b", body):
        return f"symbol {name} not found in {anchor.file}:{anchor.start_line}-{anchor.end_line}"
    return None


def with_hash(tools: RepoTools, anchor: Anchor) -> Anchor:
    text, _ = _range_text(tools, anchor)
    return anchor.model_copy(
        update={"content_hash": hash_range(text, anchor.start_line, anchor.end_line)}
    )


def is_stale(tools: RepoTools, anchor: Anchor) -> bool:
    text, error = _range_text(tools, anchor)
    return (
        bool(error) or hash_range(text, anchor.start_line, anchor.end_line) != anchor.content_hash
    )
