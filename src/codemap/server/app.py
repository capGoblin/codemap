from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from codemap.server.routes import make_router
from codemap.service import Service

_NO_CACHE = {"Cache-Control": "no-cache"}
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


def create_app(service: Service, static_dir: Path | None) -> FastAPI:
    app = FastAPI(
        title="codemap", openapi_url="/api/v1/openapi.json", docs_url=None, redoc_url=None
    )

    @app.exception_handler(KeyError)
    def _not_found(_: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse({"detail": f"not found: {exc.args[0]}"}, status_code=404)

    app.include_router(make_router(service), prefix="/api/v1")
    if static_dir is not None:
        _mount_spa(app, static_dir.resolve())
    return app


def _mount_spa(app: FastAPI, root: Path) -> None:
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "not found")
        target = (root / path).resolve()
        if path and target.is_file() and target.is_relative_to(root) and target != index:
            immutable = target.is_relative_to(root / "assets")
            return FileResponse(target, headers=_IMMUTABLE if immutable else _NO_CACHE)
        return FileResponse(index, headers=_NO_CACHE)
