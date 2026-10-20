#!/usr/bin/env python3
"""Check the citations and shape of a codemap trace markdown file. Standard library only.

  cite.py check TRACE.md [--repo ROOT]

A citation is a markdown link whose target ends in #L<start>[-L<end>]. The link title, when
present, is the symbol the range must contain: [`a.ts:10-40`](../a.ts#L10-L40 "handle").
The check is free: it reads files and runs no model.
"""

import argparse
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

CITE = re.compile(
    r"\]\((?P<href>[^)\s#]+)#L(?P<s>\d+)(?:-L(?P<e>\d+))?(?:\s+\"(?P<sym>[^\"]*)\")?\)"
)
PERMALINK = re.compile(r"^https?://[^/]+/[^/]+/[^/]+/blob/[^/]+/(?P<path>.+)$")
SECTIONS = ["Answer", "Trace card", "Map", "Stages"]
SECRET_NAMES = [
    ".env", ".env.*", "*.env", "*.pem", "*.key", "id_rsa*", "*.p12", "*.pfx", ".npmrc",
    ".pypirc", ".netrc", "credentials*", "*.tfvars",
]  # fmt: skip
SECRET_OK = {".env.example", ".env.sample", ".env.template"}
SECRET_DIRS = {".aws", ".ssh", ".git"}
SECRET_TEXT = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
CLAIM_LINE = {"Answer": r"^(\d+\.|-)\s+\S", "Stages": r"^\d+\.\s+\S"}


@dataclass(frozen=True)
class Cite:
    path: str  # repo-relative, posix
    start: int
    end: int
    symbol: str
    line: int  # line in the markdown file


def repo_root(md: Path, given: str | None) -> Path:
    if given:
        return Path(given).resolve()
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=md.parent, capture_output=True, text=True
    )
    return Path(out.stdout.strip()) if out.returncode == 0 else Path.cwd()


def to_repo_path(href: str, md: Path, root: Path) -> str | None:
    """Repo-relative path of a citation target, or None when it is not inside the repo."""
    href = unquote(href)
    if m := PERMALINK.match(href):
        return m["path"]
    if re.match(r"^[a-z]+://", href):
        return None
    for base in (md.parent, root):
        try:
            return (base / href).resolve().relative_to(root).as_posix()
        except ValueError:
            continue
    return None


def collect(text: str, md: Path, root: Path, errors: list[str]) -> list[Cite]:
    found: list[Cite] = []
    for n, line in enumerate(text.splitlines(), start=1):
        for m in CITE.finditer(line):
            path = to_repo_path(m["href"], md, root)
            start, end = int(m["s"]), int(m["e"] or m["s"])
            if path is None:
                errors.append(f"line {n}: citation target is not a repo file: {m['href']}")
            elif start > end:
                errors.append(f"line {n}: bad range L{start}-L{end}")
            else:
                found.append(Cite(path, start, end, m["sym"] or "", n))
    return found


def is_secret(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    if name in SECRET_OK:
        return False
    return bool(SECRET_DIRS & set(parts[:-1])) or any(
        fnmatch.fnmatch(name, p) for p in SECRET_NAMES
    )


def git_ignored(root: Path, path: str) -> bool:
    if not (root / ".git").exists():
        return False
    return subprocess.run(["git", "check-ignore", "-q", "--", path], cwd=root).returncode == 0


def read_range(root: Path, c: Cite) -> tuple[list[str] | None, str | None]:
    """The cited lines, or (None, reason)."""
    if is_secret(c.path):
        return None, "secret file: never cite it"
    if git_ignored(root, c.path):
        return None, "file is ignored by git: never cite it"
    file = (root / c.path).resolve()
    if not file.is_relative_to(root) or not file.is_file():
        return None, "file not found in the repo"
    lines = file.read_text(errors="replace").splitlines()
    if c.end > len(lines):
        return None, f"range ends past line {len(lines)}"
    return lines[c.start - 1 : c.end], None


def check_cites(cites: list[Cite], root: Path, errors: list[str]) -> int:
    ok = 0
    for c in cites:
        lines, why = read_range(root, c)
        where = f"line {c.line}: {c.path}:{c.start}-{c.end}"
        if lines is None:
            errors.append(f"{where}: {why}")
            continue
        name = c.symbol.rsplit(".", 1)[-1]
        if name and not re.search(rf"\b{re.escape(name)}\b", "\n".join(lines)):
            errors.append(f"{where}: symbol '{name}' not found in the range")
            continue
        ok += 1
    return ok


def lint(text: str, errors: list[str]) -> None:
    heads = [h for h in re.findall(r"^## (.+?)\s*$", text, flags=re.M)]
    if heads != SECTIONS:
        errors.append(f"sections must be exactly, in order: {', '.join(SECTIONS)} (found: {heads})")
    if "```mermaid" not in text:
        errors.append("no mermaid diagram in the Map section")
    for name, shape in CLAIM_LINE.items():
        sec = re.search(rf"^## {name}\s*$(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
        for line in sec.group(1).splitlines() if sec else []:
            if re.match(shape, line) and not CITE.search(line):
                errors.append(f"uncited claim in {name}: {line.strip()[:70]}")
    for rx in SECRET_TEXT:
        if rx.search(text):
            errors.append(f"text looks like a secret ({rx.pattern[:20]}...): remove it")


def cmd_check(md: Path, root: Path) -> int:
    text = md.read_text()
    errors: list[str] = []
    cites = collect(text, md, root, errors)
    ok = check_cites(cites, root, errors)
    lint(text, errors)
    for e in errors:
        print(f"FAIL  {e}")
    print(f"{len(cites)} citations, {ok} ok, {len(errors)} problems")
    return 1 if errors else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("command", choices=["check"])
    ap.add_argument("trace", type=Path)
    ap.add_argument("--repo", help="repo root (default: the git root of the trace file)")
    args = ap.parse_args()
    md = args.trace.resolve()
    return cmd_check(md, repo_root(md, args.repo))


if __name__ == "__main__":
    sys.exit(main())
