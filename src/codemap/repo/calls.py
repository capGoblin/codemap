"""Static call sites inside an anchored range, from tree-sitter with a regex fallback."""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import tree_sitter_language_pack as tslp

from codemap.domain.models import Anchor
from codemap.repo.index import EXT_LANGUAGE
from codemap.repo.sandbox import OutsideRepoError
from codemap.repo.tools import RepoTools

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

MAX_FULL_CHARS = 120
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_FALLBACK_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_DECLARATION = re.compile(r"\b(?:def|class|function|func|fn|sub|new|catch)\s*$")
_FIELDS = ("function", "method", "macro", "name")


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


KEYWORDS = _words(
    "and assert async await case catch class def defer elif else except for function go if "
    "in is lambda new not or return select sizeof switch throw typeof while with yield"
)
BUILTINS = _words(
    "Array Boolean Error Errorf Number Object Promise Sprintf String abs all any append "
    "assert assert_eq bool bytes callable cap close copy delete dict dir enumerate filter "
    "float format frozenset getattr hasattr hash id int isinstance issubclass iter len list "
    "make map max min new next open panic parseFloat parseInt print printf println range "
    "recover repr require reversed set setInterval setTimeout setattr sorted str sum super "
    "todo tuple type vars vec zip"
)
# Dotted prefixes of calls on the language runtime, never repo code.
DENIED_PREFIXES = ("console.", "Math.", "JSON.", "Object.", "Array.", "fmt.", "os.", "sys.")
# Method names so common that a unique repo definition proves nothing without import evidence.
COMMON_METHODS = _words(
    "add append clear close copy count decode encode endswith extend filter find format get "
    "index insert_many items join keys lower map pop push read remove replace sort split "
    "startswith strip then upper values write"
)


@dataclass(frozen=True)
class CallSite:
    name: str  # last identifier: `c` for `a.b.c()`
    line: int  # 1-based file line
    full: str = ""  # dotted text of the callee, for disambiguation


@lru_cache(maxsize=64)
def _tree(language: str, text: str) -> "Tree | None":
    try:
        return tslp.get_parser(language).parse(text.encode("utf-8"))  # type: ignore[arg-type]
    except Exception:  # grammar missing
        return None


def _text(node: "Node") -> str:
    return (node.text or b"").decode("utf-8", errors="replace")


def _is_call(node_type: str) -> bool:
    words = set(node_type.split("_"))
    return bool(words & {"call", "invocation"}) and "signature" not in words


def _callee_text(node: "Node") -> str:
    for field in _FIELDS:
        child = node.child_by_field_name(field)
        if child is None:
            continue
        text = _text(child)
        owner = node.child_by_field_name("object")
        if field == "name" and owner is not None:  # Java: object.name(...)
            text = f"{_text(owner)}.{text}"
        return " ".join(text.split())[:MAX_FULL_CHARS]
    return ""


def _site(full: str, line: int, denied: bool = True) -> CallSite | None:
    names = _IDENT.findall(full)
    if not names or "[" in full:  # a subscript call (`handlers[name](x)`) names no function
        return None
    name = names[-1]
    if name in KEYWORDS or (denied and name in BUILTINS and "." not in full):
        return None
    if full.startswith(DENIED_PREFIXES) or full.startswith("super()"):
        return None
    return CallSite(name, line, full)


def _tree_sites(tree: "Tree", start: int, end: int) -> list[CallSite]:
    found: list[CallSite] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        row = node.start_point.row + 1
        if node.end_point.row + 1 < start or row > end:
            continue
        if _is_call(node.type) and start <= row <= end and (site := _site(_callee_text(node), row)):
            found.append(site)
        stack.extend(node.children)
    return found


def _regex_sites(lines: list[str], first: int) -> list[CallSite]:
    found: list[CallSite] = []
    for number, line in enumerate(lines, start=first):
        for match in _FALLBACK_CALL.finditer(line):
            if _DECLARATION.search(line[: match.start()]):
                continue
            if site := _site(match.group(1), number):
                found.append(site)
    return found


def calls_in(tools: RepoTools, anchor: Anchor) -> list[CallSite]:
    """Call sites inside the anchored lines, in source order, one per (name, line)."""
    try:
        text = tools.file_text(anchor.file)
    except (OutsideRepoError, OSError):
        return []
    language = EXT_LANGUAGE.get(PurePosixPath(anchor.file).suffix.lower())
    tree = _tree(language, text) if language else None
    if tree is not None:
        sites = _tree_sites(tree, anchor.start_line, anchor.end_line)
    else:
        lines = text.splitlines()[anchor.start_line - 1 : anchor.end_line]
        sites = _regex_sites(lines, anchor.start_line)
    seen: set[tuple[str, int]] = set()
    out: list[CallSite] = []
    for site in sorted(sites, key=lambda s: s.line):
        if (site.name, site.line) not in seen:
            seen.add((site.name, site.line))
            out.append(site)
    return out
