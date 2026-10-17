import socket
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn

from codemap.server.app import create_app
from codemap.service import Service

_HOST = "127.0.0.1"
_WAIT_SECONDS = 5.0
_DEFAULT_STATIC = Path(__file__).parent / "static"


def serve_in_background(service: Service, static_dir: Path | None = None) -> str:
    """Start the API on 127.0.0.1 and a free port in a daemon thread. Return the base URL."""
    if static_dir is None and _DEFAULT_STATIC.is_dir():
        static_dir = _DEFAULT_STATIC
    sock = socket.socket()
    sock.bind((_HOST, 0))
    url = f"http://{_HOST}:{sock.getsockname()[1]}"
    config = uvicorn.Config(create_app(service, static_dir), log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/v1/health", timeout=0.5):
                return url
        except OSError:
            time.sleep(0.05)
    server.should_exit = True
    raise RuntimeError("codemap server did not start within 5 s")


def serve_dev(service: Service, port: int, static_dir: Path | None = None) -> None:
    """Serve in the foreground. Without `static_dir`, serve the API only for the Vite proxy."""
    uvicorn.run(create_app(service, static_dir), host=_HOST, port=port, log_level="warning")
