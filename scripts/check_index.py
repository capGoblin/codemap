"""Run the symbol index over a repo to check for native crashes.

Usage: uv run python scripts/check_index.py REPO [--ext .py,.ts,.tsx] [--limit N] [--passes 3]
Exit code 0 means every pass finished. A native crash gives a non-zero code.
"""

import argparse
import faulthandler
from pathlib import Path

from codemap.repo.ignore import RepoIgnore
from codemap.repo.index import MemorySymbolCache, SymbolIndex
from codemap.repo.tools import RepoTools

SKIPPED_DIRS = {".venv", ".codemap", "node_modules", ".git"}


def main() -> None:
    faulthandler.enable()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", type=Path)
    ap.add_argument("--ext", default=".py")
    ap.add_argument("--limit", type=int, default=0, help="max files (0 = all)")
    ap.add_argument("--passes", type=int, default=3)
    args = ap.parse_args()
    root: Path = args.repo
    exts = tuple(args.ext.split(","))
    tools = RepoTools(root, RepoIgnore(root))
    index = SymbolIndex(tools, MemorySymbolCache())
    tools.index = index
    files = sorted(
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.suffix in exts and not SKIPPED_DIRS & set(p.parts)
    )
    if args.limit:
        files = files[: args.limit]
    for n in range(args.passes):
        symbols = sum(len(index.outline(f)) for f in files)
        print(f"pass {n}: {len(files)} files, {symbols} symbols", flush=True)
        index._cache = MemorySymbolCache()  # force a re-parse on the next pass


if __name__ == "__main__":
    main()
