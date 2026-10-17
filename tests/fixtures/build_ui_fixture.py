"""Build a finished ScriptedModel trace in a temp copy of sample_repo for the browser e2e test.

Run: uv run python tests/fixtures/build_ui_fixture.py
Prints {"repo": <path>, "trace_id": <id>} as JSON on stdout.
"""

import json
import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(TESTS), str(TESTS / "unit")]

from test_service import RoutedModel, make, trace  # noqa: E402


def main() -> None:
    svc, repo = make(Path(tempfile.mkdtemp(prefix="codemap-ui-")), RoutedModel())
    print(json.dumps({"repo": str(repo), "trace_id": trace(svc)}))


if __name__ == "__main__":
    main()
