"""Symbol index: tree-sitter outlines with a regex fallback."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Protocol

import tree_sitter_language_pack as tslp

from codemap.repo.tools import FILE_ERROR_PREFIX

if TYPE_CHECKING:
    from tree_sitter import Node

    from codemap.repo.tools import RepoTools

SIGNATURE_CHARS = 200
MAX_HIT_ROWS = 200

EXT_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".scala": "scala",
    ".ex": "elixir",
    ".exs": "elixir",
    ".lua": "lua",
    ".sh": "bash",
    ".bash": "bash",
}

# Node types are split on "_"; a type counts when it has a wanted word and no skipped word.
_WANTED_WORDS = {"function", "method", "class", "def", "impl", "definition"}
_SKIPPED_WORDS = {"call", "parameter", "type", "expression", "lambda"}
_FALLBACK = re.compile(r"^\s*(?:def|defp|class|function|func|fn|sub)\s+([A-Za-z_$][\w$.:]*)")


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str


class SymbolCache(Protocol):
    def get(self, content_hash: str) -> list[Symbol] | None: ...

    def put(self, content_hash: str, symbols: list[Symbol]) -> None: ...


class MemorySymbolCache:
    def __init__(self) -> None:
        self._items: dict[str, list[Symbol]] = {}

    def get(self, content_hash: str) -> list[Symbol] | None:
        return self._items.get(content_hash)

    def put(self, content_hash: str, symbols: list[Symbol]) -> None:
        self._items[content_hash] = symbols


def _is_definition(node_type: str) -> bool:
    words = set(node_type.split("_"))
    return bool(words & _WANTED_WORDS) and not words & _SKIPPED_WORDS


def _name_of(node: "Node") -> str | None:
    child = node.child_by_field_name("name")
    if child is None and "impl" in node.type.split("_"):
        child = node.child_by_field_name("type")
    return child.text.decode("utf-8", errors="replace") if child and child.text else None


def _signature(node: "Node") -> str:
    text = (node.text or b"").decode("utf-8", errors="replace")
    return text.split("\n", 1)[0].strip()[:SIGNATURE_CHARS]


def _walk(root: "Node") -> list[Symbol]:
    found: list[Symbol] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if _is_definition(node.type) and (name := _name_of(node)):
            found.append(
                Symbol(
                    name,
                    node.type,
                    node.start_point.row + 1,
                    node.end_point.row + 1,
                    _signature(node),
                )
            )
        stack.extend(node.children)
    return sorted(found, key=lambda s: (s.start_line, s.end_line))


def _regex_outline(text: str) -> list[Symbol]:
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        if match := _FALLBACK.match(line):
            found.append(
                Symbol(match.group(1), "regex", number, number, line.strip()[:SIGNATURE_CHARS])
            )
    return found


def _parse(language: str, text: str) -> list[Symbol] | None:
    """Symbols from tree-sitter, or None when the grammar is not available."""
    try:
        tree = tslp.get_parser(language).parse(text.encode("utf-8"))
    except Exception:  # grammar missing or download failed
        return None
    return _walk(tree.root_node)


class SymbolIndex:
    def __init__(self, tools: "RepoTools", cache: SymbolCache) -> None:
        self._tools = tools
        self._cache = cache

    def outline(self, path: str) -> list[Symbol]:
        text = self._tools.file_text(path)
        if text.startswith(FILE_ERROR_PREFIX):
            return []
        key = hashlib.sha256(f"{path}\0{text}".encode()).hexdigest()
        if (cached := self._cache.get(key)) is not None:
            return cached
        language = EXT_LANGUAGE.get(PurePosixPath(path).suffix.lower())
        symbols = _parse(language, text) if language else None
        if not symbols:
            symbols = _regex_outline(text)
        self._cache.put(key, symbols)
        return symbols

    def find_definition(self, symbol: str) -> list[tuple[str, Symbol]]:
        name = symbol.rsplit(".", 1)[-1]
        if not name:
            return []
        hits = self._tools.search(rf"\b{re.escape(name)}\b", max_results=MAX_HIT_ROWS)
        paths = dict.fromkeys(
            m.group(1) for r in hits.splitlines() if (m := re.match(r"(.+?):\d+: ", r))
        )
        return [(p, s) for p in paths for s in self.outline(p) if s.name.rsplit(".", 1)[-1] == name]
