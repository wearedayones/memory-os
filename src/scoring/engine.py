from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..graph.engine import KnowledgeGraph
from ..graph.ontology import Edge, Node


class ScoringEngine:
    """
    Dynamic scoring engine for memory items.

    Combines:
    - importance
    - confidence
    - frequency
    - recency
    - relationship strength
    - retrieval count
    """

    def __init__(self, graph: Optional[KnowledgeGraph] = None):
        if graph is None:
            graph = KnowledgeGraph()
        self.graph = graph
        self.retrieval_counts: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Component helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _recency_score(timestamp: str, max_hours: float = 720.0) -> float:
        try:
            dt = datetime.fromisoformat(timestamp)
        except Exception:
            return 0.0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_hours = max((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 0.0)
        exponent = -age_hours / ((max_hours / 2.0) if max_hours else 720.0)
        return round(float((1.0 - max_hours / 100.0) + (max_hours / 100.0) * pow(2.0, exponent)), 6)

    def _frequency_score(self, text: str) -> float:
        keyword_index_path = self.graph.base_dir.parent / 'index' / 'keywords.json'
        if not keyword_index_path.exists():
            return 0.0
        try:
            import json
            data = json.loads(keyword_index_path.read_text())
            keywords = data.get('keywords', {})
        except Exception:
            return 0.0
        total = 0
        for word in [w.lower() for w in text.split() if len(w) > 2]:
            if word in keywords:
                total += keywords[word].get('count', 0)
        # Normalize into [0, 1] using a simple log compression.
        return round(min(total / 50.0, 1.0), 6)

    def _relationship_strength_score(self, node_id: str) -> float:
        strengths = []
        for edge in self.graph.edges.values():
            if edge.source_id == node_id or edge.target_id == node_id:
                strengths.append(max(0.0, min(1.0, float(edge.strength))))
        if not strengths:
            return 0.0
        return round(min(sum(strengths) / len(strengths) * 1.2, 1.0), 6)

    def _retrieval_count_score(self, node_id: str) -> float:
        count = self.retrieval_counts.get(node_id, 0)
        return round(min(count / 20.0, 1.0), 6)

    # ------------------------------------------------------------------
    # Scoring API
    # ------------------------------------------------------------------
    def score_node(
        self,
        node_id: str,
        *,
        importance: Optional[float] = None,
        confidence: Optional[float] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        node = self.graph.get_node(node_id)
        if node is None:
            raise KeyError(f'Node not found: {node_id}')

        weights = weights or {
            'importance': 0.18,
            'confidence': 0.15,
            'frequency': 0.15,
            'recency': 0.15,
            'relationship_strength': 0.17,
            'retrieval_count': 0.20,
        }

        freq = self._frequency_score(f"{node.title} {node.description}")
        recency = self._recency_score(node.updated_at)
        rel_strength = self._relationship_strength_score(node_id)
        retrieval_score = self._retrieval_count_score(node_id)

        score_map = {
            'importance': float(max(0.0, min(1.0, node.properties.get('importance', importance or 0.5)))),
            'confidence': float(max(0.0, min(1.0, node.properties.get('confidence', confidence or 0.5)))),
            'frequency': freq,
            'recency': recency,
            'relationship_strength': rel_strength,
            'retrieval_count': retrieval_score,
        }

        final = round(sum(score_map[k] * weights.get(k, 0.16) for k in score_map), 6)

        record = {
            'node_id': node_id,
            'type': node.type,
            'final_score': final,
            'scores': score_map,
            'weights': weights,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        return record

    def score_edge(self, edge_id: str, *, weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        edge = self.graph.get_edge(edge_id)
        if edge is None:
            raise KeyError(f'Edge not found: {edge_id}')

        weights = weights or {
            'type_weight': 0.2,
            'relationship_strength': 0.35,
            'recency': 0.2,
            'retrieval_count': 0.15,
            'confidence': 0.1,
        }

        scores = {
            'relationship_strength': round(max(0.0, min(1.0, float(edge.strength))), 6),
            'recency': self._recency_score(edge.updated_at),
            'retrieval_count': self._retrieval_count_score(edge.edge_id),
            'confidence': round(max(0.0, min(1.0, float(edge.properties.get('confidence', 0.5)))), 6),
            'type_weight': 1.0 if edge.type in {'created', 'knows', 'member_of'} else 0.6,
        }

        final = round(sum(scores[k] * weights.get(k, 0.2) for k in scores), 6)
        return {
            'edge_id': edge_id,
            'type': edge.type,
            'final_score': final,
            'scores': scores,
            'weights': weights,
        }

    def increment_retrieval_count(self, node_id: str, delta: int = 1) -> None:
        self.retrieval_counts[node_id] = self.retrieval_counts.get(node_id, 0) + delta

    def rank_nodes(
        self,
        node_ids: List[str],
        *,
        weights: Optional[Dict[str, float]] = None,
    ) -> List[Tuple[str, float]]:
        scored = []
        for nid in node_ids:
            try:
                record = self.score_node(nid, weights=weights)
                scored.append((nid, record['final_score']))
            except KeyError:
                pass
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def get_node(self, node_id: str, *, importance: Optional[float] = None, confidence: Optional[float] = None) -> Optional[Node]:
        return self.graph.get_node(node_id)


class DynamicScorer:
    """Thin alias to the scoring engine for an opinionated default configuration."""

    def __init__(self, graph: Optional[KnowledgeGraph] = None):
        self.engine = ScoringEngine(graph=graph)

    def score(self, node_id: str, **kwargs: Any) -> Dict[str, Any]:
        return self.engine.score_node(node_id, **kwargs)

    def rank(self, node_ids: List[str], **kwargs: Any) -> List[Tuple[str, float]]:
        return self.engine.rank_nodes(node_ids, **kwargs)
