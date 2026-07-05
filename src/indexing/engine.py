from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class IndexEngine:
    def __init__(self, base_dir: str | os.PathLike[str] | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else Path('/home/ubuntu/hermes-memory')
        self.index_dir = self.base_dir / 'index'
        for p in [self.index_dir]:
            p.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.index_dir / f'{name}.json'

    def _load(self, path: Path, default: Any):
        if not path.exists() or path.stat().st_size == 0:
            return default
        try:
            return json.loads(path.read_text())
        except Exception:
            return default

    def _write(self, path: Path, data: Any):
        path.write_text(json.dumps(data, indent=2, ensure_ascii=True))

    def build_keyword_index(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        index: dict[str, Any] = {}
        for e in entries:
            text = str(e.get('text') or e.get('content') or '')
            mem_id = str(e.get('id') or '')
            for raw in [w.strip(".,:;!?'\"()[]{}") for w in text.lower().split() if len(w.strip(".,:;!?'\"()[]{}")) > 2]:
                w = raw.lower()
                item = index.setdefault(w, {'count': 0, 'memory_ids': []})
                item['count'] += 1
                if mem_id and mem_id not in item['memory_ids']:
                    item['memory_ids'].append(mem_id)
        self._write(self._path('keyword_index'), {'keywords': index})
        return {'keywords': index}

    def build_tag_index(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        index: dict[str, Any] = {}
        for e in entries:
            mem_id = str(e.get('id') or '')
            for t in [str(x).lower() for x in (e.get('tags') or []) if str(x).strip()]:
                item = index.setdefault(t, {'count': 0, 'memory_ids': []})
                item['count'] += 1
                if mem_id and mem_id not in item['memory_ids']:
                    item['memory_ids'].append(mem_id)
        self._write(self._path('tag_index'), {'tags': index})
        return {'tags': index}

    def build_entity_index(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        entities: dict[str, Any] = {}
        for e in entries:
            mem_id = str(e.get('id') or '')
            text = str(e.get('text') or e.get('content') or '')
            words = [w for w in text.split() if len(w) > 2]
            for w in words:
                key = w.strip(".,:;!?'\"()[]{}")
                if not key:
                    continue
                item = entities.setdefault(key, {'count': 0, 'memory_ids': []})
                item['count'] += 1
                if mem_id and mem_id not in item['memory_ids']:
                    item['memory_ids'].append(mem_id)
        self._write(self._path('entity_index'), {'entities': entities})
        return {'entities': entities}

    def build_relationship_index(self, edges: list[dict[str, Any]]) -> dict[str, Any]:
        rels: dict[str, Any] = {}
        for e in edges:
            rel = str(e.get('type') or e.get('edge_type') or '')
            if not rel:
                continue
            key = rel.lower()
            item = rels.setdefault(key, {'count': 0, 'edges': []})
            item['count'] += 1
            item['edges'].append(e)
        self._write(self._path('relationship_index'), {'relationships': rels})
        return {'relationships': rels}

    def build_all(self, memories: list[dict[str, Any]], edges: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        kw = self.build_keyword_index(memories)
        tag = self.build_tag_index(memories)
        ent = self.build_entity_index(memories)
        rel = self.build_relationship_index(edges or [])
        return {'keywords': kw, 'tags': tag, 'entities': ent, 'relationships': rel}
