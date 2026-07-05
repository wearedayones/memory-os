from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from graph.engine import KnowledgeGraph
from graph.ontology import Node, VALID_NODE_TYPES


class SummaryResult(dict):
    pass


class SummarizerEngine:
    def __init__(self, graph: Optional[KnowledgeGraph] = None, base_dir: Optional[Path] = None) -> None:
        self.graph = graph or KnowledgeGraph()
        self.base_dir = base_dir or Path(
            os.environ.get('HERMES_MEMORY_DIR', '/home/ubuntu/hermes-memory')
        )
        self.summary_dir = self.base_dir / 'summaries'
        self.summary_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _collect(self, user_id: Optional[str] = None, scope: str = 'user') -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for node in self.graph.nodes.values():
            if scope == 'user':
                owner = str(node.properties.get('user_id', '') or '')
                if user_id is not None and owner != user_id:
                    continue
            items.append(node.to_dict())
        return items

    def _compress(self, items: List[Dict[str, Any]], max_chars: int = 1800) -> str:
        bucket = Counter()
        for item in items:
            key = item.get('node_id') or item.get('type') or 'unknown'
            bucket[key] += 1
        parts = [f"{k} x{v}" for k, v in bucket.most_common(25)]
        text = ' | '.join(parts)
        if len(text) > max_chars:
            text = text[: max_chars - 3] + '...'
        return text

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _write_index(self, summary: Dict[str, Any]) -> None:
        index_path = self.summary_dir / 'index.json'
        data: Dict[str, Any] = {'summaries': []}
        if index_path.exists():
            try:
                data = json.loads(index_path.read_text())
            except Exception:
                data = {'summaries': []}
        data.setdefault('summaries', []).append(summary)
        index_path.write_text(json.dumps(data, indent=2))

    # ------------------------------------------------------------------
    # Generators
    # ------------------------------------------------------------------
    def conversation(self, source_text: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        now = self._now()
        payload = {
            'scope': 'conversation',
            'source_text': source_text[:4000],
            'metadata': metadata or {},
        }
        summary = {
            'id': _hash(f'{now}:conversation:{source_text}')[:16],
            'type': 'conversation',
            'summary': f"Conversation summary ({len(source_text)} chars)",
            'payload': payload,
            'created_at': now,
        }
        path = self.summary_dir / f"{summary['id']}.json"
        path.write_text(json.dumps(summary, indent=2))
        self._write_index(summary)
        return summary

    def project(self, project_id: str, project_name: str = '') -> Dict[str, Any]:
        nodes = [n.to_dict() for n in self.graph.nodes.values() if str(n.properties.get('project_id', '')) == project_id]
        text = f"Project '{project_name}' progress. " + self._compress(nodes)
        now = self._now()
        summary = {
            'id': _hash(f'{now}:project:{project_id}')[:16],
            'type': 'project',
            'project_id': project_id,
            'summary': text,
            'created_at': now,
        }
        path = self.summary_dir / f"{summary['id']}.json"
        path.write_text(json.dumps(summary, indent=2))
        self._write_index(summary)
        return summary

    def user(self, user_id: str) -> Dict[str, Any]:
        items = self._collect(user_id=user_id, scope='user')
        text = self._compress(items)
        now = self._now()
        summary = {
            'id': _hash(f'{now}:user:{user_id}')[:16],
            'type': 'user',
            'user_id': user_id,
            'summary': text,
            'created_at': now,
        }
        path = self.summary_dir / f"{summary['id']}.json"
        path.write_text(json.dumps(summary, indent=2))
        self._write_index(summary)
        return summary

    def daily(self, user_id: Optional[str] = None, pivot_date: Optional[datetime] = None) -> Dict[str, Any]:
        if pivot_date is None:
            pivot_date = datetime.now(timezone.utc)
        day_start = pivot_date.replace(hour=0, minute=0, second=0, microsecond=0)
        items = self._collect(user_id=user_id, scope='user')
        day_items = []
        for item in items:
            timestamp = item.get('updated_at') or item.get('created_at') or ''
            try:
                dt = datetime.fromisoformat(timestamp)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= day_start:
                    day_items.append(item)
            except Exception:
                continue
        text = f"Daily summary {day_start.date().isoformat()}: " + self._compress(day_items)
        now = self._now()
        summary = {
            'id': _hash(f'{now}:daily:{user_id}:{day_start.isoformat()}')[:16],
            'type': 'daily',
            'user_id': user_id,
            'date': day_start.date().isoformat(),
            'summary': text,
            'created_at': now,
        }
        path = self.summary_dir / f"{summary['id']}.json"
        path.write_text(json.dumps(summary, indent=2))
        self._write_index(summary)
        return summary

    def long_term(
        self,
        user_id: Optional[str] = None,
        threshold_items: int = 30,
        max_progression: int = 300,
    ) -> Dict[str, Any]:
        items = self._collect(user_id=user_id, scope='user')
        items = sorted(items, key=lambda x: x.get('created_at', ''))[:max_progression]
        if len(items) < threshold_items:
            text = f"Long-term summary (incomplete; {len(items)} items). " + self._compress(items)
        else:
            text = f"Long-term summary ({len(items)} items). " + self._compress(items)
        now = self._now()
        summary = {
            'id': _hash(f'{now}:long-term:{user_id}:items:{len(items)}')[:16],
            'type': 'long_term',
            'user_id': user_id,
            'summary': text,
            'item_count': len(items),
            'created_at': now,
        }
        path = self.summary_dir / f"{summary['id']}.json"
        path.write_text(json.dumps(summary, indent=2))
        self._write_index(summary)
        return summary

    def build_all(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return [
            self.user(user_id=user_id),
            self.daily(user_id=user_id),
            self.long_term(user_id=user_id),
        ]

    def list_summaries(self, summary_type: Optional[str] = None) -> List[Dict[str, Any]]:
        index_path = self.summary_dir / 'index.json'
        if not index_path.exists():
            return []
        try:
            data = json.loads(index_path.read_text())
            summaries = data.get('summaries', [])
        except Exception:
            return []
        if summary_type:
            summaries = [s for s in summaries if s.get('type') == summary_type]
        summaries = sorted(summaries, key=lambda s: s.get('created_at', ''), reverse=True)
        return summaries

    def ensure_node(self, type: str = 'Concepts', title: str = '', **kwargs: Any) -> Node:
        if type not in VALID_NODE_TYPES:
            raise ValueError(f'Invalid node type: {type!r}')
        node = self.graph.add_node(type=type, title=title, **kwargs)
        return node

    def summarize_and_link(
        self,
        node_id: str,
        *,
        summary_type: str = 'user',
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if summary_type == 'conversation':
            raise ValueError('Use conversation() for source-text summaries.')
        node = self.graph.get_node(node_id)
        if node is None:
            raise KeyError(f'Node not found: {node_id}')
        target_user = user_id if user_id is not None else str(node.properties.get('user_id', '') or '')
        summary = self.user(user_id=target_user)

        # Touch related edges via relationship expansion.
        expanded = self.graph.multi_hop(node_id, max_hops=1)
        return summary


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]
