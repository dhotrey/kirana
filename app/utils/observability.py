from __future__ import annotations

import os

LOGFIRE_DISABLED_VALUES = ("1", "true", "yes")


def logfire_enabled() -> bool:
    return os.environ.get("KIRANA_DISABLE_LOGFIRE", "").lower() not in (
        LOGFIRE_DISABLED_VALUES
    )
