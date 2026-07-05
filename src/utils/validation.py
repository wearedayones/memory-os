from typing import Any

schema_fields = {
    "id": str,
    "timestamp": str,
    "updated_at": str,
    "importance": int,
    "confidence": int,
    "tags": list,
    "type": str,
    "source": str | None,
    "status": str,
    "version": str,
    "content": str | None,
    "metadata": dict | None,
    "links": list | None,
}


def _type_name(expected_type: Any) -> str:
    if hasattr(expected_type, "__name__"):
        return expected_type.__name__
    origin = getattr(expected_type, "__origin__", None)
    args = getattr(expected_type, "__args__", ())
    if origin is not None:
        inner = ", ".join(_type_name(a) for a in args)
        if args:
            return f"{_type_name(origin)}[{inner}]"
        return _type_name(origin)
    return repr(expected_type)


def _validate_schema_entry(value: Any, expected_type: Any, path: str, errors: list[str]) -> None:
    if value is None:
        if str(expected_type) in ("str | None", "dict | None", "list | None") or type(None) in getattr(expected_type, "__args__", ()):
            return
        errors.append(f"{path} expected {_type_name(expected_type)}, got NoneType")
        return
    origin = getattr(expected_type, "__origin__", None)
    args = getattr(expected_type, "__args__", ())
    valid = False
    if origin is not None and args:
        valid = isinstance(value, args)
    if not valid:
        valid = isinstance(value, expected_type)
    if not valid:
        errors.append(f"{path} expected {_type_name(expected_type)}, got {type(value).__name__}")


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
        value = record[field]
        _validate_schema_entry(value, expected_type, field, errors)
    if "importance" in record and record["importance"] is not None:
        importance = record["importance"]
        if not isinstance(importance, int) or not (0 <= importance <= 10):
            errors.append("importance must be int between 0 and 10")
    if "confidence" in record and record["confidence"] is not None:
        confidence = record["confidence"]
        if not isinstance(confidence, int) or not (0 <= confidence <= 10):
            errors.append("confidence must be int between 0 and 10")
    if "version" in record and not isinstance(record.get("version", ""), str):
        errors.append("version must be a string")
    valid_status = {"active", "archived", "inactive", "broken", "deleted"}
    if record.get("status") and record["status"] not in valid_status:
        errors.append(f"status must be one of {sorted(valid_status)}")
    return len(errors) == 0, errors


def is_valid_metadata(metadata: dict[str, Any]) -> tuple[bool, list[str]]:
    if not isinstance(metadata, dict):
        return False, ["metadata must be a dict"]
    return True, []


def ensure_memory_schema(data: dict[str, Any], defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    merged: dict[str, Any] = dict(defaults) if defaults else {}
    merged.update(data)

    if "id" not in merged or not merged["id"]:
        from utils.ids import generate_id
        merged["id"] = generate_id()
    if "timestamp" not in merged or not merged["timestamp"]:
        from utils.time import now_iso
        merged["timestamp"] = now_iso()
    if "last_updated" not in merged or not merged["last_updated"]:
        from utils.time import now_iso
        merged["last_updated"] = now_iso()
    if "importance" not in merged or merged.get("importance") is None:
        merged["importance"] = 5
    if "confidence" not in merged or merged.get("confidence") is None:
        merged["confidence"] = 5
    if "tags" not in merged or merged.get("tags") is None:
        merged["tags"] = []
    if "links" not in merged or merged.get("links") is None:
        merged["links"] = []
    for field in ("type", "version", "status"):
        if field not in merged or not merged[field]:
            merged[field] = "note" if field == "type" else "1.0.0" if field == "version" else "active"
    for field in ("source", "content"):
        if field not in merged:
            merged[field] = None
    if "metadata" not in merged:
        merged["metadata"] = {}
    for list_field in ("tags", "links"):
        if not isinstance(merged.get(list_field), list):
            merged[list_field] = []
    return merged
