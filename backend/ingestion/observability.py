from __future__ import annotations

import os
import sys
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path
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


def _read_logfire_token(default_path: Path | None = None) -> str | None:
    if token := os.environ.get("LOGFIRE_TOKEN"):
        return token

    path = default_path or Path.home() / ".logfire" / "default.toml"
    if not path.exists():
        return None
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    tokens = data.get("tokens", {})
    for token_config in tokens.values():
        token = token_config.get("token")
        if token:
            return token
    return None


def _env_has_key(env_path: Path, key: str) -> bool:
    if not env_path.exists():
        return False
    return any(
        line.split("=", 1)[0].strip() == key
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def bootstrap_logfire_token(env_path: Path | None = None) -> str | None:
    token = _read_logfire_token()
    if token is None:
        return None

    os.environ.setdefault("LOGFIRE_TOKEN", token)
    target_env = env_path or Path(__file__).resolve().parents[1] / ".env"
    if not _env_has_key(target_env, "LOGFIRE_TOKEN"):
        with target_env.open("a", encoding="utf-8") as f:
            if target_env.exists() and target_env.stat().st_size > 0:
                f.write("\n")
            f.write(f"LOGFIRE_TOKEN={token}\n")
    return token


def configure_logfire() -> None:
    token = bootstrap_logfire_token()
    if token is None:
        logger.warning("LOGFIRE_TOKEN not found; Logfire export is disabled")
        return
    import logfire

    logfire.configure(token=token)
    logfire.instrument_pydantic_ai()
