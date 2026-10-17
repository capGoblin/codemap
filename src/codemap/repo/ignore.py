"""Paths the agent never sees: built-in defaults plus the repo's root .gitignore."""

from pathlib import Path

import pathspec

DEFAULT_PATTERNS = [
    ".git/",
    ".codemap/",
    "node_modules/",
    "vendor/",
    ".venv/",
    "venv/",
    "dist/",
    "build/",
    "__pycache__/",
    "*.lock",
    "*.min.js",
    "*.map",
]


class RepoIgnore:
    def __init__(self, root: Path) -> None:
        patterns = list(DEFAULT_PATTERNS)
        gitignore = root / ".gitignore"
        if gitignore.is_file():
            patterns += gitignore.read_text(errors="replace").splitlines()
        self._spec = pathspec.PathSpec.from_lines("gitignore", patterns)

    def is_ignored(self, rel: str) -> bool:
        """`rel` is relative to the root. End it with `/` for a directory."""
        return self._spec.match_file(rel)
