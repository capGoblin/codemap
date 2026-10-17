"""Anchor hashing and checks against the files on disk."""

import hashlib
import re

from codemap.domain.models import Anchor
from codemap.repo.sandbox import OutsideRepoError
from codemap.repo.tools import RepoTools


def hash_range(text: str, start: int, end: int) -> str:
    lines = [line.rstrip() for line in text.splitlines()[start - 1 : end]]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _range_text(tools: RepoTools, anchor: Anchor) -> tuple[str, str | None]:
    """Return (text of the range, error message)."""
    try:
        text = tools.file_text(anchor.file)
    except OutsideRepoError as exc:
        return "", str(exc)
    except OSError as exc:
        return "", f"cannot read {anchor.file}: {exc.strerror or exc}"
    lines = text.splitlines()
    if anchor.end_line > len(lines):
        return "", f"range {anchor.start_line}-{anchor.end_line} is past end of {anchor.file}"
    return text, None


def check_range(tools: RepoTools, anchor: Anchor) -> str | None:
    """Like `check_anchor`, but does not look for the symbol. Use it for sub-ranges."""
    return _range_text(tools, anchor)[1]


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
