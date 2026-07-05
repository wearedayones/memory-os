from typing import Any

schema_fields = {
    "id": str,
    "timestamp": str,
    "last_updated": str,
    "importance": int,
    "confidence": int,
    "tags": list,
    "source": str | None,
    "type": str,
    "status": str,
    "version": str,
    "content": str | None,
    "metadata": dict | None,
    "links": list | None,
}


def _validate_schema_entry(value: Any, expected_type: Any, path: str, errors: list[str]) -> None:
    if value is None:
        return
    if isinstance(expected_type, tuple) or hasattr(expected_type, "__origin__"):
        return
    if not isinstance(value, expected_type):
        errors.append(f"{path} expected {expected_type.__name__}, got {type(value).__name__}")


def is_valid_memory(record: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return False, ["record must be a dict"]
    for field in schema_fields:
        if field not in record:
            errors.append(f"missing required field: {field}")
    for field, expected_type in schema_fields.items():
        if field not in record:
            continue
        _validate_schema_entry(record[field], expected_type, field, errors)
    if record.get("importance") is not None:
        importance = record["importance"]
        if not isinstance(importance, int) or not (0 <= importance <= 10):
            errors.append("importance must be int between 0 and 10")
    if record.get("confidence") is not None:
        confidence = record["confidence"]
        if not isinstance(confidence, int) or not (0 <= confidence <= 10):
            errors.append("confidence must be int between 0 and 10")
    return (len(errors) == 0, errors)


def is_valid_metadata(metadata: dict[str, Any]) -> tuple[bool, list[str]]:
    if not isinstance(metadata, dict):
        return False, ["metadata must be a dict"]
    return True, []


def ensure_memory_schema(
    data: dict[str, Any],
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(defaults) if defaults else {}
    merged.update(data)
    if "timestamp" in merged and not merged["timestamp"]:
        from utils.time import now_iso
        merged["timestamp"] = now_iso()
    if "last_updated" in merged and not merged["last_updated"]:
        from utils.time import now_iso
        merged["last_updated"] = now_iso()
    for field in ("importance", "confidence"):
        if field not in merged:
            merged[field] = 5
    for list_field in ("tags", "links"):
        if list_field not in merged or merged[list_field] is None:
            merged[list_field] = []
    if "status" not in merged or not merged["status"]:
        merged["status"] = "active"
    if "version" not in merged or not merged["version"]:
        merged["version"] = "1.0.0"
    if "type" not in merged or not merged["type"]:
        merged["type"] = "note"
    if "source" not in merged:
        merged["source"] = None
    if "content" not in merged:
        merged["content"] = None
    if "metadata" not in merged:
        merged["metadata"] = {}
    return merged
