import sys
from pathlib import Path

from loguru import logger

from utils.config import load_config


def _configured_log_level() -> str:
    config_path = Path(__file__).resolve().parents[1] / "config.toml"
    return load_config(str(config_path)).log_level


logger.remove()
logger.configure(extra={"image_id": "-"})
logger.add(sys.stderr, level=_configured_log_level())

log = logger
