import hashlib
import secrets
from datetime import datetime, timezone


def generate_id(prefix: str = "mem") -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    random_suffix = secrets.token_hex(3)
    raw = f"{timestamp}-{random_suffix}-{prefix.lower()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def generate_link_id(source_id: str, target_id: str) -> str:
    raw = source_id + target_id
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"link_{digest}"
