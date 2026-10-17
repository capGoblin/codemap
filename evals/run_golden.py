"""Run codemap on a pinned target repo and score the trace against a golden file.

python -m evals.run_golden evals/example-file-parsing.expected.json [--record]
"""

import argparse
import subprocess
import sys
from pathlib import Path

from codemap.agents.model import AnthropicModel, ChatModel
from codemap.agents.recording import CachedModel, JsonFileCache, ReplayOnlyModel
from codemap.domain.models import EntryCandidate
from codemap.service import Service
from codemap.settings import load_settings
from evals.expected import ExpectedTrace, load_expected
from evals.score import Score, format_score, score

RECORDINGS = Path(__file__).parent / "recordings"


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True, timeout=30
    )
    return done.stdout.strip()


def run_golden(expected_path: Path, *, record: bool, model: ChatModel | None = None) -> Score:
    """Trace the expected file's entry and score the result.

    `model` replaces the recording layer. It exists for tests.
    """
    root = Path(ExpectedTrace.model_validate_json(expected_path.read_text()).repo)
    expected = load_expected(expected_path, root)

    head = _git(root, "rev-parse", "HEAD")
    if not head.startswith(expected.commit):
        raise RuntimeError(f"{root} is at {head}, but the expected file pins {expected.commit}")
    if _git(root, "status", "--porcelain"):
        print(f"warning: {root} has uncommitted changes; the trace reads the working tree")

    settings = load_settings()
    if model is None:
        cache = JsonFileCache(
            RECORDINGS / f"{expected_path.name.removesuffix('.expected.json')}.json"
        )
        if record:
            model = CachedModel(
                AnthropicModel(
                    settings.anthropic_base_url,
                    settings.anthropic_auth_token.get_secret_value(),
                    settings.model,
                    settings.request_timeout_s,
                ),
                cache,
            )
        else:
            model = ReplayOnlyModel(cache)

    service = Service(root, settings, model)
    entry = EntryCandidate(anchor=expected.entry, label="golden", reason="pinned")
    trace_id = service.start_trace(expected.question, entry, "eager")
    service.wait(trace_id)
    result = score(service.get_graph(trace_id, depth=99), expected)
    print(format_score(result))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run_golden")
    parser.add_argument("expected", type=Path)
    parser.add_argument("--record", action="store_true", help="call the real model and record")
    args = parser.parse_args(argv)
    run_golden(args.expected, record=args.record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
