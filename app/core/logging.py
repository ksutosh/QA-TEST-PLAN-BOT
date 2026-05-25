import logging
import os
from typing import Optional

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "app.log")

_configured = False


def setup_logging(level: Optional[str] = None) -> None:
    global _configured
    if _configured:
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    log_level = getattr(logging, (level or os.getenv("LOG_LEVEL", "INFO")).upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(filename)s:%(lineno)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(),
        ],
        force=True,
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
