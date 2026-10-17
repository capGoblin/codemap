"""Paths the agent never sees (spec 7).

Four sources are combined: built-in defaults, a deny list of secret files that applies even
when git does not ignore them, every `.gitignore` under the root (scoped to its directory),
and, for a git repo, what git itself reports as ignored. Git covers `.git/info/exclude` and
the global excludes file.
"""

import os
import subprocess
from pathlib import Path
from typing import Any

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

SECRET_PATTERNS = [
    ".env",
    ".env.*",
    "*.env",
    "!.env.example",
    "!.env.sample",
    "!.env.template",
    "*.pem",
    "*.key",
    "id_rsa*",
    "*.p12",
    "*.pfx",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "credentials*",
    "secrets*.json",
    "secrets*.yaml",
    "secrets*.yml",
    "secrets*.toml",
    "*.kdbx",
    ".aws/",
    ".ssh/",
    ".gnupg/",
]

GIT_TIMEOUT_S = 60


def _git_ignored(root: Path) -> list[str]:
    """Untracked paths git ignores. A directory ends with `/`. Empty when git cannot say."""
    cmd = ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"]
    try:
        done = subprocess.run(
            cmd, cwd=root, capture_output=True, text=True, check=True, timeout=GIT_TIMEOUT_S
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [p for p in done.stdout.split("\0") if p]


class RepoIgnore:
    def __init__(self, root: Path) -> None:
        self._base = pathspec.PathSpec.from_lines("gitignore", DEFAULT_PATTERNS + SECRET_PATTERNS)
        self._nested = self._load_gitignores(root)
        listed = _git_ignored(root) if (root / ".git").exists() else []
        self._git_dirs = {p.rstrip("/") for p in listed if p.endswith("/")}
        self._git_files = {p for p in listed if not p.endswith("/")}

    def _load_gitignores(self, root: Path) -> dict[str, pathspec.PathSpec[Any]]:
        """One spec per directory that holds a .gitignore. Keys are paths from the root."""
        found: dict[str, pathspec.PathSpec[Any]] = {}
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = Path(dirpath).relative_to(root).as_posix()
            prefix = "" if rel_dir == "." else rel_dir + "/"
            dirnames[:] = [d for d in dirnames if not self._base.match_file(f"{prefix}{d}/")]
            if ".gitignore" in filenames:
                lines = (Path(dirpath) / ".gitignore").read_text(errors="replace").splitlines()
                found["" if rel_dir == "." else rel_dir] = pathspec.PathSpec.from_lines(
                    "gitignore", lines
                )
        return found

    def is_ignored(self, rel: str) -> bool:
        """`rel` is relative to the root. End it with `/` for a directory."""
        if self._base.match_file(rel):
            return True
        parts = rel.rstrip("/").split("/")
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            if prefix in self._git_dirs or (i == len(parts) and prefix in self._git_files):
                return True
        for scope, spec in self._nested.items():
            if scope and not rel.startswith(scope + "/"):
                continue
            if spec.match_file(rel[len(scope) + 1 :] if scope else rel):
                return True
        return False
