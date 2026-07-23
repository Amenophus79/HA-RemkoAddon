from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

AVAILABLE = "available"
UNAVAILABLE = "unavailable"
ERROR = "error"
STARTING = "starting"
BUSY = "busy"


def build_feedback_payload(
    status: str,
    message: str = "",
    *,
    available: bool | None = None,
) -> dict[str, Any]:
    if available is None:
        available = status == AVAILABLE
    return {
        "available": bool(available),
        "status": status,
        "message": message,
        "last_update": datetime.now(timezone.utc).isoformat(),
    }
