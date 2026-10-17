"""Hatch build hook: build the React UI into src/codemap/server/static for wheels and sdists."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class UiBuildHook(BuildHookInterface):  # type: ignore[type-arg]
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        # Editable installs (uv sync) and CODEMAP_SKIP_UI builds never need the UI.
        if version == "editable" or os.environ.get("CODEMAP_SKIP_UI"):
            return
        frontend = Path(self.root) / "frontend"
        if not frontend.is_dir():
            return
        npm = shutil.which("npm")
        if npm is None:
            raise RuntimeError(
                "Node.js (npm) is required to build the codemap UI. "
                "Install Node 20+, or set CODEMAP_SKIP_UI=1 to build without the UI."
            )
        for args in (["ci"], ["run", "build"]):
            subprocess.run([npm, "--prefix", str(frontend), *args], check=True)
        index = Path(self.root) / "src" / "codemap" / "server" / "static" / "index.html"
        if not index.is_file():
            raise RuntimeError(f"UI build did not produce {index}")
