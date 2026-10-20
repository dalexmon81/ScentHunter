from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone


@dataclass
class HealthSnapshot:
    engine: str = "next"
    process_ok: bool = True
    database_ok: bool = False
    last_success_at: str | None = None
    last_error: str | None = None
    stores_configured: int = 0
    offers_current: int = 0
    stale_store_count: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def freshness_seconds(iso_timestamp: str | None, *, now=None) -> float | None:
    if not iso_timestamp:
        return None
    now = now or datetime.now(timezone.utc)
    then = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0.0, (now - then).total_seconds())
