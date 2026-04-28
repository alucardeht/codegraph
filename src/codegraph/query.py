from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from .scanner import GRAPH_FILE, READY_FILE


def load_graph(output: Path) -> dict[str, Any]:
    ready_path = output / READY_FILE
    if not ready_path.is_file():
        raise ValueError(f"Graph is not ready yet: {ready_path}")
    graph_path = output / GRAPH_FILE
    if not graph_path.is_file():
        raise ValueError(f"No graph found at {graph_path}")
    return json.loads(graph_path.read_text(encoding="utf-8"))


def query_subgraph(
    output: Path,
    *,
    node: str,
    depth: int = 1,
    confidence: set[str] | None = None,
    direction: str = "out",
    include_containment: bool = False,
) -> dict[str, Any]:
    graph = load_graph(output.resolve())
    matches = find_nodes(graph, node)
    if not matches:
        return {"matches": [], "nodes": [], "edges": [], "evidence": [], "warnings": ["no matching node"]}
    if len(matches) > 1:
        return {
            "matches": [node_summary(item) for item in matches],
            "nodes": [],
            "edges": [],
            "evidence": [],
            "warnings": ["multiple matching nodes; query by a more specific id or path"],
        }

    root = matches[0]
    allowed_confidence = confidence or {"PROVEN", "DERIVED", "INFERRED", "UNRESOLVED"}
    edge_by_node: dict[str, list[dict[str, Any]]] = {}
    for edge in graph["edges"]:
        if edge["confidence"] not in allowed_confidence:
            continue
        if edge["kind"] == "contains" and not include_containment:
            continue
        if direction in {"out", "both"}:
            edge_by_node.setdefault(edge["from"], []).append(edge)
        if direction in {"in", "both"}:
            edge_by_node.setdefault(edge["to"], []).append(edge)

    visited_nodes = {root["id"]}
    visited_edges: dict[str, dict[str, Any]] = {}
    queue: deque[tuple[str, int]] = deque([(root["id"], 0)])
    while queue:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        for edge in edge_by_node.get(current, []):
            visited_edges[edge["id"]] = edge
            neighbor = edge["to"] if edge["from"] == current else edge["from"]
            if neighbor not in visited_nodes:
                visited_nodes.add(neighbor)
                queue.append((neighbor, current_depth + 1))

    nodes = [item for item in graph["nodes"] if item["id"] in visited_nodes]
    evidence_ids = {
        edge["evidence_id"] for edge in visited_edges.values() if edge.get("evidence_id")
    }
    evidence = [item for item in graph["evidence"] if item["id"] in evidence_ids]
    return {
        "matches": [node_summary(root)],
        "nodes": sorted(nodes, key=lambda item: item["id"]),
        "edges": sorted(visited_edges.values(), key=lambda item: item["id"]),
        "evidence": sorted(evidence, key=lambda item: item["id"]),
        "traversal": {
            "depth": depth,
            "direction": direction,
            "include_containment": include_containment,
            "confidence": sorted(allowed_confidence),
        },
        "warnings": [],
    }


def find_nodes(graph: dict[str, Any], query: str) -> list[dict[str, Any]]:
    for predicate in (
        lambda item: item["id"] == query,
        lambda item: item["kind"] == "file" and item.get("source_path") == query,
        lambda item: item.get("source_path") == query,
        lambda item: item.get("label") == query,
    ):
        exact = [node for node in graph["nodes"] if predicate(node)]
        if len(exact) == 1:
            return exact
        if len(exact) > 1:
            break
    lowered = query.lower()
    return [
        node
        for node in graph["nodes"]
        if lowered in node["id"].lower()
        or lowered in str(node.get("source_path") or "").lower()
        or lowered in str(node.get("label") or "").lower()
    ]


def node_summary(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node["id"],
        "kind": node["kind"],
        "label": node["label"],
        "source_path": node.get("source_path"),
    }
