"""Score the independent verifier on real and planted-fake indirect hops."""

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from codemap.agents.model import ChatModel
from codemap.agents.providers import make_model
from codemap.agents.recording import CachedModel, JsonFileCache, ReplayOnlyModel
from codemap.domain.models import Anchor, EdgeKind, Hop
from codemap.pipeline.context import TraceContext, build_context
from codemap.pipeline.verify import verify_hop
from codemap.repo.anchors import with_hash
from codemap.settings import Settings, load_settings

ROOT = Path(__file__).resolve().parents[1]
RECORDING = Path(__file__).parent / "recordings" / "verifier.json"
PASS_BAR = 0.02
REPOS = {"codemap": ROOT}


class HopEntry(BaseModel):
    repo: str
    caller: Anchor
    callee: Anchor
    kind: EdgeKind
    wiring: Anchor | None
    real: bool
    category: str = ""
    note: str = ""


@dataclass(frozen=True)
class VerifierScore:
    real_rejected: int
    real_total: int
    fake_caught: int
    fake_total: int
    unsure: int
    rejected_real: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.real_total > 0 and self.real_rejected / self.real_total <= PASS_BAR


def load_hops(path: Path) -> list[HopEntry]:
    return [HopEntry.model_validate(raw) for raw in json.loads(path.read_text())]


def _hashed(entry: HopEntry, index: int, ctx: TraceContext) -> Hop:
    return Hop(
        id=f"eval-{index}",
        caller=with_hash(ctx.tools, entry.caller),
        callee=with_hash(ctx.tools, entry.callee),
        kind=entry.kind,
        hop_type="indirect",
        wiring=with_hash(ctx.tools, entry.wiring) if entry.wiring else None,
    )


def _model(settings: Settings, record: bool, recording: Path) -> ChatModel:
    cache = JsonFileCache(recording)
    if not record:
        return ReplayOnlyModel(cache, settings.model_id)
    return CachedModel(make_model(settings), cache, settings.model_id)


def run_verifier(
    path: Path,
    *,
    record: bool,
    repos: dict[str, Path] | None = None,
    settings: Settings | None = None,
    model: ChatModel | None = None,
    recording: Path = RECORDING,
) -> VerifierScore:
    """Verify each entry once. The verdict cache lives in a fresh temp DB, never in the repo."""
    roots = repos or REPOS
    settings = settings or load_settings()
    model = model or _model(settings, record, recording)
    entries = load_hops(path)
    real_rejected = fake_caught = unsure = 0
    rejected_real: list[str] = []
    for repo in dict.fromkeys(e.repo for e in entries):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = build_context(
                roots[repo], settings, "verifier-eval", model=model, db_path=Path(tmp) / "c.db"
            )
            for i, entry in enumerate(entries):
                if entry.repo != repo:
                    continue
                result = verify_hop(ctx, _hashed(entry, i, ctx))
                unsure += result.verdict == "unsure"
                if result.verdict == "rejected":
                    real_rejected += entry.real
                    fake_caught += not entry.real
                    if entry.real:
                        label = f"{repo}: {entry.caller.symbol} -> {entry.callee.symbol}"
                        rejected_real.append(f"{label}: {result.evidence}")
    real_total = sum(e.real for e in entries)
    return VerifierScore(
        real_rejected,
        real_total,
        fake_caught,
        len(entries) - real_total,
        unsure,
        tuple(rejected_real),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.run_verifier")
    parser.add_argument("hops", type=Path)
    parser.add_argument("--record", action="store_true", help="call the real model and record")
    args = parser.parse_args(argv)
    score = run_verifier(args.hops, record=args.record)
    print(
        f"real rejected {score.real_rejected}/{score.real_total} (bar {PASS_BAR:.0%}); "
        f"fake caught {score.fake_caught}/{score.fake_total}; unsure {score.unsure}"
    )
    for line in score.rejected_real:
        print(f"  REJECTED REAL {line}")
    print("PASS" if score.passed else "FAIL")
    return 0 if score.passed else 1


if __name__ == "__main__":
    sys.exit(main())
