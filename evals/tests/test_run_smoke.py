import json
from pathlib import Path

import pytest

from codemap.domain.models import Anchor
from codemap.repo.anchors import check_anchor
from codemap.repo.ignore import RepoIgnore
from codemap.repo.tools import RepoTools
from evals.run_smoke import SmokeEntry, append_results, format_table, load_smoke, run_smoke
from evals.tests.test_run_golden import UPLOAD, ScriptedModel, committed_repo

SMOKE = Path(__file__).resolve().parents[1] / "smoke.json"


def test_smoke_file_has_five_repos() -> None:
    assert len(load_smoke(SMOKE)) == 5


@pytest.mark.parametrize("item", load_smoke(SMOKE), ids=lambda i: Path(i.repo).name)
def test_smoke_entry_anchors_resolve(item: SmokeEntry) -> None:
    root = Path(item.repo)
    if not root.is_dir():
        pytest.skip(f"{root} is not on this machine")
    tools = RepoTools(root, RepoIgnore(root))
    assert check_anchor(tools, Anchor.model_validate(item.entry)) is None


def test_run_smoke_reports_a_scripted_trace(tmp_path: Path) -> None:
    repo, _ = committed_repo(tmp_path)
    path = tmp_path / "smoke.json"
    path.write_text(json.dumps([{"repo": str(repo), "question": "q", "entry": UPLOAD}]))
    rows = run_smoke(path, model=ScriptedModel())
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "complete"
    assert (row.phases, row.steps, row.hops) == (2, 4, 4)
    assert row.files_read >= 4

    results = tmp_path / "notes" / "eval-results.md"
    append_results(rows, "test-model", results)
    text = results.read_text()
    assert "test-model" in text
    assert format_table(rows) in text
