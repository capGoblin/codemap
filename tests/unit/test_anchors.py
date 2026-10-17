import shutil
from pathlib import Path

import pytest

from codemap.domain.models import Anchor
from codemap.repo.anchors import check_anchor, hash_range, is_stale, with_hash
from codemap.repo.ignore import RepoIgnore
from codemap.repo.tools import RepoTools

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_repo"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(FIXTURE, dest)
    return dest


@pytest.fixture
def tools(repo: Path) -> RepoTools:
    return RepoTools(repo, RepoIgnore(repo))


def _anchor(
    file: str = "app/worker.py", start: int = 9, end: int = 12, symbol: str = "w.parse_document"
) -> Anchor:
    return Anchor(file=file, start_line=start, end_line=end, symbol=symbol)


def test_hash_range_ignores_trailing_whitespace() -> None:
    assert hash_range("a  \nb\n", 1, 2) == hash_range("a\nb", 1, 2)
    assert hash_range("a\nb", 1, 1) != hash_range("a\nb", 2, 2)


def test_check_anchor_ok(tools: RepoTools) -> None:
    assert check_anchor(tools, _anchor()) is None


def test_check_anchor_symbol_missing(tools: RepoTools) -> None:
    assert "nope" in (check_anchor(tools, _anchor(symbol="nope")) or "")
    assert check_anchor(tools, _anchor(symbol="parse")) is not None  # whole word only


def test_check_anchor_past_eof(tools: RepoTools) -> None:
    assert "past end" in (check_anchor(tools, _anchor(end=500)) or "")


@pytest.mark.parametrize("file", ["missing.py", "../x.py", "/etc/passwd", "build/out.py"])
def test_check_anchor_bad_file(tools: RepoTools, file: str) -> None:
    assert check_anchor(tools, _anchor(file=file)) is not None


def test_with_hash(tools: RepoTools) -> None:
    anchored = with_hash(tools, _anchor())
    assert len(anchored.content_hash) == 64
    assert not is_stale(tools, anchored)


def test_is_stale_after_edit(tools: RepoTools, repo: Path) -> None:
    anchored = with_hash(tools, _anchor())
    file = repo / "app" / "worker.py"
    file.write_text(file.read_text().replace("pages = ocr", "pages = ocr2"))
    assert is_stale(tools, anchored)


def test_is_stale_for_missing_file(tools: RepoTools) -> None:
    assert is_stale(tools, _anchor(file="missing.py"))
