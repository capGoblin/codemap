import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent


@pytest.mark.parametrize("subdir", ["src", "tests/fixtures"])
def test_index_survives_every_python_file(subdir: str) -> None:
    """tree-sitter 0.26.0 segfaulted while the index walked real files.

    A subprocess makes a native crash fail this test instead of killing pytest.
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_index.py"), str(ROOT / subdir)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-2000:]
