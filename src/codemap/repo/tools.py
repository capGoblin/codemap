"""Read-only file tools for the agent. Tools return text and never raise."""

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from codemap.repo.ignore import RepoIgnore
from codemap.repo.sandbox import OutsideRepoError, resolve_inside

if TYPE_CHECKING:
    from codemap.repo.index import SymbolIndex

PAGE_LINES = 400
MAX_LINE_CHARS = 2000
BINARY_SNIFF_BYTES = 8192
FILE_ERROR_PREFIX = "error: "


def _safe[F: Callable[..., str]](fn: F) -> F:
    """Turn sandbox and file errors into `error: ...` text."""

    def wrapper(*args: object, **kwargs: object) -> str:
        try:
            return fn(*args, **kwargs)
        except OutsideRepoError as exc:
            return f"error: {exc}"
        except FileNotFoundError as exc:
            return f"error: not found: {exc.filename or exc}"
        except (IsADirectoryError, NotADirectoryError, PermissionError) as exc:
            return f"error: cannot read {exc.filename or exc}"
        except re.error as exc:
            return f"error: bad pattern: {exc}"

    return wrapper  # type: ignore[return-value]


def _is_binary(path: Path) -> bool:
    with path.open("rb") as handle:
        return b"\x00" in handle.read(BINARY_SNIFF_BYTES)


class RepoTools:
    def __init__(self, root: Path, ignore: RepoIgnore) -> None:
        self._root = root.resolve()
        self._ignore = ignore
        self.index: SymbolIndex | None = None

    def _rel(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix()

    def _resolve_visible(self, path: str, *, is_dir: bool = False) -> Path:
        """Resolve inside the root and refuse ignored paths."""
        real = resolve_inside(self._root, path)
        rel = self._rel(real)
        if rel != "." and self._ignore.is_ignored(rel + "/" if is_dir else rel):
            raise OutsideRepoError(f"path is ignored: {rel}")
        return real

    @_safe
    def list_dir(self, path: str = ".") -> str:
        directory = self._resolve_visible(path, is_dir=True)
        rows = []
        for entry in sorted(directory.iterdir(), key=lambda e: e.name):
            is_dir = entry.is_dir()
            rel = (directory / entry.name).relative_to(self._root).as_posix()
            if self._ignore.is_ignored(rel + "/" if is_dir else rel):
                continue
            rows.append(entry.name + "/" if is_dir else entry.name)
        return "\n".join(rows)

    @_safe
    def read_file(self, path: str, start: int = 1, end: int | None = None) -> str:
        file = self._resolve_visible(path)
        if _is_binary(file):
            return "binary file, not shown"
        start = max(start, 1)
        last = start + PAGE_LINES - 1
        if end is not None:
            last = min(last, end)
        out: list[str] = []
        more = 0
        with file.open(encoding="utf-8", errors="replace") as handle:
            for n, line in enumerate(handle, start=1):
                if n < start:
                    continue
                if n > last:
                    more += 1
                    continue
                out.append(f"{n}: {line.rstrip(chr(10)).rstrip(chr(13))[:MAX_LINE_CHARS]}")
        if more and (end is None or last < end):
            out.append(f"... {more} more lines; call read_file with start={last + 1}")
        return "\n".join(out)

    @_safe
    def file_text(self, path: str) -> str:
        """Raw text for code use only. Not a tool the agent calls."""
        return self._resolve_visible(path).read_text(errors="replace")

    def outline(self, path: str) -> str:
        if self.index is None:
            return "error: no symbol index"
        rows = [
            f"{path}:{s.start_line}-{s.end_line} {s.kind} {s.name} {s.signature}"
            for s in self.index.outline(path)
        ]
        return "\n".join(rows) or f"no symbols found in {path}"

    def find_definition(self, symbol: str) -> str:
        if self.index is None:
            return "error: no symbol index"
        rows = [
            f"{p}:{s.start_line}-{s.end_line} {s.kind} {s.name} {s.signature}"
            for p, s in self.index.find_definition(symbol)
        ]
        return "\n".join(rows) or f"no definition found for {symbol}"

    @_safe
    def search(self, pattern: str, glob: str | None = None, max_results: int = 50) -> str:
        re.compile(pattern)
        rows = (
            self._search_rg(pattern, glob) if shutil.which("rg") else self._search_py(pattern, glob)
        )
        found = []
        for row in rows:
            found.append(row)
            if len(found) >= max_results:
                break
        return "\n".join(found)

    def _row(self, rel: str, number: int, text: str) -> str:
        return f"{rel}:{number}: {text.rstrip()[:MAX_LINE_CHARS]}"

    def _search_rg(self, pattern: str, glob: str | None) -> Iterator[str]:
        cmd = ["rg", "--json", "--no-require-git", "-e", pattern]
        if glob:
            cmd += ["--glob", glob]
        cmd.append(".")
        proc = subprocess.run(cmd, cwd=self._root, capture_output=True, text=True, check=False)
        for raw in proc.stdout.splitlines():
            event = json.loads(raw)
            if event.get("type") != "match":
                continue
            data = event["data"]
            rel = Path(data["path"]["text"]).as_posix().removeprefix("./")
            if self._ignore.is_ignored(rel) or "text" not in data["lines"]:
                continue
            yield self._row(rel, data["line_number"], data["lines"]["text"])

    def _search_py(self, pattern: str, glob: str | None) -> Iterator[str]:
        regex = re.compile(pattern)
        for dirpath, dirnames, filenames in os.walk(self._root):
            base = Path(dirpath)
            dirnames[:] = sorted(
                d for d in dirnames if not self._ignore.is_ignored(self._rel(base / d) + "/")
            )
            for name in sorted(filenames):
                file = base / name
                rel = self._rel(file)
                if self._ignore.is_ignored(rel) or (glob and not file.match(glob)):
                    continue
                yield from self._grep_file(regex, rel)

    def _grep_file(self, regex: re.Pattern[str], rel: str) -> Iterator[str]:
        try:
            file = resolve_inside(self._root, rel)
            if _is_binary(file):
                return
            with file.open(encoding="utf-8", errors="replace") as handle:
                for n, line in enumerate(handle, start=1):
                    if regex.search(line):
                        yield self._row(rel, n, line)
        except (OutsideRepoError, OSError):
            return
