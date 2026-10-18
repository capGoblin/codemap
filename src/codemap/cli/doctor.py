"""The `doctor` command: check the setup. Never print secret values."""

import shutil
import sys
from collections.abc import Callable

from rich.table import Table

from codemap.agents.pricing import price_for
from codemap.cli import render
from codemap.service import Service
from codemap.settings import FALLBACK_KEY_VARS, Settings

Check = tuple[str, str, str]  # name, pass|warn|fail, detail
_STYLE = {"pass": "green", "warn": "yellow", "fail": "red"}
_MIN_PYTHON = (3, 12)


def _config(settings: Settings) -> list[Check]:
    key = settings.resolved_api_key()
    model = settings.resolved_model
    prices = price_for(model, settings.price_in_per_mtok, settings.price_out_per_mtok)
    rows: list[Check] = [
        ("provider", "pass", settings.provider),
        (
            "api key",
            "pass" if key else "fail",
            "set"
            if key
            else f"missing: set {FALLBACK_KEY_VARS[settings.provider]} or CODEMAP_API_KEY",
        ),
        ("model", "pass", model),
        (
            "price",
            "pass" if prices else "warn",
            f"${prices[0]} in / ${prices[1]} out per MTok"
            if prices
            else "price unknown: set price_in_per_mtok / price_out_per_mtok",
        ),
    ]
    if settings.base_url:
        rows.append(("base url", "pass", settings.base_url))
    return rows


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
        return ("model call", "fail", "skipped: database did not open")
    if not settings.resolved_api_key():
        return ("model call", "fail", "skipped: no API key")
    error = service.check_model()
    if error:
        return ("model call", "fail", error)
    return ("model call", "pass", f"{settings.resolved_model} answered")


def run_doctor(settings: Settings, make: Callable[[], Service]) -> int:
    db_check, service = _db(make)
    checks = [*_config(settings), _python(), _rg(), db_check, _model(service, settings)]
    table = Table(title="codemap doctor")
    for name in ("check", "result", "detail"):
        table.add_column(name)
    for name, result, detail in checks:
        table.add_row(name, f"[{_STYLE[result]}]{result}[/{_STYLE[result]}]", detail)
    render.status_console(to_stderr=False).print(table)
    return 1 if any(result == "fail" for _, result, _ in checks) else 0
