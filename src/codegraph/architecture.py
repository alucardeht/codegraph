from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .graph import Graph


GENERIC_FEATURE_NAMES = {
    "__tests__",
    "assets",
    "components",
    "config",
    "docs",
    "helpers",
    "hooks",
    "index",
    "layouts",
    "models",
    "modules",
    "navigation",
    "networking",
    "pages",
    "routes",
    "screens",
    "services",
    "shared",
    "src",
    "store",
    "stores",
    "tests",
    "types",
    "utilities",
    "utilityfunctions",
    "utils",
    "widgets",
}


@dataclass(frozen=True)
class FileArchitecture:
    area: str
    layer: str
    role: str
    feature: str | None
    domain: str


def enrich_architecture(graph: Graph) -> None:
    file_nodes = {
        node_id: node
        for node_id, node in graph.nodes.items()
        if node.kind == "file" and node.source_path
    }
    architecture_by_file = {
        node_id: classify_file_architecture(node.source_path or "", node.attributes)
        for node_id, node in file_nodes.items()
    }
    add_architecture_hubs(graph, architecture_by_file)
    add_file_architecture_edges(graph, file_nodes, architecture_by_file)
    add_import_role_edges(graph, architecture_by_file)


def classify_file_architecture(source_path: str, attributes: dict[str, Any]) -> FileArchitecture:
    path = Path(source_path)
    parts = path.parts
    lowered_parts = tuple(part.lower() for part in parts)
    name = path.name
    lowered_name = name.lower()
    domain = str(attributes.get("content_domain") or "unknown")
    area = parts[0] if len(parts) > 1 else "root"
    layer = infer_layer(lowered_parts, lowered_name, domain)
    role = infer_role(lowered_parts, lowered_name, domain)
    feature = infer_feature(parts, lowered_parts, lowered_name, layer, domain)
    return FileArchitecture(area=area, layer=layer, role=role, feature=feature, domain=domain)


def infer_layer(parts: tuple[str, ...], name: str, domain: str) -> str:
    if domain == "documentation":
        return "documentation"
    if domain == "configuration":
        return "configuration"
    if domain == "observability":
        return "observability"
    if domain == "asset":
        return "assets"
    if domain == "test":
        return "tests"
    if "screens" in parts or "pages" in parts or "routes" in parts:
        return "screens"
    if "components" in parts or "widgets" in parts:
        return "components"
    if "hooks" in parts or name.startswith("use"):
        return "hooks"
    if "store" in parts or "stores" in parts or "redux" in parts:
        return "state"
    if "networking" in parts or "api" in parts or "apis" in parts or "services" in parts:
        return "networking"
    if "navigation" in parts or "router" in parts or "routes" in parts:
        return "navigation"
    if "layouts" in parts:
        return "layouts"
    if "modules" in parts or "features" in parts:
        return "features"
    if "models" in parts or "types" in parts or name.endswith(".types.ts"):
        return "models"
    if "utils" in parts or "utilityfunctions" in parts or "helpers" in parts:
        return "utilities"
    return domain if domain != "unknown" else "source"


def infer_role(parts: tuple[str, ...], name: str, domain: str) -> str:
    if domain in {"documentation", "configuration", "observability", "asset", "generated"}:
        return domain
    if domain == "test" or ".test." in name or ".spec." in name:
        return "test"
    if name.endswith(".styles.ts") or name.endswith(".styles.tsx") or name.endswith(".css"):
        return "style"
    if name.endswith(".types.ts") or name.endswith(".types.tsx") or name.endswith(".d.ts"):
        return "type"
    if name.endswith(".schema.ts") or name.endswith(".schemas.ts"):
        return "schema"
    if name.startswith("use") or "hooks" in parts:
        return "hook"
    if "slice" in name or "reducer" in name or "selector" in name or "store" in parts:
        return "state"
    if "api" in name or "apis" in name or "networking" in parts or "services" in parts:
        return "api"
    if "navigation" in parts or "navigator" in name or "router" in name:
        return "navigation"
    if "screens" in parts or name.endswith("screen.tsx") or name.endswith("page.tsx"):
        return "screen"
    if "layouts" in parts or name.endswith("layout.tsx"):
        return "layout"
    if "components" in parts or "widgets" in parts or name.endswith(".tsx") or name.endswith(".jsx"):
        return "component"
    if "models" in parts:
        return "model"
    if "utils" in parts or "utilityfunctions" in parts or "helpers" in parts:
        return "utility"
    return "source"


def infer_feature(
    parts: tuple[str, ...],
    lowered_parts: tuple[str, ...],
    lowered_name: str,
    layer: str,
    domain: str,
) -> str | None:
    if not parts:
        return None
    for marker in ("modules", "features"):
        if marker in lowered_parts:
            index = lowered_parts.index(marker)
            if index + 1 < len(parts):
                return normalized_feature_name(parts[index + 1])
    for marker in ("screens", "pages", "routes"):
        if marker in lowered_parts:
            index = lowered_parts.index(marker)
            if index + 1 < len(parts):
                candidate = parts[index + 1]
                return normalized_feature_name(candidate)
    for marker in ("components", "widgets"):
        if marker in lowered_parts:
            index = lowered_parts.index(marker)
            if index + 1 < len(parts):
                return normalized_feature_name(parts[index + 1])
    if len(parts) > 2 and lowered_parts[0] in {"src", "app", "lib"}:
        candidate = normalized_feature_name(parts[1])
        if candidate and candidate.lower() not in GENERIC_FEATURE_NAMES:
            return candidate
    if domain in {"documentation", "configuration"} and len(parts) > 2:
        return normalized_feature_name(parts[0])
    if lowered_name in {"readme.md", "package.json", "pyproject.toml"}:
        return "project"
    return None


def add_architecture_hubs(graph: Graph, architecture_by_file: dict[str, FileArchitecture]) -> None:
    graph.add_node("arch:project", "architecture_root", "Project Architecture")
    areas = sorted({item.area for item in architecture_by_file.values()})
    domains = sorted({item.domain for item in architecture_by_file.values()})
    layers = sorted({item.layer for item in architecture_by_file.values()})
    roles = sorted({item.role for item in architecture_by_file.values()})
    features = sorted({item.feature for item in architecture_by_file.values() if item.feature})
    for area in areas:
        graph.add_node(f"area:{area}", "area", area)
        add_architecture_edge(graph, "part_of", f"area:{area}", "arch:project", "area")
    for domain in domains:
        graph.add_node(f"domain:{domain}", "domain", domain)
        add_architecture_edge(graph, "part_of", f"domain:{domain}", "arch:project", "domain")
    for layer in layers:
        graph.add_node(f"layer:{layer}", "layer", layer)
        add_architecture_edge(graph, "part_of", f"layer:{layer}", "arch:project", "layer")
    for role in roles:
        graph.add_node(f"role:{role}", "role", role)
        add_architecture_edge(graph, "part_of", f"role:{role}", "arch:project", "role")
    for feature in features:
        graph.add_node(f"feature:{feature}", "feature", feature)
        add_architecture_edge(graph, "part_of", f"feature:{feature}", "arch:project", "feature")


def add_file_architecture_edges(
    graph: Graph,
    file_nodes: dict[str, Any],
    architecture_by_file: dict[str, FileArchitecture],
) -> None:
    for node_id, node in file_nodes.items():
        architecture = architecture_by_file[node_id]
        source_path = node.source_path or node_id
        add_architecture_edge(graph, "belongs_to", node_id, f"area:{architecture.area}", source_path)
        add_architecture_edge(graph, "belongs_to", node_id, f"domain:{architecture.domain}", source_path)
        add_architecture_edge(graph, "belongs_to", node_id, f"layer:{architecture.layer}", source_path)
        add_architecture_edge(graph, "categorized_as", node_id, f"role:{architecture.role}", source_path)
        if architecture.feature:
            add_architecture_edge(graph, "belongs_to", node_id, f"feature:{architecture.feature}", source_path)


def add_import_role_edges(graph: Graph, architecture_by_file: dict[str, FileArchitecture]) -> None:
    edges = list(graph.edges.values())
    for edge in edges:
        if edge.kind != "imports":
            continue
        source_architecture = architecture_by_file.get(edge.source)
        target_architecture = architecture_by_file.get(edge.target)
        if not source_architecture or not target_architecture:
            continue
        kind = relationship_for_import_target(target_architecture)
        if not kind:
            continue
        add_architecture_edge(graph, kind, edge.source, edge.target, edge.id)


def relationship_for_import_target(target: FileArchitecture) -> str | None:
    if target.role == "hook":
        return "uses_hook"
    if target.role == "state":
        return "uses_state"
    if target.role == "api" or target.layer == "networking":
        return "calls_api"
    if target.role == "style":
        return "styled_by"
    if target.role == "type":
        return "typed_by"
    if target.role == "test":
        return "tested_by"
    if target.role == "component":
        return "uses_component"
    return None


def add_architecture_edge(
    graph: Graph,
    kind: str,
    source: str,
    target: str,
    evidence_hint: str,
) -> None:
    evidence_id = graph.add_evidence(
        extractor="architecture.enrichment",
        method=kind,
        source_locator=evidence_hint,
        snippet=f"{source} {kind} {target}",
        confidence="INFERRED",
    )
    graph.add_edge(
        kind=kind,
        source=source,
        target=target,
        confidence="INFERRED",
        evidence_id=evidence_id,
    )


def remove_extension(value: str) -> str:
    for suffix in (".tsx", ".jsx", ".ts", ".js", ".py", ".md"):
        if value.lower().endswith(suffix):
            return value[: -len(suffix)]
    return value


def normalized_feature_name(value: str) -> str | None:
    candidate = remove_extension(value)
    if not candidate:
        return None
    if candidate.lower() in GENERIC_FEATURE_NAMES:
        return None
    return candidate
