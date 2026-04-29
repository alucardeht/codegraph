from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .query import load_graph
from .scanner import (
    MANIFEST_FILE,
    OBSIDIAN_DIR,
    normalize_obsidian_note_path,
    obsidian_reserved_note_paths,
    unique_obsidian_note_paths,
)
from .status import graph_status, load_manifest


ARCHITECTURE_KINDS = {"architecture_root", "area", "domain", "layer", "role", "feature"}
SEMANTIC_SKIP_EDGES = {"contains"}


def graph_overview(output: Path, *, limit: int = 12) -> dict[str, Any]:
    output = output.resolve()
    graph = load_graph(output)
    manifest = load_manifest(output)
    nodes = graph["nodes"]
    edges = graph["edges"]
    nodes_by_id = {node["id"]: node for node in nodes}
    incoming_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        incoming_by_target[edge["to"]].append(edge)
        outgoing_by_source[edge["from"]].append(edge)

    return {
        "target": manifest["target"],
        "output": str(output),
        "freshness": graph_status(output),
        "quality": manifest["quality"],
        "totals": {
            "nodes": len(nodes),
            "edges": len(edges),
            "evidence": len(graph["evidence"]),
            "files": manifest["quality"]["file_count"],
        },
        "node_kinds": dict(Counter(node["kind"] for node in nodes).most_common()),
        "edge_kinds": dict(Counter(edge["kind"] for edge in edges).most_common()),
        "architecture": {
            "areas": architecture_items(nodes, incoming_by_target, "area", limit),
            "domains": architecture_items(nodes, incoming_by_target, "domain", limit),
            "layers": architecture_items(nodes, incoming_by_target, "layer", limit),
            "roles": architecture_items(nodes, incoming_by_target, "role", limit),
            "features": architecture_items(nodes, incoming_by_target, "feature", limit),
        },
        "important_files": important_files(nodes_by_id, incoming_by_target, outgoing_by_source, limit),
        "external_modules": external_modules(nodes_by_id, incoming_by_target, limit),
        "agent_entrypoints": agent_entrypoints(nodes, limit),
        "warnings": overview_warnings(manifest),
    }


def architecture_items(
    nodes: list[dict[str, Any]],
    incoming_by_target: dict[str, list[dict[str, Any]]],
    kind: str,
    limit: int,
) -> list[dict[str, Any]]:
    items = [node for node in nodes if node["kind"] == kind]
    ranked = sorted(
        items,
        key=lambda node: (-linked_file_count(incoming_by_target[node["id"]]), node["id"]),
    )
    return [
        {
            "id": node["id"],
            "label": node["label"],
            "linked_files": linked_file_count(incoming_by_target[node["id"]]),
        }
        for node in ranked[:limit]
    ]


def linked_file_count(edges: list[dict[str, Any]]) -> int:
    return sum(1 for edge in edges if edge["kind"] in {"belongs_to", "categorized_as"})


def important_files(
    nodes_by_id: dict[str, dict[str, Any]],
    incoming_by_target: dict[str, list[dict[str, Any]]],
    outgoing_by_source: dict[str, list[dict[str, Any]]],
    limit: int,
) -> list[dict[str, Any]]:
    files = [node for node in nodes_by_id.values() if node["kind"] == "file"]
    ranked = sorted(
        files,
        key=lambda node: (-semantic_degree(node["id"], incoming_by_target, outgoing_by_source), node["id"]),
    )
    return [file_summary(node, incoming_by_target, outgoing_by_source) for node in ranked[:limit]]


def file_summary(
    node: dict[str, Any],
    incoming_by_target: dict[str, list[dict[str, Any]]],
    outgoing_by_source: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "id": node["id"],
        "path": node["source_path"],
        "domain": node.get("attributes", {}).get("content_domain"),
        "semantic_degree": semantic_degree(node["id"], incoming_by_target, outgoing_by_source),
        "outgoing": edge_kind_counts(outgoing_by_source[node["id"]]),
        "incoming": edge_kind_counts(incoming_by_target[node["id"]]),
    }


def semantic_degree(
    node_id: str,
    incoming_by_target: dict[str, list[dict[str, Any]]],
    outgoing_by_source: dict[str, list[dict[str, Any]]],
) -> int:
    edges = incoming_by_target[node_id] + outgoing_by_source[node_id]
    return sum(1 for edge in edges if edge["kind"] not in SEMANTIC_SKIP_EDGES)


def edge_kind_counts(edges: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(edge["kind"] for edge in edges if edge["kind"] not in SEMANTIC_SKIP_EDGES))


def external_modules(
    nodes_by_id: dict[str, dict[str, Any]],
    incoming_by_target: dict[str, list[dict[str, Any]]],
    limit: int,
) -> list[dict[str, Any]]:
    modules = [node for node in nodes_by_id.values() if node["kind"] == "module"]
    ranked = sorted(
        modules,
        key=lambda node: (-sum(1 for edge in incoming_by_target[node["id"]] if edge["kind"] == "imports"), node["id"]),
    )
    return [
        {
            "id": node["id"],
            "label": node["label"],
            "importing_files": sum(1 for edge in incoming_by_target[node["id"]] if edge["kind"] == "imports"),
        }
        for node in ranked[:limit]
    ]


def agent_entrypoints(nodes: list[dict[str, Any]], limit: int) -> dict[str, list[str]]:
    by_kind = {kind: [] for kind in ("area", "domain", "layer", "role", "feature")}
    for node in sorted(nodes, key=lambda item: item["id"]):
        kind = node["kind"]
        if kind in by_kind and len(by_kind[kind]) < limit:
            by_kind[kind].append(node["id"])
    return by_kind


def overview_warnings(manifest: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    quality = manifest["quality"]
    if quality["status"] != "passed":
        warnings.append(f"quality status is {quality['status']}; inspect quality gates before trusting coverage")
    if quality.get("unsupported_file_count", 0):
        warnings.append(f"{quality['unsupported_file_count']} files were not semantically extracted")
    return warnings


def graph_doctor(output: Path) -> dict[str, Any]:
    output = output.resolve()
    graph = load_graph(output)
    manifest = load_manifest(output)
    node_ids = {node["id"] for node in graph["nodes"]}
    evidence_ids = {item["id"] for item in graph["evidence"]}
    checks = [
        check("ready_marker", (output / ".ready").is_file(), str(output / ".ready")),
        check("graph_file", (output / "graph.json").is_file(), str(output / "graph.json")),
        check("manifest_file", (output / MANIFEST_FILE).is_file(), str(output / MANIFEST_FILE)),
    ]
    missing_endpoints = [
        edge["id"] for edge in graph["edges"] if edge["from"] not in node_ids or edge["to"] not in node_ids
    ]
    missing_evidence = [
        edge["id"]
        for edge in graph["edges"]
        if edge["kind"] != "contains" and not edge.get("evidence_id")
    ]
    broken_evidence_refs = [
        edge["id"]
        for edge in graph["edges"]
        if edge.get("evidence_id") and edge["evidence_id"] not in evidence_ids
    ]
    checks.extend(
        [
            check("edge_endpoints", not missing_endpoints, len(missing_endpoints)),
            check("edge_evidence", not missing_evidence, len(missing_evidence)),
            check("evidence_references", not broken_evidence_refs, len(broken_evidence_refs)),
            check("quality_not_untrusted", manifest["quality"]["status"] != "untrusted", manifest["quality"]["status"]),
        ]
    )
    obsidian_path = output / OBSIDIAN_DIR
    if obsidian_path.exists():
        note_paths = unique_obsidian_note_paths(graph["nodes"])
        duplicates = duplicate_values(note_paths)
        casefold_duplicates = duplicate_normalized_values(note_paths)
        reserved_collisions = [
            note_path
            for note_path in note_paths.values()
            if normalize_obsidian_note_path(note_path)
            in {normalize_obsidian_note_path(path) for path in obsidian_reserved_note_paths()}
        ]
        missing_notes = [
            note_path
            for note_path in note_paths.values()
            if not (obsidian_path / f"{note_path}.md").is_file()
        ]
        checks.extend(
            [
                check("obsidian_note_paths_unique", not duplicates, len(duplicates)),
                check("obsidian_note_paths_unique_casefold", not casefold_duplicates, len(casefold_duplicates)),
                check("obsidian_note_paths_not_reserved", not reserved_collisions, len(reserved_collisions)),
                check("obsidian_notes_present", not missing_notes, len(missing_notes)),
                check("obsidian_graph_settings", (obsidian_path / ".obsidian" / "graph.json").is_file(), "graph.json"),
            ]
        )

    freshness = graph_status(output)
    checks.append(check("freshness_current", freshness["freshness"] == "current", freshness["freshness"]))
    return {
        "output": str(output),
        "target": manifest["target"],
        "status": "passed" if all(item["passed"] for item in checks) else "failed",
        "checks": checks,
        "freshness": freshness,
        "quality": manifest["quality"],
    }


def check(name: str, passed: bool, value: Any) -> dict[str, Any]:
    return {"name": name, "passed": passed, "value": value}


def duplicate_values(values: dict[str, str]) -> dict[str, int]:
    counts = Counter(values.values())
    return {value: count for value, count in counts.items() if count > 1}


def duplicate_normalized_values(values: dict[str, str]) -> dict[str, int]:
    counts = Counter(normalize_obsidian_note_path(value) for value in values.values())
    return {value: count for value, count in counts.items() if count > 1}
