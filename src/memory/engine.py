from __future__ import annotations

import copy
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

from storage.json_store import JsonStore
from utils.ids import generate_id, generate_link_id
from utils.time import age_seconds, now_iso
from utils.validation import ensure_memory_schema, is_valid_memory, is_valid_metadata


class MemoryEngine:
    def __init__(self, base_path: str, user: str = "default") -> None:
        self.base_path = os.path.abspath(base_path)
        self.user = user
        self._store_dir = os.path.join(self.base_path, "memories", self.user)
        self._user_dir = os.path.join(self.base_path, "users")
        self._store = JsonStore(self._store_dir)
        os.makedirs(self._user_dir, exist_ok=True)

    def _empty_memory(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        record = {
            "id": generate_id(),
            "timestamp": now_iso(),
            "last_updated": now_iso(),
            "importance": 5,
            "confidence": 5,
            "tags": [],
            "source": None,
            "type": "note",
            "status": "active",
            "version": "1.0.0",
            "content": None,
            "metadata": {},
            "links": [],
        }
        if overrides:
            record.update(overrides)
        return ensure_memory_schema(record)

    def _auto_link(self, record: dict[str, Any]) -> list[str]:
        record_id = record.get("id")
        if not record_id:
            return list(record.get("links") or [])
        record_tags = {tag.lower() for tag in (record.get("tags") or [])}
        if not record_tags:
            return list(record.get("links") or [])
        seen: set[str] = {record_id}
        seen.update(record.get("links") or [])
        new_links: list[str] = list(seen)
        for key in self._store.list_keys():
            if key in seen:
                continue
            candidate = self._store.read(key)
            if candidate is None:
                continue
            if candidate.get("status") != "active":
                continue
            candidate_tags = {tag.lower() for tag in (candidate.get("tags") or [])}
            if record_tags & candidate_tags:
                seen.add(key)
                new_links.append(key)
        return sorted(set(new_links))

    @staticmethod
    def _resolve_boundary(value: datetime | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        stripped = value.strip()
        if stripped.endswith("Z"):
            stripped = stripped[:-1] + "+00:00"
        parsed = datetime.fromisoformat(stripped)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _text_haystack(record: dict[str, Any]) -> str:
        parts = [
            record.get("content") or "",
            record.get("source") or "",
            record.get("type") or "",
            " ".join(record.get("tags") or []),
        ]
        metadata = record.get("metadata")
        if metadata:
            parts.append(json.dumps(metadata, ensure_ascii=True, sort_keys=True))
        return " ".join(parts)

    def _normalize_memory(self, memory: dict[str, Any]) -> dict[str, Any]:
        overrides = {k: memory[k] for k in memory if memory.get(k) is not None}
        record = ensure_memory_schema({}, defaults=overrides)
        if not record.get("id"):
            record["id"] = generate_id()
        if not record.get("timestamp"):
            record["timestamp"] = now_iso()
        if not record.get("last_updated"):
            record["last_updated"] = now_iso()
        return record

    def _atomic_user_write(self, path: str, data: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            dir=os.path.dirname(path) or ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=True, indent=2, sort_keys=True)
            os.replace(temp_path, path)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise

    # Core mutators

    def remember(self, memory: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(memory, dict):
            raise TypeError("memory must be a dict")
        record = self._normalize_memory(memory)
        valid, errors = is_valid_memory(record)
        if not valid:
            raise ValueError(f"Invalid memory: {errors}")
        record["links"] = self._auto_link(record)
        self._store.write(record["id"], record)
        return copy.deepcopy(record)

    def recall(self, memory_id: str, *, include_inactive: bool = False) -> dict[str, Any] | None:
        record = self._store.read(memory_id)
        if record is None:
            return None
        if not include_inactive and record.get("status") != "active":
            return None
        return copy.deepcopy(record)

    def update(self, memory_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        record = self._store.read(memory_id)
        if record is None:
            return None
        merged = {**record, **updates, "last_updated": now_iso()}
        valid, errors = is_valid_memory(merged)
        if not valid:
            raise ValueError(f"Invalid memory after update: {errors}")
        merged = ensure_memory_schema(merged)
        self._store.write(memory_id, merged)
        return copy.deepcopy(merged)

    def forget(self, memory_id: str, *, hard: bool = False) -> bool:
        record = self._store.read(memory_id)
        if record is None:
            return False
        if hard:
            self._store.delete(memory_id)
        else:
            record = {**record, "status": "archived", "last_updated": now_iso()}
            self._store.write(memory_id, record)
        return True

    def merge(self, primary_id: str, secondary_id: str) -> dict[str, Any] | None:
        primary = self._store.read(primary_id)
        secondary = self._store.read(secondary_id)
        if primary is None or secondary is None:
            return None
        merged_tags = sorted(set(primary.get("tags", []) + secondary.get("tags", [])))
        merged_links = sorted(set(primary.get("links", []) + secondary.get("links", [])))
        if primary_id not in merged_links:
            merged_links.append(primary_id)
        if secondary_id not in merged_links:
            merged_links.append(secondary_id)
        metadata = copy.deepcopy(primary.get("metadata") or {})
        metadata.update(secondary.get("metadata") or {})
        content = primary.get("content") or secondary.get("content")
        importance = max(
            int(primary.get("importance", 5)), int(secondary.get("importance", 5))
        )
        confidence = max(
            int(primary.get("confidence", 5)), int(secondary.get("confidence", 5))
        )
        source = primary.get("source") or secondary.get("source")
        memory_type = primary.get("type") or secondary.get("type")
        merged = {
            "id": primary_id,
            "timestamp": primary.get("timestamp", now_iso()),
            "last_updated": now_iso(),
            "importance": importance,
            "confidence": confidence,
            "tags": merged_tags,
            "source": source,
            "type": memory_type,
            "status": "active",
            "version": primary.get("version", "1.0.0"),
            "content": content,
            "metadata": metadata,
            "links": merged_links,
        }
        merged = ensure_memory_schema(merged)
        self._store.write(primary_id, merged)
        self.forget(secondary_id, hard=True)
        return copy.deepcopy(merged)

    # Queries

    def search(
        self,
        *,
        text: str | None = None,
        tags: list[str] | None = None,
        importance_ge: int | None = None,
        confidence_ge: int | None = None,
        memory_type: str | None = None,
        status: str | None = None,
        source: str | None = None,
        since: datetime | str | None = None,
        until: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        since_iso = self._resolve_boundary(since)
        until_iso = self._resolve_boundary(until)
        matches: list[dict[str, Any]] = []
        for key in self._store.list_keys():
            record = self._store.read(key)
            if record is None:
                continue
            if status is not None and record.get("status") != status:
                continue
            if memory_type is not None and record.get("type") != memory_type:
                continue
            if source is not None and record.get("source") != source:
                continue
            if importance_ge is not None and int(record.get("importance", 5)) < importance_ge:
                continue
            if confidence_ge is not None and int(record.get("confidence", 5)) < confidence_ge:
                continue
            if since_iso:
                ts = record.get("timestamp") or ""
                if not ts or ts < since_iso:
                    continue
            if until_iso:
                ts = record.get("timestamp") or ""
                if ts and ts > until_iso:
                    continue
            if tags:
                record_tags = {t.lower() for t in record.get("tags", [])}
                lower_tags = [t.lower() for t in tags]
                if not all(tag in record_tags for tag in lower_tags):
                    continue
            if text:
                if text.lower() not in self._text_haystack(record).lower():
                    continue
            matches.append(copy.deepcopy(record))
        return matches

    def summarize(self, group_by: str = "type") -> dict[str, Any]:
        summaries: dict[str, Any] = {}
        for key in self._store.list_keys():
            record = self._store.read(key)
            if record is None:
                continue
            group = record.get(group_by) or "unknown"
            if group not in summaries:
                summaries[group] = {
                    "count": 0,
                    "total_importance": 0,
                    "total_confidence": 0,
                    "tags": [],
                    "sources": [],
                }
            summary = summaries[group]
            summary["count"] += 1
            summary["total_importance"] += int(record.get("importance", 5))
            summary["total_confidence"] += int(record.get("confidence", 5))
            for tag in record.get("tags", []):
                if tag not in summary["tags"]:
                    summary["tags"].append(tag)
            source = record.get("source")
            if source and source not in summary["sources"]:
                summary["sources"].append(source)
        for group, summary in summaries.items():
            count = summary["count"]
            summary["average_importance"] = (
                summary["total_importance"] / count if count else 0.0
            )
            summary["average_confidence"] = (
                summary["total_confidence"] / count if count else 0.0
            )
            del summary["total_importance"]
            del summary["total_confidence"]
        return summaries

    def cleanup(
        self,
        *,
        importance_below: int | None = None,
        confidence_below: int | None = None,
        older_than_seconds: float | None = None,
        statuses: list[str] | None = None,
        dry_run: bool = False,
    ) -> list[str]:
        target_statuses = set(statuses) if statuses else {"inactive", "archived", "broken"}
        removed: list[str] = []
        keys = self._store.list_keys()
        for key in keys:
            record = self._store.read(key)
            if record is None:
                continue
            if importance_below is not None and int(record.get("importance", 5)) >= importance_below:
                continue
            if confidence_below is not None and int(record.get("confidence", 5)) >= confidence_below:
                continue
            if older_than_seconds is not None:
                age = age_seconds(record.get("last_updated") or "")
                if age is None or age < older_than_seconds:
                    continue
            if record.get("status") not in target_statuses:
                continue
            removed.append(key)
            if not dry_run:
                self._store.delete(key)
        return removed

    # User-level persistence

    def save_user(self, user_data: dict[str, Any]) -> None:
        is_valid_metadata(user_data)
        user_dir = self._user_dir
        os.makedirs(user_dir, exist_ok=True)
        path = os.path.join(user_dir, f"{self.user}.json")
        fd, temp_path = tempfile.mkstemp(dir=user_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(user_data, handle, ensure_ascii=True, indent=2, sort_keys=True)
            os.replace(temp_path, path)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise

    def load_user(self) -> dict[str, Any] | None:
        path = os.path.join(self._user_dir, f"{self.user}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    # Validation / import / export

    def validate(self, memory: dict[str, Any]) -> tuple[bool, list[str]]:
        return is_valid_memory(memory)

    def export_memory(self, memory_id: str) -> dict[str, Any] | None:
        return self.recall(memory_id)

    def import_memory(self, memory: dict[str, Any]) -> dict[str, Any]:
        if "id" not in memory:
            memory = {**memory, "id": generate_id()}
        return self.remember(memory)
