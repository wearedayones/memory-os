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
from utils.validation import ensure_memory_schema, is_valid_memory, is_valid_metadata, schema_fields


class MemoryEngine:
    _REQUIRED_SCHEMA_FIELDS = list(schema_fields.keys())

    def __init__(self, base_path: str, user: str = "default") -> None:
        self.base_path = os.path.abspath(base_path)
        self.user = user
        self._store_dir = os.path.join(self.base_path, "memories", self.user)
        self._user_dir = os.path.join(self.base_path, "users")
        self._store = JsonStore(self._store_dir)
        self._graph_path = os.path.join(self.base_path, "graph", f"{self.user}.json")
        os.makedirs(self._user_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self._graph_path), exist_ok=True)

    def _default_memory(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        memory = {
            "id": generate_id(),
            "timestamp": now_iso(),
            "updated_at": now_iso(),
            "importance": 5,
            "confidence": 5,
            "tags": [],
            "type": "note",
            "source": None,
            "status": "active",
            "version": "1.0.0",
            "content": None,
            "metadata": {},
            "links": [],
        }
        if overrides:
            memory.update({k: v for k, v in overrides.items() if v is not None})
        return ensure_memory_schema(memory)

    def _normalize_memory(self, memory: dict[str, Any]) -> dict[str, Any]:
        normalized = ensure_memory_schema({}, defaults={k: v for k, v in memory.items() if v is not None})
        if not normalized.get("id"):
            normalized["id"] = generate_id()
        if not normalized.get("timestamp"):
            normalized["timestamp"] = now_iso()
        if not normalized.get("updated_at"):
            normalized["updated_at"] = now_iso()
        if not normalized.get("last_updated") and not normalized.get("updated_at"):
            normalized["updated_at"] = now_iso()
        return normalized

    @staticmethod
    def _text_haystack(record: dict[str, Any]) -> str:
        parts = [str(record.get(k, "")) for k in ("content", "source", "type") if record.get(k)]
        parts.extend(record.get("tags", []))
        metadata = record.get("metadata")
        if metadata:
            parts.append(json.dumps(metadata, ensure_ascii=True, sort_keys=True))
        return " ".join(parts)

    def _auto_link(self, record: dict[str, Any]) -> list[str]:
        record_id = record.get("id")
        if not record_id:
            return list(record.get("links") or [])
        seen: set[str] = {record_id}
        seen.update(record.get("links") or [])
        record_tags = {tag.lower() for tag in (record.get("tags") or [])}
        for key in self._store.list_keys():
            if key in seen:
                continue
            candidate = self._store.read(key)
            if candidate is None or candidate.get("status") != "active":
                continue
            if record_tags & {tag.lower() for tag in (candidate.get("tags") or [])}:
                seen.add(key)
        return sorted(seen)

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
        safe_updates = dict(updates)
        safe_updates["updated_at"] = now_iso()
        if safe_updates.get("last_updated") == "":
            safe_updates.pop("last_updated", None)
        merged = {**record, **safe_updates}
        merged = self._normalize_memory(merged)
        valid, errors = is_valid_memory(merged)
        if not valid:
            raise ValueError(f"Invalid memory after update: {errors}")
        self._store.write(memory_id, merged)
        return copy.deepcopy(merged)

    def forget(self, memory_id: str, *, hard: bool = False, prune_links: bool = True) -> bool:
        record = self._store.read(memory_id)
        if record is None or record.get("status") in {"archived", "deleted"}:
            return False
        if hard:
            self._store.delete(memory_id)
            if prune_links:
                for key in self._store.list_keys():
                    item = self._store.read(key)
                    if item and memory_id in (item.get("links") or []):
                        item["links"] = [link for link in item.get("links", []) if link != memory_id]
                        self._store.write(key, item)
        else:
            updated = {**record, "status": "archived", "updated_at": now_iso()}
            updated = self._normalize_memory(updated)
            self._store.write(memory_id, updated)
        return True

    def merge(self, primary_id: str, secondary_id: str) -> dict[str, Any] | None:
        primary = self._store.read(primary_id)
        secondary = self._store.read(secondary_id)
        if not primary or not secondary:
            return None
        merged_tags = sorted(set(primary.get("tags", []) + secondary.get("tags", [])))
        merged_links = sorted(set(primary.get("links", []) + secondary.get("links", [])))
        for item_id in (primary_id, secondary_id):
            if item_id not in merged_links:
                merged_links.append(item_id)
        metadata = copy.deepcopy(primary.get("metadata") or {})
        metadata.update(secondary.get("metadata") or {})
        merged = {
            "id": primary_id,
            "timestamp": primary.get("timestamp", now_iso()),
            "updated_at": now_iso(),
            "importance": max(int(primary.get("importance", 5)), int(secondary.get("importance", 5))),
            "confidence": max(int(primary.get("confidence", 5)), int(secondary.get("confidence", 5))),
            "tags": merged_tags,
            "source": primary.get("source") or secondary.get("source"),
            "type": primary.get("type") or secondary.get("type"),
            "status": "active",
            "version": primary.get("version", "1.0.0"),
            "content": primary.get("content") or secondary.get("content"),
            "metadata": metadata,
            "links": merged_links,
        }
        merged = self._normalize_memory(merged)
        valid, errors = is_valid_memory(merged)
        if not valid:
            raise ValueError(f"Invalid merged memory: {errors}")
        self._store.write(primary_id, merged)
        self.forget(secondary_id, hard=True, prune_links=False)
        return copy.deepcopy(merged)

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
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
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
            if since is not None and (record.get("timestamp") or "") < since:
                continue
            if until is not None and (record.get("timestamp") or "") > until:
                continue
            if tags:
                record_tags = {tag.lower() for tag in (record.get("tags") or [])}
                if not all(tag.lower() in record_tags for tag in tags):
                    continue
            if text and text.lower() not in self._text_haystack(record).lower():
                continue
            results.append(copy.deepcopy(record))
        return results

    def summarize(self, group_by: str = "type") -> dict[str, Any]:
        summaries: dict[str, Any] = {}
        for key in self._store.list_keys():
            record = self._store.read(key)
            if record is None:
                continue
            group = record.get(group_by) or "unknown"
            summary = summaries.setdefault(group, {"count": 0, "tags": [], "sources": []})
            summary["count"] += 1
            summary.setdefault("total_importance", 0)
            summary.setdefault("total_confidence", 0)
            summary["total_importance"] += int(record.get("importance", 5))
            summary["total_confidence"] += int(record.get("confidence", 5))
            for tag in record.get("tags", []):
                if tag not in summary["tags"]:
                    summary["tags"].append(tag)
            source = record.get("source")
            if source and source not in summary["sources"]:
                summary["sources"].append(source)
        for summary in summaries.values():
            count = summary["count"]
            summary["average_importance"] = summary.pop("total_importance", 0) / count if count else 0.0
            summary["average_confidence"] = summary.pop("total_confidence", 0) / count if count else 0.0
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
        target_statuses = set(statuses) if statuses else {"inactive", "archived", "broken", "deleted"}
        removed: list[str] = []
        for key in list(self._store.list_keys()):
            record = self._store.read(key)
            if record is None:
                continue
            if importance_below is not None and int(record.get("importance", 5)) > importance_below:
                continue
            if confidence_below is not None and int(record.get("confidence", 5)) > confidence_below:
                continue
            if older_than_seconds is not None:
                age = age_seconds(record.get("updated_at") or "")
                if age is None or age < older_than_seconds:
                    continue
            if record.get("status") not in target_statuses:
                continue
            removed.append(key)
            if not dry_run:
                self._store.delete(key)
        return removed

    def save_user(self, user_data: dict[str, Any]) -> None:
        is_valid_metadata(user_data)
        user_path = os.path.join(self._user_dir, f"{self.user}.json")
        fd, temp_path = tempfile.mkstemp(dir=self._user_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(user_data, handle, ensure_ascii=True, indent=2, sort_keys=True)
            os.replace(temp_path, user_path)
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
            payload = json.load(handle)
        is_valid_metadata(payload)
        return payload

    def load_graph(self) -> dict[str, Any] | None:
        if not os.path.exists(self._graph_path):
            return None
        with open(self._graph_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def save_graph(self, graph: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self._graph_path), exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(self._graph_path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(graph, handle, ensure_ascii=True, indent=2, sort_keys=True)
            os.replace(temp_path, self._graph_path)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise

    def search_graph(self, query: str | None = None, *, min_links: int | None = None) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for key in self._store.list_keys():
            record = self._store.read(key)
            if record is None:
                continue
            if query and query.lower() not in self._text_haystack(record).lower():
                continue
            if min_links is not None and int(len(record.get("links") or [])) < min_links:
                continue
            entries.append(copy.deepcopy(record))
        return entries

    def build_indexes(self) -> dict[str, Any]:
        memory_count = len(self._store.list_keys())
        tag_index: dict[str, list[str]] = {}
        for key in self._store.list_keys():
            record = self._store.read(key)
            if record is None:
                continue
            for tag in record.get("tags", []):
                tag_index.setdefault(tag, []).append(key)
        graph = {
            "nodes": memory_count,
            "edges": {},
            "tag_index": tag_index,
        }
        return graph

    def validate(self, memory: dict[str, Any]) -> tuple[bool, list[str]]:
        return is_valid_memory(memory)

    def import_memory(self, memory: dict[str, Any]) -> dict[str, Any]:
        if "id" not in memory or not memory["id"]:
            memory = {**memory, "id": generate_id()}
        return self.remember(memory)

    def export_memory(self, memory_id: str) -> dict[str, Any] | None:
        return self.recall(memory_id)

    def sync(self) -> dict[str, Any]:
        summary = self.summarize()
        graph = self.build_indexes()
        self.save_graph(graph)
        return {"summary": summary, "graph": graph}
