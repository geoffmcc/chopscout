from __future__ import annotations

import logging
from pathlib import Path

from platformdirs import user_log_dir


def configure_logging() -> Path:
    directory = Path(user_log_dir("ChopScout", "ChopScout"))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "chopscout.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()],
    )
    return path
