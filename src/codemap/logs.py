"""File logging with token redaction."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from codemap.settings import load_settings

LOG_FORMAT = "%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"
_HANDLER_MARK = "_codemap_handler"
_MAX_BYTES = 1_000_000
_BACKUPS = 3


class RedactFilter(logging.Filter):
    """Replace the exact token value with `***` in the message, args and traceback."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._token:
            return True
        record.msg = record.getMessage().replace(self._token, "***")
        record.args = None
        if record.exc_info and not record.exc_text:
            text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = text.replace(self._token, "***")
        elif record.exc_text:
            record.exc_text = record.exc_text.replace(self._token, "***")
        return True


def setup_logging(root: Path, verbose: bool, token: str | None = None) -> None:
    """Log to `root/.codemap/logs/codemap.log`. `token` defaults to the configured one."""
    if token is None:
        token = load_settings().resolved_api_key()
    path = root / ".codemap" / "logs" / "codemap.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(RedactFilter(token))
    setattr(handler, _HANDLER_MARK, True)

    logger = logging.getLogger("codemap")
    for old in [h for h in logger.handlers if getattr(h, _HANDLER_MARK, False)]:
        logger.removeHandler(old)
        old.close()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
