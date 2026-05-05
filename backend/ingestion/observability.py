from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from typing import Iterator

from loguru import logger

from utils.types import Config


def configure_logging(cfg: Config) -> None:
    logger.remove()
    logger.configure(extra={"image_id": "-"})
    logger.add(
        sys.stderr,
        level=cfg.log_level,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{extra[image_id]}:{module}:{line} - {message}"
        ),
    )


def bind_image(image_id: str):
    return logger.bind(image_id=image_id)


@contextmanager
def stopwatch(name: str, timings: dict[str, float]) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        timings[name] = round(time.perf_counter() - started, 4)


class Stopwatch:
    def __init__(self, name: str, timings: dict[str, float]) -> None:
        self.name = name
        self.timings = timings
        self._started = 0.0

    def __enter__(self) -> "Stopwatch":
        self._started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.timings[self.name] = round(time.perf_counter() - self._started, 4)




def configure_logfire() -> None:
    disable = os.environ.get("KIRANA_DISABLE_LOGFIRE", "").lower()
    if disable in ("1", "true", "yes"):
        logger.info(
            "Logfire export skipped (KIRANA_DISABLE_LOGFIRE). "
            "Unset LOGFIRE_TOKEN or fix it at https://logfire.pydantic.dev if you re-enable."
        )
        return
    import logfire

    logfire.configure(token=os.environ.get("LOGFIRE_TOKEN"))
    logfire.instrument_pydantic_ai()
