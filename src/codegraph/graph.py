from __future__ import annotations

import hashlib
from typing import Any

from .models import Edge, Evidence, Node, SourceRange


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}
        self.evidence: dict[str, Evidence] = {}

    def add_node(
        self,
        node_id: str,
        kind: str,
        label: str,
        *,
        source_path: str | None = None,
        range: SourceRange | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> str:
        if node_id not in self.nodes:
            self.nodes[node_id] = Node(
                id=node_id,
                kind=kind,
                label=label,
                source_path=source_path,
                range=range,
                attributes=attributes or {},
            )
        return node_id

    def add_evidence(
        self,
        *,
        extractor: str,
        method: str,
        source_locator: str,
        snippet: str,
        confidence: str,
    ) -> str:
        payload = "|".join([extractor, method, source_locator, snippet, confidence])
        evidence_id = "evidence:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
        if evidence_id not in self.evidence:
            self.evidence[evidence_id] = Evidence(
                id=evidence_id,
                extractor=extractor,
                method=method,
                source_locator=source_locator,
                snippet=snippet.strip(),
                confidence=confidence,
            )
        return evidence_id

    def add_edge(
        self,
        *,
        kind: str,
        source: str,
        target: str,
        confidence: str,
        evidence_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> str:
        payload = "|".join([kind, source, target, confidence, evidence_id or ""])
        edge_id = "edge:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
        if edge_id not in self.edges:
            self.edges[edge_id] = Edge(
                id=edge_id,
                kind=kind,
                source=source,
                target=target,
                confidence=confidence,
                evidence_id=evidence_id,
                attributes=attributes or {},
            )
        return edge_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in sorted(self.nodes.values(), key=lambda item: item.id)],
            "edges": [edge.to_dict() for edge in sorted(self.edges.values(), key=lambda item: item.id)],
            "evidence": [
                item.to_dict() for item in sorted(self.evidence.values(), key=lambda item: item.id)
            ],
        }
