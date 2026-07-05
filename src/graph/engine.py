from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .ontology import VALID_EDGE_TYPES, VALID_NODE_TYPES, Edge, Node


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeGraph:
    def __init__(self, base_dir: Optional[str | os.PathLike[str]] = None) -> None:
        if base_dir is None:
            base_dir = os.environ.get('HERMES_GRAPH_DIR', '/home/ubuntu/hermes-memory/graph')
        self.base_dir = Path(base_dir)
        self.nodes_dir = self.base_dir / 'nodes'
        self.edges_dir = self.base_dir / 'edges'
        self.index_dir = self.base_dir / 'index'
        self._auto_index()
        self.nodes: Dict[str, Node] = {}
        self.edges: Dict[str, Edge] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _auto_index(self) -> None:
        for d in [self.nodes_dir, self.edges_dir, self.index_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def _node_path(self, node_id: str) -> Path:
        return self.nodes_dir / f'{node_id}.json'

    def _edge_path(self, edge_id: str) -> Path:
        return self.edges_dir / f'{edge_id}.json'

    def _node_index_path(self) -> Path:
        return self.index_dir / 'nodes.json'

    def _edge_index_path(self) -> Path:
        return self.index_dir / 'edges.json'

    def _write_json(self, path: Path, data: Dict[str, Any]) -> None:
        path.write_text(_json_dumps(data))

    def _read_json(self, path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        if not path.exists() or path.stat().st_size == 0:
            self._write_json(path, default)
            return default
        try:
            data = _json_loads(path.read_text())
            if not isinstance(data, dict):
                return default
            return data
        except Exception:
            return default

    def _load(self) -> None:
        self.nodes.clear()
        self.edges.clear()
        for p in self.nodes_dir.glob('*.json'):
            try:
                data = _json_loads(p.read_text())
                if isinstance(data, dict) and 'node_id' in data:
                    self.nodes[data['node_id']] = Node.from_dict(data)
            except Exception:
                pass
        for p in self.edges_dir.glob('*.json'):
            try:
                data = _json_loads(p.read_text())
                if isinstance(data, dict) and 'edge_id' in data:
                    self.edges[data['edge_id']] = Edge.from_dict(data)
            except Exception:
                pass
        self._update_index_files()

    def _update_index_files(self) -> None:
        nodes_index = {
            'count': len(self.nodes),
            'by_type': {},
            'updated_at': _now_iso(),
        }
        for node in self.nodes.values():
            nodes_index['by_type'].setdefault(node.type, []).append(node.node_id)

        edges_index = {
            'count': len(self.edges),
            'by_type': {},
            'updated_at': _now_iso(),
        }
        for edge in self.edges.values():
            edges_index['by_type'].setdefault(edge.type, []).append(edge.edge_id)

        self._write_json(self._node_index_path(), nodes_index)
        self._write_json(self._edge_index_path(), edges_index)

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------
    def add_node(
        self,
        node_id: Optional[str] = None,
        *,
        type: str = 'Concepts',
        title: str = '',
        description: str = '',
        tags: Optional[List[str]] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> Node:
        if type not in VALID_NODE_TYPES:
            raise ValueError(f'Invalid node type: {type!r}')

        if node_id is None:
            seed = f'{type}:{title}:{_now_iso()}'
            node_id = hashlib.sha1(seed.encode()).hexdigest()[:16]

        if node_id in self.nodes:
            raise ValueError(f'Node already exists: {node_id}')

        node = Node(
            node_id=node_id,
            type=type,
            title=title,
            description=description,
            tags=list(tags or []),
            properties=dict(properties or {}),
        )
        self.nodes[node_id] = node
        self._write_json(self._node_path(node_id), node.to_dict())
        self._update_index_files()
        return node

    def get_node(self, node_id: str) -> Optional[Node]:
        return self.nodes.get(node_id)

    def update_node(self, node_id: str, **changes: Any) -> Optional[Node]:
        node = self.nodes.get(node_id)
        if node is None:
            return None
        for key, value in changes.items():
            if key == 'tags' and value is not None:
                node.tags = list(value)
            elif key == 'properties' and value is not None:
                node.properties = dict(value)
            elif hasattr(node, key):
                setattr(node, key, value)
        node.updated_at = _now_iso()
        self._write_json(self._node_path(node_id), node.to_dict())
        self._update_index_files()
        return node

    def delete_node(self, node_id: str) -> bool:
        if node_id not in self.nodes:
            return False
        del self.nodes[node_id]
        path = self._node_path(node_id)
        if path.exists():
            path.unlink()
        # Remove connected edges.
        to_remove = [eid for eid, edge in self.edges.items() if edge.source_id == node_id or edge.target_id == node_id]
        for eid in to_remove:
            self.delete_edge(eid)
        self._update_index_files()
        return True

    def find_nodes_by_type(self, type: str) -> List[Node]:
        return [n for n in self.nodes.values() if n.type == type]

    def find_nodes_by_tag(self, tag: str) -> List[Node]:
        tag_lower = tag.lower()
        return [n for n in self.nodes.values() if any(t.lower() == tag_lower for t in n.tags)]

    def find_nodes_by_keyword(self, keyword: str) -> List[Node]:
        keyword_lower = keyword.lower()
        results: List[Tuple[float, Node]] = []
        for n in self.nodes.values():
            text = f"{n.title} {n.description} {' '.join(n.tags)}".lower()
            score = 0.0
            if keyword_lower in text:
                score += 2.0
            for tag in n.tags:
                if keyword_lower in tag.lower():
                    score += 1.5
            if score:
                results.append((score, n))
        results.sort(key=lambda x: x[0], reverse=True)
        return [node for _, node in results]

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------
    def add_edge(
        self,
        source_id: str,
        target_id: str,
        type: str,
        *,
        edge_id: Optional[str] = None,
        strength: float = 0.5,
        context: str = '',
        properties: Optional[Dict[str, Any]] = None,
    ) -> Edge:
        if type not in VALID_EDGE_TYPES:
            raise ValueError(f'Invalid edge type: {type!r}')
        source_node = self.nodes.get(source_id)
        target_node = self.nodes.get(target_id)
        if source_node is None or target_node is None:
            raise ValueError('Both source and target nodes must exist before adding an edge.')

        # Avoid duplicate undirected-style edges for symmetric relations.
        if type in {'related_to', 'knows'}:
            for edge in self.edges.values():
                if (
                    edge.type == type
                    and (
                        (edge.source_id == source_id and edge.target_id == target_id)
                        or (edge.source_id == target_id and edge.target_id == source_id)
                    )
                ):
                    raise ValueError(f'Duplicate edge between {source_id} and {target_id}.')

        if edge_id is None:
            seed = f'{source_id}:{type}:{target_id}:{_now_iso()}'
            edge_id = hashlib.sha1(seed.encode()).hexdigest()[:16]

        if edge_id in self.edges:
            raise ValueError(f'Edge already exists: {edge_id}')

        edge = Edge(
            edge_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            type=type,
            strength=float(max(0.0, min(1.0, strength))),
            context=context,
            properties=dict(properties or {}),
        )
        self.edges[edge_id] = edge
        self._write_json(self._edge_path(edge_id), edge.to_dict())
        self._update_index_files()
        return edge

    def get_edge(self, edge_id: str) -> Optional[Edge]:
        return self.edges.get(edge_id)

    def delete_edge(self, edge_id: str) -> bool:
        if edge_id not in self.edges:
            return False
        del self.edges[edge_id]
        path = self._edge_path(edge_id)
        if path.exists():
            path.unlink()
        self._update_index_files()
        return True

    def neighbors(self, node_id: str, direction: str = 'out'):
        if direction in ('out', 'both'):
            for edge in self.edges.values():
                if edge.source_id == node_id:
                    target = self.nodes.get(edge.target_id)
                    if target is not None:
                        yield target, edge
        if direction in ('in', 'both'):
            for edge in self.edges.values():
                if edge.target_id == node_id:
                    source = self.nodes.get(edge.source_id)
                    if source is not None:
                        yield source, edge

    def edges_for_node(self, node_id: str) -> List[Edge]:
        return [edge for edge in self.edges.values() if edge.source_id == node_id or edge.target_id == node_id]

    # ------------------------------------------------------------------
    # Multi-hop traversal
    # ------------------------------------------------------------------
    def multi_hop(
        self,
        start_node_id: str,
        max_hops: int = 3,
        edge_types: Optional[List[str]] = None,
        direction: str = 'out',
        limit: int = 50,
    ) -> List[Tuple[Node, int, List[Edge]]]:
        """
        Return reachable nodes from start_node_id within max_hops.
        Each result tuple is (node, hop_distance, path_edges).
        """
        if max_hops < 1:
            return []

        seen = {start_node_id}
        results: List[Tuple[Node, int, List[Edge]]] = []
        frontier = [(start_node_id, 0, [])]
        while frontier and len(results) < limit:
            next_frontier: List[Tuple[str, int, List[Edge]]] = []
            for node_id, hops, path in frontier:
                for neighbor, edge in self.neighbors(node_id, direction=direction):
                    if neighbor.node_id in seen:
                        continue
                    if edge_types and edge.type not in edge_types:
                        continue
                    seen.add(neighbor.node_id)
                    new_path = path + [edge]
                    if hops + 1 < max_hops:
                        next_frontier.append((neighbor.node_id, hops + 1, new_path))
                    results.append((neighbor, hops + 1, new_path))
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break
            frontier = next_frontier
        return results

    def shortest_path(
        self,
        source_id: str,
        target_id: str,
        max_hops: int = 5,
    ) -> Optional[List[Edge]]:
        if source_id not in self.nodes or target_id not in self.nodes:
            return None
        if source_id == target_id:
            return []

        visited = {source_id: []}
        frontier = [source_id]
        hops = 0
        while frontier and hops < max_hops:
            next_frontier: List[str] = []
            for node_id in frontier:
                for neighbor, edge in self.neighbors(node_id, direction='both'):
                    if neighbor.node_id in visited:
                        continue
                    visited[neighbor.node_id] = visited[node_id] + [edge]
                    if neighbor.node_id == target_id:
                        return visited[neighbor.node_id]
                    next_frontier.append(neighbor.node_id)
            frontier = next_frontier
            hops += 1
        return None

    def prune(self, max_orphan_age_days: int = 30) -> Dict[str, int]:
        removed_nodes = 0
        removed_edges = 0
        threshold = max_orphan_age_days * 24 * 60 * 60
        orphan_ids = [
            node_id
            for node_id, node in self.nodes.items()
            if not any(
                (edge.source_id == node_id or edge.target_id == node_id)
                for edge in self.edges.values()
            )
        ]
        for node_id in orphan_ids:
            node = self.nodes.get(node_id)
            if node is None:
                continue
            try:
                created = datetime.fromisoformat(node.created_at)
                age_seconds = (datetime.now(timezone.utc) - created).total_seconds()
            except Exception:
                age_seconds = float('inf')
            if age_seconds <= threshold:
                continue
            if self.delete_node(node_id):
                removed_nodes += 1
        self._update_index_files()
        return {'removed_nodes': removed_nodes, 'removed_edges': removed_edges}

    def stats(self) -> Dict[str, Any]:
        by_type: Dict[str, int] = {}
        for node in self.nodes.values():
            by_type[node.type] = by_type.get(node.type, 0) + 1
        edge_by_type: Dict[str, int] = {}
        for edge in self.edges.values():
            edge_by_type[edge.type] = edge_by_type.get(edge.type, 0) + 1
        return {
            'nodes': len(self.nodes),
            'edges': len(self.edges),
            'node_types': by_type,
            'edge_types': edge_by_type,
        }


def _json_loads(text: str) -> Dict[str, Any]:
    import json
    return json.loads(text)


def _json_dumps(data: Dict[str, Any]) -> str:
    import json
    return json.dumps(data, indent=2)
