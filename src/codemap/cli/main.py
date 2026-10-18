"""Typer app: global options and command wiring."""

from pathlib import Path
from typing import Annotated, Any

import typer

from codemap import __version__
from codemap.cli import doctor as doctor_cmd
from codemap.cli import open as open_cmd
from codemap.cli import render
from codemap.cli import trace as trace_cmd
from codemap.logs import setup_logging
from codemap.server.run import serve_dev
from codemap.service import Service
from codemap.settings import Provider, Settings

app = typer.Typer(help="Trace one system in a codebase into a zoomable graph.")


def make_service(repo: Path, settings: Settings) -> Service:
    return Service(repo, settings)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"codemap {__version__}")
        raise typer.Exit


@app.callback()
def main(
    ctx: typer.Context,
    repo: Annotated[Path, typer.Option(help="Repository to work in.")] = Path("."),
    verbose: Annotated[bool, typer.Option("--verbose", help="Log at debug level.")] = False,
    provider: Annotated[Provider | None, typer.Option(help="Model provider.")] = None,
    model: Annotated[
        str | None, typer.Option(help="Model id. Default depends on provider.")
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option(help="Prefer the env var; a flag lands in shell history."),
    ] = None,
    base_url: Annotated[
        str | None, typer.Option(help="Any OpenAI- or Anthropic-compatible endpoint.")
    ] = None,
    max_cost: Annotated[
        float | None, typer.Option(help="Stop a run past this cost in USD.")
    ] = None,
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    given = {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "max_cost_usd": max_cost,
    }
    overrides = {k: v for k, v in given.items() if v is not None}
    ctx.obj = (repo.resolve(), verbose, overrides)


def _settings(ctx: typer.Context) -> Settings:
    """Settings with the global flags as init args, so they beat env and config.toml."""
    overrides: dict[str, Any] = ctx.obj[2]
    return Settings(**overrides)


def _service(ctx: typer.Context, settings: Settings) -> Service:
    repo, verbose, _ = ctx.obj
    setup_logging(repo, verbose, settings.resolved_api_key())
    return make_service(repo, settings)


@app.command()
def trace(
    ctx: typer.Context,
    question: str,
    lazy: Annotated[bool, typer.Option(help="Build the phase level only.")] = False,
    pick: Annotated[int | None, typer.Option(help="Entry point number; skips the prompt.")] = None,
    json: Annotated[
        bool, typer.Option("--json", help="Print only the graph JSON on stdout.")
    ] = False,
    no_open: Annotated[
        bool, typer.Option("--no-open", help="Skip the browser and the server.")
    ] = False,
) -> None:
    """Trace the system that QUESTION describes."""
    service = _service(ctx, _settings(ctx))
    trace_cmd.run_trace(service, question, lazy, pick, json, not no_open)


@app.command()
def open(  # noqa: A001
    ctx: typer.Context, trace_id: Annotated[str | None, typer.Argument()] = None
) -> None:
    """Open a saved trace in the browser."""
    raise typer.Exit(open_cmd.open_trace(_service(ctx, _settings(ctx)), trace_id))


@app.command("list")
def list_traces(ctx: typer.Context) -> None:
    """List saved traces for this repo."""
    traces = _service(ctx, _settings(ctx)).list_traces()
    console = render.status_console(to_stderr=False)
    if not traces:
        console.print('No traces yet. Run: codemap trace "<system>"')
        return
    console.print(render.traces_table(traces))


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check the environment, model access and database."""
    settings = _settings(ctx)
    repo, verbose, _ = ctx.obj
    setup_logging(repo, verbose, settings.resolved_api_key())
    raise typer.Exit(doctor_cmd.run_doctor(settings, lambda: make_service(repo, settings)))


DEV_PORT = 8765


@app.command("serve-dev", hidden=True)
def serve_dev_cmd(
    ctx: typer.Context,
    port: Annotated[int, typer.Option(help="Port to listen on.")] = DEV_PORT,
    static: Annotated[Path | None, typer.Option(help="Built frontend to serve.")] = None,
) -> None:
    """Serve the API for the frontend dev server, or the built frontend with --static."""
    serve_dev(_service(ctx, _settings(ctx)), port, static)
