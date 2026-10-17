"""The `doctor` command: check the setup. Never print secret values."""

import shutil
import sys
from collections.abc import Callable

from rich.table import Table

from codemap.cli import render
from codemap.service import Service
from codemap.settings import Settings

Check = tuple[str, str, str]  # name, pass|warn|fail, detail
_STYLE = {"pass": "green", "warn": "yellow", "fail": "red"}
_MIN_PYTHON = (3, 12)


def _env(settings: Settings) -> list[Check]:
    token = settings.anthropic_auth_token.get_secret_value()
    return [
        (
            "ANTHROPIC_AUTH_TOKEN",
            "pass" if token else "fail",
            "set" if token else "missing: set it in the environment or config.toml",
        ),
        (
            "ANTHROPIC_BASE_URL",
            "pass" if settings.anthropic_base_url else "fail",
            settings.anthropic_base_url or "missing",
        ),
    ]


def _python() -> Check:
    found = sys.version_info[:2]
    ok = found >= _MIN_PYTHON
    return ("python", "pass" if ok else "fail", ".".join(map(str, found)))


def _rg() -> Check:
    if shutil.which("rg"):
        return ("rg", "pass", "found")
    return ("rg", "warn", "not on PATH: code search is slower")


def _db(make: Callable[[], Service]) -> tuple[Check, Service | None]:
    try:
        service = make()
    except Exception as exc:
        return ("database", "fail", f"{type(exc).__name__}: {exc}"), None
    return ("database", "pass", "opens, schema is current"), service


def _model(service: Service | None, settings: Settings) -> Check:
    if service is None:
        return ("model", "fail", "skipped: database did not open")
    if not settings.anthropic_auth_token.get_secret_value():
        return ("model", "fail", "skipped: no auth token")
    error = service.check_model()
    if error:
        return ("model", "fail", error)
    return ("model", "pass", f"{settings.model} answered")


def run_doctor(settings: Settings, make: Callable[[], Service]) -> int:
    db_check, service = _db(make)
    checks = [*_env(settings), _python(), _rg(), db_check, _model(service, settings)]
    table = Table(title="codemap doctor")
    for name in ("check", "result", "detail"):
        table.add_column(name)
    for name, result, detail in checks:
        table.add_row(name, f"[{_STYLE[result]}]{result}[/{_STYLE[result]}]", detail)
    render.status_console(to_stderr=False).print(table)
    return 1 if any(result == "fail" for _, result, _ in checks) else 0
