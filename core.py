import json
import os
import re
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def _user_dir(user_id: str) -> Path:
    d = DATA_DIR / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    for sub in ("raw", "structured", "index", "conversations", "preferences"):
        (d / sub).mkdir(exist_ok=True)
    return d


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _uid(prefix: str = "mem") -> str:
    return f"{prefix}_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"


def _atomic_write(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _file_newest(path: Path) -> datetime:
    try:
        return datetime.fromisoformat(json.loads(path.read_text(encoding="utf-8")).get("updated_at", _now()).replace("Z", "+00:00"))
    except Exception:
        return datetime.fromtimestamp(0, tz=None)


def _load_entry(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_entry(user_dir: Path, category: str, entry: Dict[str, Any]) -> Path:
    filepath = user_dir / category / f"{entry['id']}.json"
    _atomic_write(filepath, entry)
    return filepath


def _list_entries(user_dir: Path, category: str) -> List[Dict[str, Any]]:
    entries = []
    if not (user_dir / category).exists():
        return entries
    for p in sorted((user_dir / category).glob("*.json")):
        e = _load_entry(p)
        if e:
            entries.append(e)
    return entries


def _tag_text(text: str) -> List[str]:
    # Minimal heuristic tagging: lowercase alnum tokens longer than 2 chars, up to 8 tags
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_+#/-]{1,}", text.lower())
    seen = []
    for t in tokens:
        if t not in seen:
            seen.append(t)
        if len(seen) >= 8:
            break
    return seen


def _regex_query(query: str, exact: bool = False) -> re.Pattern:
    q = re.escape(query)
    q = q.replace(r"\ ", r"\s+")
    if not exact:
        q = re.sub(r"\\\*", ".*", q)
        if not q.startswith(".*"):
            q = ".*" + q
        if not q.endswith(".*"):
            q = q + ".*"
    return re.compile(q, re.IGNORECASE)


def _score(entry: Dict[str, Any], matches: int) -> float:
    # Recurrence score: exact field matches weighted by recency.
    now = datetime.utcnow()
    updated = None
    for key in ("updated_at", "created_at"):
        raw = entry.get(key, "")
        if raw:
            try:
                updated = datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
                break
            except Exception:
                continue
    age_days = (now - updated).total_seconds() / 86400.0 if updated else 365.0
    recency = 1.0 / (1.0 + max(age_days, 0.0))
    return matches * 2.0 + recency * 1.0


def _match_fields(entry: Dict[str, Any], pattern: re.Pattern) -> int:
    fields = [entry.get("title", ""), entry.get("text", ""), entry.get("topic", ""), " ".join(entry.get("tags", []))]
    if "summary" in entry and isinstance(entry["summary"], dict):
        fields.append(entry["summary"].get("text", ""))
        fields.extend(entry["summary"].get("tags", []))
    total = 0
    for f in fields:
        if f and pattern.search(str(f)):
            total += 1
    return total


def _commit_changes_for(user_id: str, entries: List[Dict[str, Any]], category: str) -> List[Path]:
    written = []
    for e in entries:
        written.append(_write_entry(_user_dir(user_id), category, e))
    # persist high-level index snapshots
    if category == "structured":
        _update_meta(user_id)
    return written


def _update_meta(user_id: str) -> None:
    user_dir = _user_dir(user_id)
    structured = _list_entries(user_dir, "structured")
    raw = _list_entries(user_dir, "raw")
    meta = {
        "updated_at": _now(),
        "user_id": user_id,
        "counts": {
            "raw": len(raw),
            "structured": len(structured),
        },
    }
    _atomic_write(user_dir / "index" / "meta.json", meta)


def remember(user_id: str, text: str, title: Optional[str] = None, tags: Optional[List[str]] = None) -> Dict[str, Any]:
    """Persist a raw memory entry."""
    if not text and not text.strip():
        raise ValueError("Memory text is required.")
    user_dir = _user_dir(user_id)
    entry_id = _uid("raw")
    entry: Dict[str, Any] = {
        "id": entry_id,
        "user_id": user_id,
        "title": title or "",
        "text": text,
        "tags": tags or _tag_text(text),
        "created_at": _now(),
        "updated_at": _now(),
        "category": "raw",
        "source": "api",
    }
    _write_entry(user_dir, "raw", entry)
    _update_meta(user_id)
    return entry


def recall(user_id: str, query: str, top_n: int = 10, exact: bool = False) -> List[Dict[str, Any]]:
    """Search memories across raw, structured, and conversations."""
    user_dir = _user_dir(user_id)
    pattern = _regex_query(query, exact=exact)
    candidates: List[tuple[float, Dict[str, Any]]] = []
    seen = set()
    for category in ("raw", "structured", "conversations"):
        for entry in _list_entries(user_dir, category):
            if entry.get("id") in seen:
                continue
            matches = _match_fields(entry, pattern)
            if matches > 0:
                score = _score(entry, matches)
                candidates.append((score, entry))
                seen.add(entry.get("id"))
    candidates.sort(key=lambda x: x[0], reverse=True)
    scored = []
    for _, entry in candidates[: max(top_n, 1)]:
        out = dict(entry)
        del out["text"]
        try:
            out["snippet"] = entry.get("text", "")[:240]
        except Exception:
            out["snippet"] = ""
        scored.append(out)
    return scored


def summarize(user_id: str, max_entries: int = 20) -> Dict[str, Any]:
    """Group raw entries into structured topic summaries."""
    user_dir = _user_dir(user_id)
    raw_entries = _list_entries(user_dir, "raw")
    if not raw_entries:
        return {"user_id": user_id, "topics": [], "counts": {"raw": 0, "structured": 0}}

    by_topic: Dict[str, List[Dict[str, Any]]] = {}
    for e in raw_entries:
        topic = e.get("topic") or (e.get("tags", [])[0] if e.get("tags") else "general")
        by_topic.setdefault(topic, []).append(e)

    written = []
    for topic, items in by_topic.items():
        items.sort(key=lambda x: x.get("created_at", ""))
        texts = [i.get("text", "") for i in items if i.get("text")]
        summary_text = " ".join(texts)
        all_tags = []
        seen_tags = set()
        for i in items:
            for t in i.get("tags", []):
                if t not in seen_tags:
                    all_tags.append(t)
                    seen_tags.add(t)
        summary_entry: Dict[str, Any] = {
            "id": _uid("topic"),
            "user_id": user_id,
            "title": f"{topic.title() if topic else 'Summary'} summary",
            "text": summary_text[:2000],
            "topic": topic,
            "tags": all_tags[:20],
            "created_at": _now(),
            "updated_at": _now(),
            "category": "structured",
            "summary": {
                "text": summary_text[:400],
                "entry_ids": [i.get("id") for i in items if i.get("id")],
                "count": len(items),
                "tags": all_tags[:20],
            },
            "source": "summarizer",
        }
        _write_entry(user_dir, "structured", summary_entry)
        written.append(summary_entry)

    _update_meta(user_id)
    return {
        "user_id": user_id,
        "topics": [t for t in by_topic.keys()],
        "counts": {"structured": len(written), "raw": len(raw_entries)},
    }


def cleanup(user_id: str, older_than_days: int = 180, dry_run: bool = False) -> Dict[str, Any]:
    """Merge/dedupe old or stale raw entries."""
    user_dir = _user_dir(user_id)
    raw_entries = _list_entries(user_dir, "raw")
    cutoff = datetime.utcnow() - timedelta(days=max(older_than_days, 1))
    to_remove = []
    to_keep = []
    for e in raw_entries:
        ts = e.get("updated_at") or e.get("created_at") or ""
        dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
                break
            except Exception:
                continue
        if dt and dt < cutoff:
            to_remove.append(e)
        else:
            to_keep.append(e)

    merged_count = 0
    seen_sigs = set()
    deduped = []
    for e in to_keep:
        sig = (e.get("topic") or "") + " || " + (e.get("text", "") or "").strip().lower()
        h = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]
        if h in seen_sigs:
            merged_count += 1
            continue
        seen_sigs.add(h)
        deduped.append(e)

    removed_ids = [e.get("id") for e in to_remove if e.get("id")]
    if not dry_run:
        # rewrite raw and structured afterwards
        from glob import glob
        for p in (user_dir / "raw").glob("*.json"):
            try:
                e = _load_entry(p)
                if e and e.get("id") in removed_ids:
                    p.unlink(missing_ok=True)
            except Exception:
                pass
        for e in deduped:
            _write_entry(user_dir, "raw", e)
        # regenerate summaries after cleanup
        summarize(user_id, max_entries=50)

    return {
        "user_id": user_id,
        "dry_run": bool(dry_run),
        "older_than_days": int(older_than_days),
        "removed_old": len(removed_ids),
        "merged_duplicates": merged_count,
        "removed_ids": removed_ids[:200],
    }


def commit_memory(message: Optional[str] = None) -> Dict[str, Any]:
    """Commit/persist any in-memory memory updates for all known users."""
    changed = []
    if not DATA_DIR.exists():
        return {"committed": 0, "users": [], "message": message}
    for user_dir in sorted(DATA_DIR.iterdir()):
        if not user_dir.is_dir():
            continue
        try:
            _update_meta(user_dir.name)
            changed.append(user_dir.name)
        except Exception:
            continue
    return {"committed": len(changed), "users": changed, "message": message}
