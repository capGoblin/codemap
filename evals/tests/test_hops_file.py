from pathlib import Path
from typing import Any

from codemap.agents.model import ModelResponse
from codemap.repo.anchors import check_anchor
from codemap.repo.ignore import RepoIgnore
from codemap.repo.tools import RepoTools
from evals.run_verifier import REPOS, VerifierScore, load_hops, run_verifier

HOPS = Path(__file__).resolve().parents[1] / "hops" / "hops.json"
FIXTURE = Path(__file__).resolve().parents[2] / "tests/fixtures/sample_repo"


def test_hops_file_valid() -> None:
    entries = load_hops(HOPS)
    assert sum(e.real for e in entries) >= 15
    assert sum(not e.real for e in entries) >= 12
    assert len({e.category for e in entries if e.real}) >= 4
    assert {e.repo for e in entries} <= set(REPOS)
    keys = [(e.repo, e.caller, e.callee, e.wiring) for e in entries]
    assert len(set(map(repr, keys))) == len(keys)
    tools = {r: RepoTools(REPOS[r], RepoIgnore(REPOS[r])) for r in {e.repo for e in entries}}
    for e in entries:
        for anchor in (e.caller, e.callee, e.wiring):
            if anchor is not None:
                assert check_anchor(tools[e.repo], anchor) is None, (e.repo, anchor)
        assert e.caller != e.callee


class Scripted:
    def __init__(self, verdicts: list[str]) -> None:
        self._verdicts = list(verdicts)

    def respond(self, **_: Any) -> ModelResponse:
        verdict = self._verdicts.pop(0)
        fields: dict[str, Any] = {"verdict": verdict, "evidence": "because"}
        if verdict == "rejected":
            fields["evidence_anchors"] = [
                {"file": "app/queue.py", "start_line": 3, "end_line": 3, "symbol": "HANDLERS"}
            ]
        block = {"type": "tool_use", "id": "s1", "name": "submit", "input": fields}
        return ModelResponse(
            content=[block], stop_reason="tool_use", input_tokens=1, output_tokens=1
        )


def _hops_file(tmp_path: Path) -> Path:
    queue = {"file": "app/queue.py", "start_line": 6, "end_line": 7, "symbol": "enqueue"}
    wiring = {"file": "app/queue.py", "start_line": 3, "end_line": 3, "symbol": "HANDLERS"}

    def entry(callee: dict[str, Any], real: bool) -> dict[str, Any]:
        return {
            "repo": "sample", "caller": queue, "callee": callee, "kind": "call",
            "wiring": wiring, "real": real,
        }  # fmt: skip

    parse = {"file": "app/worker.py", "start_line": 9, "end_line": 12, "symbol": "parse_document"}
    ocr = {"file": "app/worker.py", "start_line": 5, "end_line": 6, "symbol": "ocr"}
    import json

    path = tmp_path / "hops.json"
    path.write_text(json.dumps([entry(parse, True), entry(ocr, False)]))
    return path


def test_run_verifier_scores_real_and_fake(tmp_path: Path) -> None:
    score = run_verifier(
        _hops_file(tmp_path),
        record=False,
        repos={"sample": FIXTURE},
        model=Scripted(["confirmed", "rejected"]),
    )
    assert (score.real_rejected, score.real_total, score.fake_caught, score.fake_total) == (
        0,
        1,
        1,
        1,
    )
    assert score.unsure == 0
    assert score.passed


def test_run_verifier_counts_rejected_real_and_unsure(tmp_path: Path) -> None:
    score = run_verifier(
        _hops_file(tmp_path),
        record=False,
        repos={"sample": FIXTURE},
        model=Scripted(["rejected", "unsure"]),
    )
    assert score == VerifierScore(1, 1, 0, 1, 1, score.rejected_real)
    assert len(score.rejected_real) == 1
    assert not score.passed


def test_replay_without_recording_is_unsure(tmp_path: Path) -> None:
    score = run_verifier(
        _hops_file(tmp_path),
        record=False,
        repos={"sample": FIXTURE},
        recording=tmp_path / "none.json",
    )
    assert score.unsure == 2 and score.real_rejected == 0
    assert not (FIXTURE / ".codemap").exists()
