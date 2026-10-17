"""Path sandbox: every agent-supplied path must resolve inside the repo root."""

import os
from pathlib import Path


class OutsideRepoError(Exception):
    """A path points outside the repo root."""


def resolve_inside(root: Path, rel: str) -> Path:
    """Return the real path of `rel` under `root`, or raise OutsideRepoError.

    Rejects absolute paths, `..` escapes and symlinks whose target leaves `root`.
    """
    if "\x00" in rel or Path(rel).is_absolute():
        raise OutsideRepoError(f"path is not allowed: {rel!r}")
    real_root = root.resolve()
    real = (real_root / rel).resolve()
    if not real.is_relative_to(real_root):
        raise OutsideRepoError(f"path is outside the repo: {rel!r}")
    return real


def canonical_rel(root: Path, rel: str) -> str:
    """Spell each part of `rel` as it is on disk, so case variants cannot dodge an ignore rule.

    A part is renamed only when exactly one entry matches it ignoring case. Parts that do not
    exist stay as given. `rel` must already be inside `root`.
    """
    current = root
    parts: list[str] = []
    for part in Path(rel).parts:
        if part in (".", ""):
            continue
        name = part
        try:
            names = os.listdir(current)
        except OSError:
            names = []
        if part not in names:
            same = [n for n in names if n.lower() == part.lower()]
            if len(same) == 1:
                name = same[0]
        parts.append(name)
        current = current / name
    return "/".join(parts) or "."
