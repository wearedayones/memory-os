from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from ..graph.engine import KnowledgeGraph
from ..graph.ontology import VALID_NODE_TYPES


class RetrievalEngine:
    """
    Retrieval subsystem for the memory/graph system.

    Supports:
    - keyword similarity
    - tag similarity
    - entity matching
    - relationship expansion
    """

    def __init__(self, graph: Optional[KnowledgeGraph] = None):
        if graph is None:
            graph = KnowledgeGraph()
        self.graph = graph

    def keyword_similarity(self, query: str, node: Any) -> float:
        q_lower = query.lower()
        text = f"{getattr(node, 'title', '')} {getattr(node, 'description', '')} {' '.join(getattr(node, 'tags', []))}".lower()
        if not text.strip():
            return 0.0
        q_words = [w for w in q_lower.split() if len(w) > 2]
        if not q_words:
            return 1.0 if q_lower in text else 0.0
        hits = sum(1 for w in q_words if w in text)
        return hits / len(q_words)

    def tag_similarity(self, query_tags: List[str], node: Any) -> float:
        q_tags = {t.lower() for t in query_tags if t}
        node_tags = {t.lower() for t in getattr(node, 'tags', [])}
        if not q_tags or not node_tags:
            return 0.0
        overlap = q_tags & node_tags
        if not overlap:
            return 0.0
        return len(overlap) / len(q_tags | node_tags)

    def entity_match(self, keyword: str, node_type: Optional[str] = None) -> List[Tuple[Any, float]]:
        candidates = filter(lambda n: n.type == node_type, self.graph.nodes.values()) if node_type else self.graph.nodes.values()
        scored = []
        for node in candidates:
            sim = self.keyword_similarity(keyword, node)
            if sim > 0.0:
                scored.append((node, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def relationship_expansion(
        self,
        node_id: str,
        max_hops: int = 2,
        direction: str = 'both',
    ) -> List[Tuple[Any, int, List[Any]]]:
        return self.graph.multi_hop(node_id, max_hops=max_hops, direction=direction)

    def search(
        self,
        query: str,
        *,
        node_type: Optional[str] = None,
        max_hops: int = 2,
        expand_relationships: bool = True,
        top_k: int = 20,
    ) -> List[Tuple[Any, float, List[Any]]]:
        if node_type and node_type not in VALID_NODE_TYPES:
            raise ValueError(f'Invalid node type: {node_type!r}')

        query_parts = [part.strip() for part in query.split(',')]
        query_tags = [part for part in query_parts if part.startswith('#')]
        query_keywords = query.replace(',', ' ').replace('#', ' ').strip()

        candidates = filter(lambda n: n.type == node_type, self.graph.nodes.values()) if node_type else self.graph.nodes.values()
        fused: List[Tuple[Any, float]] = []
        seen: set = set()
        for node in candidates:
            if node.node_id in seen:
                continue
            seen.add(node.node_id)
            keyword_sim = self.keyword_similarity(query_keywords, node)
            tag_sim = self.tag_similarity(query_tags, node)
            score = max(keyword_sim, tag_sim)
            if score <= 0:
                continue
            fused.append((node, score))

        fused.sort(key=lambda x: x[1], reverse=True)
        top = fused[: max(top_k // (1 if expand_relationships else max_hops * 2), top_k)]
        results: List[Tuple[Any, float, List[Any]]] = []
        for node, score in top:
            if expand_relationships:
                expanded = self.relationship_expansion(node.node_id, max_hops=max_hops)
            else:
                expanded = [(node, 0, [])]
            for expanded_node, hop_count, path_edges in expanded:
                rel_boost = max(0.0, 1.0 - (0.15 * hop_count))
                results.append((expanded_node, score * rel_boost, path_edges))

        results.sort(key=lambda x: (-x[1], x[0].node_id))
        return results[:top_k]

    def find_similar_nodes(self, node_id: str, *, top_k: int = 10) -> List[Tuple[Any, float]]:
        node = self.graph.get_node(node_id)
        if node is None:
            return []
        q_tags = list(getattr(node, 'tags', []))
        q_text = f"{getattr(node, 'title', '')} {getattr(node, 'description', '')}"
        candidates = [n for n in self.graph.nodes.values() if n.node_id != node_id]
        scored = []
        for candidate in candidates:
            score = max(
                self.keyword_similarity(q_text, candidate),
                self.tag_similarity(q_tags, candidate),
            )
            if score > 0:
                scored.append((candidate, score))
        scored.sort(key=lambda x: (-x[1], x[0].node_id))
        return scored[:top_k]

    def by_tag(self, tag: str, *, node_type: Optional[str] = None, top_k: int = 20) -> List[Any]:
        tag_lower = tag.lower()
        matches = []
        for node in self.graph.nodes.values():
            if node_type and node.type != node_type:
                continue
            if any(t.lower() == tag_lower for t in getattr(node, 'tags', [])):
                matches.append(node)
        return matches[:top_k]


class HybridRetriever:
    """
    Opinionated retriever that combines a graph with free-text query scoring.
    """

    def __init__(self, graph: Optional[KnowledgeGraph] = None, retrieval: Optional[RetrievalEngine] = None):
        self.graph = graph or KnowledgeGraph()
        self.retrieval = retrieval or RetrievalEngine(graph=self.graph)

    def query(
        self,
        text: str,
        *,
        top_k: int = 10,
        keywords: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        min_keyword_score: float = 0.1,
    ) -> List[Dict[str, Any]]:
        keywords = keywords or []
        tags = tags or []
        results = self.retrieval.search(text, top_k=top_k * 2)
        filtered = [r for r in results if r[1] >= min_keyword_score]
        filtered = filtered[:top_k]
        payload = []
        for node, score, path in filtered:
            payload.append({
                'node_id': node.node_id,
                'type': node.type,
                'title': node.title,
                'score': score,
                'hop_distance': len(path),
                'tags': node.tags,
            })
        return payload
