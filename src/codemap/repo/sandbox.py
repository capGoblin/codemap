"""Path sandbox: every agent-supplied path must resolve inside the repo root."""

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
