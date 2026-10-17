"""Write the API's OpenAPI JSON to a file. Usage: dump_openapi.py OUT.json"""

import json
import sys
import tempfile
from pathlib import Path

from codemap.server.app import create_app
from codemap.service import Service
from codemap.settings import Settings


def main(out: Path) -> None:
    with tempfile.TemporaryDirectory() as repo:
        app = create_app(Service(Path(repo), Settings(), None), None)
        out.write_text(json.dumps(app.openapi(), indent=2) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
