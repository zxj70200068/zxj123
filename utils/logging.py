"""Project-wide stdlib logging factory (no third-party deps)."""

import logging
from logging import FileHandler, Formatter, Logger, StreamHandler

from utils.paths import PROJECT_ROOT

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_ERROR_LOG_PATH = PROJECT_ROOT / "app_error.log"


def get_logger(name: str) -> Logger:
    """Return a logger named ``name`` configured with a stream + file handler.

    The stream handler writes INFO-and-above to stderr; the file handler writes
    ERROR-and-above to ``PROJECT_ROOT/app_error.log``. Handlers are attached
    once per logger to avoid duplicate emission on repeated calls.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not any(getattr(h, "_hvac_kind", None) == "stream" for h in logger.handlers):
        stream = StreamHandler()
        stream.setLevel(logging.INFO)
        stream.setFormatter(Formatter(_LOG_FORMAT))
        stream._hvac_kind = "stream"  # type: ignore[attr-defined]
        logger.addHandler(stream)

    if not any(getattr(h, "_hvac_kind", None) == "file" for h in logger.handlers):
        file_handler = FileHandler(_ERROR_LOG_PATH, encoding="utf-8", delay=True)
        file_handler.setLevel(logging.ERROR)
        file_handler.setFormatter(Formatter(_LOG_FORMAT))
        file_handler._hvac_kind = "file"  # type: ignore[attr-defined]
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger
