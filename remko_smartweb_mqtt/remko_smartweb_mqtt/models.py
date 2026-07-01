from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class HeatPumpState:
    temperature_top: float | None = None
    temperature_bottom: float | None = None
    target_temperature: float | None = None
    operating_mode: str | None = None
    status: str | None = None
    power: str | None = None
    source_url: str | None = None
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_payload(self) -> dict[str, Any]:
        return {
            "temperature_top": self.temperature_top,
            "temperature_bottom": self.temperature_bottom,
            "target_temperature": self.target_temperature,
            "mode": self.operating_mode,
            "status": self.status,
            "power": self.power,
            "source_url": self.source_url,
            "last_update": self.scraped_at.isoformat(),
        }


@dataclass(slots=True)
class Command:
    kind: str
    value: Any
