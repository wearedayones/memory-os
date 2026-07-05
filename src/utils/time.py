from datetime import datetime, timezone, timedelta


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_iso(value: str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def age_seconds(timestamp: str) -> float | None:
    if not timestamp:
        return None
    ts = ensure_iso(timestamp)
    if ts is None:
        return None
    target = datetime.fromisoformat(ts)
    now = datetime.now(timezone.utc)
    delta = now - target
    return delta.total_seconds()
