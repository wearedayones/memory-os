from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


VALID_NODE_TYPES: List[str] = [
    'Users',
    'Projects',
    'Topics',
    'Concepts',
    'Companies',
    'People',
    'Places',
    'Tools',
    'Files',
    'Tasks',
    'Goals',
    'Ideas',
]


VALID_EDGE_TYPES: List[str] = [
    'likes',
    'owns',
    'works_on',
    'uses',
    'related_to',
    'depends_on',
    'created',
    'knows',
    'prefers',
    'member_of',
    'contains',
    'references',
]


@dataclass
class Node:
    node_id: str
    type: str
    title: str = ''
    description: str = ''
    tags: List[str] = field(default_factory=list)
    properties: Dict[str, object] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: _now_iso())
    updated_at: str = field(default_factory=lambda: _now_iso())

    def to_dict(self) -> Dict[str, object]:
        return {
            'node_id': self.node_id,
            'type': self.type,
            'title': self.title,
            'description': self.description,
            'tags': list(self.tags),
            'properties': dict(self.properties),
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> 'Node':
        return cls(
            node_id=str(data['node_id']),
            type=str(data['type']),
            title=str(data.get('title', '')),
            description=str(data.get('description', '')),
            tags=list(data.get('tags', [])),
            properties=dict(data.get('properties', {})),
            created_at=str(data.get('created_at', _now_iso())),
            updated_at=str(data.get('updated_at', _now_iso())),
        )


@dataclass
class Edge:
    edge_id: str
    source_id: str
    target_id: str
    type: str
    strength: float = 0.5
    context: str = ''
    properties: Dict[str, object] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: _now_iso())
    updated_at: str = field(default_factory=lambda: _now_iso())

    def to_dict(self) -> Dict[str, object]:
        return {
            'edge_id': self.edge_id,
            'source_id': self.source_id,
            'target_id': self.target_id,
            'type': self.type,
            'strength': float(self.strength),
            'context': self.context,
            'properties': dict(self.properties),
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> 'Edge':
        return cls(
            edge_id=str(data['edge_id']),
            source_id=str(data['source_id']),
            target_id=str(data['target_id']),
            type=str(data['type']),
            strength=float(data.get('strength', 0.5)),
            context=str(data.get('context', '')),
            properties=dict(data.get('properties', {})),
            created_at=str(data.get('created_at', _now_iso())),
            updated_at=str(data.get('updated_at', _now_iso())),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
