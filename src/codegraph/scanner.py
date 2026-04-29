from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .architecture import enrich_architecture
from .config import ImportAlias, config_fingerprint, load_codegraph_config
from .extractors import classify_content_domain, extract_file_content, extractor_declarations_payload
from .graph import Graph
from .ignore import IgnorePolicy
from .models import Edge, Evidence, Node, SourceRange, utc_now


GRAPH_FILE = "graph.json"
MANIFEST_FILE = "manifest.json"
REPORT_FILE = "report.md"
OBSIDIAN_DIR = "obsidian"
READY_FILE = ".ready"
EXTRACTION_CACHE_DIR = "cache/extractions"
EXTRACTION_CACHE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ScanOptions:
    target: Path
    output: Path
    include: tuple[str, ...] = ()
    disable_default_ignore: tuple[str, ...] = ()
    no_default_ignores: bool = False
    allow_output_inside_target: bool = False
    export_obsidian: bool = False
    replace_output: bool = False
    config: Path | None = None
    incremental: bool = False
    allow_existing_output: bool = False


def scan(options: ScanOptions) -> dict[str, Any]:
    target = options.target.resolve()
    output = options.output.resolve()
    validate_scan_paths(target, output, options.allow_output_inside_target)
    prepare_output_directory(
        output,
        replace_output=options.replace_output,
        allow_existing_output=options.allow_existing_output or options.incremental,
    )
    mark_not_ready(output)

    started_at = utc_now()
    previous_manifest = load_existing_manifest(output) if options.incremental else None
    config = load_codegraph_config(target, options.config)
    include = tuple(config.include) + options.include
    disable_default_ignore = tuple(config.disable_default_ignore) + options.disable_default_ignore
    no_default_ignores = options.no_default_ignores or config.no_default_ignores
    runtime_ignore = runtime_ignore_patterns(target, output)
    policy = IgnorePolicy(
        target=target,
        include=list(include),
        disable_default=list(disable_default_ignore),
        no_default_ignores=no_default_ignores,
        runtime_ignore=runtime_ignore,
    )
    graph = Graph()
    graph.add_node(
        "collection:target",
        "collection",
        target.name or str(target),
        source_path=".",
        attributes={"absolute_path": str(target)},
    )

    skipped: list[dict[str, str]] = []
    files = discover_files(target, policy, skipped)
    fingerprints = fingerprint_files_incremental(
        target,
        files,
        previous_manifest.get("source_fingerprints", {}) if previous_manifest else {},
    )
    internal_package_aliases = discover_internal_package_aliases(target, files)
    import_aliases = config.import_aliases + internal_package_aliases
    refresh_plan = incremental_refresh_plan(
        previous_manifest,
        config_fingerprint(config),
        import_aliases,
        fingerprints,
    )

    directory_nodes: set[str] = set()
    extraction_results: list[dict[str, object]] = []
    cache_stats = {"reused": 0, "written": 0, "missed": 0}
    for file_path in files:
        relative = file_path.relative_to(target).as_posix()
        add_directory_containment(graph, relative, directory_nodes)
        file_node = f"file:{relative}"
        graph.add_node(
            file_node,
            "file",
            Path(relative).name,
            source_path=relative,
            attributes={
                "content_domain": classify_content_domain(Path(relative)),
                "extension": file_path.suffix.lower(),
                "size": fingerprints[relative]["size"],
                "sha256": fingerprints[relative]["sha256"],
            },
        )
        parent = parent_node_id(relative)
        graph.add_edge(kind="contains", source=parent, target=file_node, confidence="PROVEN")
        extraction_payload = None
        if refresh_plan["mode"] == "incremental":
            extraction_payload = read_extraction_cache(
                output,
                relative,
                fingerprints[relative],
                import_aliases,
            )
        if extraction_payload is None:
            if refresh_plan["mode"] == "incremental":
                cache_stats["missed"] += 1
            file_graph = Graph()
            extraction_result = extract_file_content(
                file_graph,
                target,
                file_path,
                import_aliases=import_aliases,
            ).to_dict()
            extraction_payload = extraction_cache_payload(
                relative,
                fingerprints[relative],
                import_aliases,
                file_graph,
                extraction_result,
            )
            write_extraction_cache(output, relative, extraction_payload)
            cache_stats["written"] += 1
        else:
            cache_stats["reused"] += 1
        merge_graph_payload(graph, extraction_payload["graph"])
        extraction_results.append(dict(extraction_payload["extraction_result"]))

    enrich_architecture(
        graph,
        feature_markers=config.feature_markers,
        generic_feature_names=config.generic_feature_names,
    )

    ended_at = utc_now()
    graph_payload = {
        "schema_version": 1,
        "generated_at": ended_at,
        **graph.to_dict(),
    }
    quality = quality_summary(graph_payload, target, files, skipped, extraction_results)
    manifest = {
        "schema_version": 1,
        "tool": "codegraph",
        "started_at": started_at,
        "ended_at": ended_at,
        "target": str(target),
        "output": str(output),
        "freshness": "current",
        "scan_options": {
            "include": list(options.include),
            "disable_default_ignore": list(options.disable_default_ignore),
            "no_default_ignores": options.no_default_ignores,
            "allow_output_inside_target": options.allow_output_inside_target,
            "export_obsidian": options.export_obsidian,
            "replace_output": options.replace_output,
            "config": str(config.path) if config.path else None,
            "incremental": options.incremental,
        },
        "effective_scan_options": {
            "include": list(include),
            "disable_default_ignore": list(disable_default_ignore),
            "no_default_ignores": no_default_ignores,
        },
        "config": config.to_dict(),
        "internal_package_aliases": [item.to_dict() for item in internal_package_aliases],
        "effective_import_aliases": import_aliases_payload(import_aliases),
        "config_fingerprint": config_fingerprint(config),
        "extractor_declarations": extractor_declarations_payload(),
        "refresh": {
            **refresh_plan,
            "cache": cache_stats,
        },
        "ignore_policy": policy.to_dict(),
        "source_fingerprints": fingerprints,
        "extraction_results": extraction_results,
        "skipped": skipped,
        "quality": quality,
    }

    write_json(output / GRAPH_FILE, graph_payload)
    write_json(output / MANIFEST_FILE, manifest)
    write_text_atomic(output / REPORT_FILE, render_report(manifest, graph_payload))
    if options.export_obsidian:
        write_obsidian_export(output / OBSIDIAN_DIR, graph_payload, manifest)
    mark_ready(output)
    return manifest


def prepare_output_directory(
    output: Path,
    *,
    replace_output: bool = False,
    allow_existing_output: bool = False,
) -> None:
    if not output.exists():
        output.mkdir(parents=True)
        return
    if not output.is_dir():
        raise ValueError(f"Output path exists and is not a directory: {output}")
    if replace_output:
        shutil.rmtree(output)
        output.mkdir(parents=True)
        return
    if not any(output.iterdir()):
        return
    if allow_existing_output and is_managed_output(output):
        return
    raise ValueError(
        "Output path is not empty. Choose an empty directory or pass "
        "--replace-output to delete and recreate the entire output directory."
    )


def is_managed_output(output: Path) -> bool:
    return (output / MANIFEST_FILE).is_file() and (output / GRAPH_FILE).is_file()


def validate_scan_paths(target: Path, output: Path, allow_inside: bool) -> None:
    if not target.exists():
        raise ValueError(f"Target does not exist: {target}")
    if not target.is_dir():
        raise ValueError(f"Target must be a directory: {target}")
    if output == target:
        raise ValueError("Output path must not be the target directory.")
    if not allow_inside:
        try:
            output.relative_to(target)
        except ValueError:
            return
        raise ValueError(
            "Output path is inside the target. Choose an external output path or pass "
            "--allow-output-inside-target explicitly."
        )


def runtime_ignore_patterns(target: Path, output: Path) -> list[str]:
    try:
        return [output.relative_to(target).as_posix()]
    except ValueError:
        return []


def discover_files(target: Path, policy: IgnorePolicy, skipped: list[dict[str, str]]) -> list[Path]:
    discovered: list[Path] = []
    for root, dirnames, filenames in os.walk(target):
        root_path = Path(root)
        kept_dirs: list[str] = []
        for dirname in sorted(dirnames):
            path = root_path / dirname
            relative = path.relative_to(target).as_posix()
            decision = policy.decide(relative, is_dir=True)
            if decision.ignored:
                skipped.append({"path": relative, "reason": decision.reason or "ignored"})
            else:
                kept_dirs.append(dirname)
        dirnames[:] = kept_dirs

        for filename in sorted(filenames):
            path = root_path / filename
            relative = path.relative_to(target).as_posix()
            decision = policy.decide(relative, is_dir=False)
            if decision.ignored:
                skipped.append({"path": relative, "reason": decision.reason or "ignored"})
                continue
            if path.is_file():
                discovered.append(path)
    return discovered


def fingerprint_files(target: Path, files: list[Path]) -> dict[str, dict[str, Any]]:
    fingerprints: dict[str, dict[str, Any]] = {}
    for file_path in files:
        relative = file_path.relative_to(target).as_posix()
        stat = file_path.stat()
        fingerprints[relative] = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256_file(file_path),
        }
    return fingerprints


def fingerprint_files_incremental(
    target: Path,
    files: list[Path],
    previous: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    fingerprints: dict[str, dict[str, Any]] = {}
    for file_path in files:
        relative = file_path.relative_to(target).as_posix()
        stat = file_path.stat()
        prior = previous.get(relative, {})
        if prior.get("size") == stat.st_size and prior.get("mtime_ns") == stat.st_mtime_ns:
            fingerprints[relative] = dict(prior)
            continue
        fingerprints[relative] = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256_file(file_path),
        }
    return fingerprints


def load_existing_manifest(output: Path) -> dict[str, Any] | None:
    manifest_path = output / MANIFEST_FILE
    if not manifest_path.is_file():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def incremental_refresh_plan(
    previous_manifest: dict[str, Any] | None,
    current_config_fingerprint: dict[str, int] | None,
    import_aliases: tuple[ImportAlias, ...],
    current_fingerprints: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if previous_manifest is None:
        return {"mode": "full", "reason": "no_previous_manifest"}
    previous_fingerprints = previous_manifest.get("source_fingerprints", {})
    added = sorted(set(current_fingerprints) - set(previous_fingerprints))
    deleted = sorted(set(previous_fingerprints) - set(current_fingerprints))
    changed = sorted(
        path
        for path in set(current_fingerprints) & set(previous_fingerprints)
        if current_fingerprints[path].get("sha256") != previous_fingerprints[path].get("sha256")
    )
    if added:
        return {"mode": "full", "reason": "added_files", "added": added, "deleted": deleted, "changed": changed}
    if deleted:
        return {"mode": "full", "reason": "deleted_files", "added": added, "deleted": deleted, "changed": changed}
    if previous_manifest.get("config_fingerprint") != current_config_fingerprint:
        return {"mode": "full", "reason": "config_changed", "added": added, "deleted": deleted, "changed": changed}
    if previous_manifest.get("effective_import_aliases") != import_aliases_payload(import_aliases):
        return {
            "mode": "full",
            "reason": "import_aliases_changed",
            "added": added,
            "deleted": deleted,
            "changed": changed,
        }
    return {"mode": "incremental", "reason": "compatible_cache", "added": added, "deleted": deleted, "changed": changed}


def import_aliases_payload(import_aliases: tuple[ImportAlias, ...]) -> list[dict[str, str]]:
    return [item.to_dict() for item in import_aliases]


def extraction_cache_payload(
    relative: str,
    fingerprint: dict[str, Any],
    import_aliases: tuple[ImportAlias, ...],
    graph: Graph,
    extraction_result: dict[str, object],
) -> dict[str, Any]:
    return {
        "schema_version": EXTRACTION_CACHE_SCHEMA_VERSION,
        "source_path": relative,
        "fingerprint": dict(fingerprint),
        "import_aliases": import_aliases_payload(import_aliases),
        "graph": graph.to_dict(),
        "extraction_result": extraction_result,
    }


def read_extraction_cache(
    output: Path,
    relative: str,
    fingerprint: dict[str, Any],
    import_aliases: tuple[ImportAlias, ...],
) -> dict[str, Any] | None:
    cache_path = extraction_cache_path(output, relative)
    if not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("schema_version") != EXTRACTION_CACHE_SCHEMA_VERSION:
        return None
    if payload.get("source_path") != relative:
        return None
    if payload.get("fingerprint", {}).get("sha256") != fingerprint.get("sha256"):
        return None
    if payload.get("import_aliases") != import_aliases_payload(import_aliases):
        return None
    if not isinstance(payload.get("graph"), dict) or not isinstance(payload.get("extraction_result"), dict):
        return None
    return payload


def write_extraction_cache(output: Path, relative: str, payload: dict[str, Any]) -> None:
    cache_path = extraction_cache_path(output, relative)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(cache_path, payload)


def extraction_cache_path(output: Path, relative: str) -> Path:
    digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()
    return output / EXTRACTION_CACHE_DIR / f"{digest}.json"


def merge_graph_payload(graph: Graph, payload: dict[str, Any]) -> None:
    for item in payload.get("nodes", []):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        graph.nodes[item["id"]] = Node(
            id=item["id"],
            kind=str(item.get("kind", "unknown")),
            label=str(item.get("label", item["id"])),
            source_path=item.get("source_path") if isinstance(item.get("source_path"), str) else None,
            range=source_range_from_payload(item.get("range")),
            attributes=item.get("attributes") if isinstance(item.get("attributes"), dict) else {},
        )
    for item in payload.get("evidence", []):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        graph.evidence[item["id"]] = Evidence(
            id=item["id"],
            extractor=str(item.get("extractor", "unknown")),
            method=str(item.get("method", "unknown")),
            source_locator=str(item.get("source_locator", "")),
            snippet=str(item.get("snippet", "")),
            confidence=str(item.get("confidence", "UNRESOLVED")),
            captured_at=str(item.get("captured_at", utc_now())),
        )
    for item in payload.get("edges", []):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        source = item.get("from")
        target = item.get("to")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        graph.edges[item["id"]] = Edge(
            id=item["id"],
            kind=str(item.get("kind", "references")),
            source=source,
            target=target,
            confidence=str(item.get("confidence", "UNRESOLVED")),
            evidence_id=item.get("evidence_id") if isinstance(item.get("evidence_id"), str) else None,
            attributes=item.get("attributes") if isinstance(item.get("attributes"), dict) else {},
        )


def source_range_from_payload(payload: Any) -> SourceRange | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("start_line"), int):
        return None
    return SourceRange(
        start_line=payload["start_line"],
        start_column=int(payload.get("start_column") or 1),
        end_line=payload.get("end_line") if isinstance(payload.get("end_line"), int) else None,
        end_column=payload.get("end_column") if isinstance(payload.get("end_column"), int) else None,
    )


def discover_internal_package_aliases(target: Path, files: list[Path]) -> tuple[ImportAlias, ...]:
    aliases: list[ImportAlias] = []
    seen: set[tuple[str, str]] = set()
    for file_path in files:
        if file_path.name != "package.json":
            continue
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        package_dir = file_path.parent
        exact_target = package_entry_target(target, package_dir, payload)
        wildcard_base = package_wildcard_base(target, package_dir)
        for alias in (
            ImportAlias(name.strip(), exact_target),
            ImportAlias(f"{name.strip()}/*", f"{wildcard_base}/*"),
        ):
            key = (alias.pattern, alias.target)
            if key in seen:
                continue
            seen.add(key)
            aliases.append(alias)
    return tuple(aliases)


def package_entry_target(target: Path, package_dir: Path, payload: dict[str, Any]) -> str:
    for key in ("source", "module", "main", "types"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = package_dir / value
        if candidate.exists() or candidate.with_suffix(".ts").exists() or candidate.with_suffix(".tsx").exists():
            return candidate.relative_to(target).as_posix()
    src_dir = package_dir / "src"
    if src_dir.is_dir():
        return src_dir.relative_to(target).as_posix()
    return package_dir.relative_to(target).as_posix()


def package_wildcard_base(target: Path, package_dir: Path) -> str:
    src_dir = package_dir / "src"
    if src_dir.is_dir():
        return src_dir.relative_to(target).as_posix()
    return package_dir.relative_to(target).as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_directory_containment(graph: Graph, relative_file: str, seen: set[str]) -> None:
    parts = Path(relative_file).parts[:-1]
    parent = "collection:target"
    current_parts: list[str] = []
    for part in parts:
        current_parts.append(part)
        path = Path(*current_parts).as_posix()
        node_id = f"dir:{path}"
        if node_id not in seen:
            graph.add_node(node_id, "directory", part, source_path=path)
            graph.add_edge(kind="contains", source=parent, target=node_id, confidence="PROVEN")
            seen.add(node_id)
        parent = node_id


def parent_node_id(relative_file: str) -> str:
    parent = Path(relative_file).parent
    if parent == Path("."):
        return "collection:target"
    return f"dir:{parent.as_posix()}"


def quality_summary(
    graph_payload: dict[str, Any],
    target: Path,
    files: list[Path],
    skipped: list[dict[str, str]],
    extraction_results: list[dict[str, object]],
) -> dict[str, Any]:
    node_ids = {node["id"] for node in graph_payload["nodes"]}
    evidence_ids = {item["id"] for item in graph_payload["evidence"]}
    edge_without_evidence = [
        edge["id"]
        for edge in graph_payload["edges"]
        if edge["kind"] not in {"contains"} and not edge.get("evidence_id")
    ]
    missing_endpoints = [
        edge["id"]
        for edge in graph_payload["edges"]
        if edge["from"] not in node_ids or edge["to"] not in node_ids
    ]
    missing_evidence_refs = [
        edge["id"]
        for edge in graph_payload["edges"]
        if edge.get("evidence_id") and edge["evidence_id"] not in evidence_ids
    ]
    invalid_source_paths = [
        node["id"]
        for node in graph_payload["nodes"]
        if node.get("kind") in {"file", "section", "function", "class"}
        and node.get("source_path")
        and not (target / node["source_path"]).exists()
    ]
    unsupported_files = [item for item in extraction_results if not item["supported"]]
    extractor_failures = [item for item in extraction_results if item.get("error")]
    low_information_supported_files = [
        item
        for item in extraction_results
        if item["supported"]
        and not item.get("error")
        and item["node_count"] == 0
        and item["relationship_edge_count"] == 0
    ]
    relationship_edges = [edge for edge in graph_payload["edges"] if edge["kind"] != "contains"]
    semantic_components = semantic_component_summary(graph_payload)
    content_domain_counts = Counter(str(item["content_domain"]) for item in extraction_results)
    unsupported_by_domain = Counter(str(item["content_domain"]) for item in unsupported_files)
    relationship_edges_by_kind = Counter(edge["kind"] for edge in relationship_edges)
    nodes_by_kind = Counter(node["kind"] for node in graph_payload["nodes"])
    extractors = Counter(str(item["extractor"]) for item in extraction_results)
    supported_file_count = len(extraction_results) - len(unsupported_files)
    supported_ratio = safe_ratio(supported_file_count, len(extraction_results))
    semantic_edge_density = safe_ratio(len(relationship_edges), len(files))
    low_information_ratio = safe_ratio(len(low_information_supported_files), supported_file_count)
    gates = [
        quality_gate("edge_endpoints", len(missing_endpoints) == 0, len(missing_endpoints)),
        quality_gate("edge_evidence", len(edge_without_evidence) == 0, len(edge_without_evidence)),
        quality_gate("evidence_references", len(missing_evidence_refs) == 0, len(missing_evidence_refs)),
        quality_gate("source_paths", len(invalid_source_paths) == 0, len(invalid_source_paths)),
        quality_gate("extractor_failures", len(extractor_failures) == 0, len(extractor_failures)),
        quality_gate("supported_ratio", supported_ratio >= 0.70, round(supported_ratio, 4)),
        quality_gate("semantic_edge_density", semantic_edge_density >= 0.75, round(semantic_edge_density, 4)),
        quality_gate("low_information_ratio", low_information_ratio <= 0.10, round(low_information_ratio, 4)),
    ]
    critical_failed = any(
        not gate["passed"]
        for gate in gates
        if gate["name"]
        in {
            "edge_endpoints",
            "edge_evidence",
            "evidence_references",
            "source_paths",
            "extractor_failures",
        }
    )
    if critical_failed or (
        supported_file_count > 0 and (supported_ratio < 0.35 or semantic_edge_density < 0.10)
    ):
        status = "untrusted"
    elif any(not gate["passed"] for gate in gates):
        status = "partial"
    else:
        status = "passed"
    return {
        "status": status,
        "file_count": len(files),
        "skipped_count": len(skipped),
        "node_count": len(graph_payload["nodes"]),
        "edge_count": len(graph_payload["edges"]),
        "evidence_count": len(graph_payload["evidence"]),
        "edge_without_evidence_count": len(edge_without_evidence),
        "missing_edge_endpoint_count": len(missing_endpoints),
        "missing_evidence_reference_count": len(missing_evidence_refs),
        "invalid_source_path_count": len(invalid_source_paths),
        "supported_file_count": supported_file_count,
        "unsupported_file_count": len(unsupported_files),
        "extractor_failure_count": len(extractor_failures),
        "low_information_supported_file_count": len(low_information_supported_files),
        "supported_file_ratio": round(supported_ratio, 4),
        "semantic_edge_count": len(relationship_edges),
        "semantic_edge_density": round(semantic_edge_density, 4),
        "semantic_component_count": semantic_components["component_count"],
        "semantic_largest_component_size": semantic_components["largest_component_size"],
        "semantic_singleton_count": semantic_components["singleton_count"],
        "semantic_singleton_ratio": semantic_components["singleton_ratio"],
        "content_domain_counts": dict(sorted(content_domain_counts.items())),
        "unsupported_by_domain": dict(sorted(unsupported_by_domain.items())),
        "relationship_edges_by_kind": dict(sorted(relationship_edges_by_kind.items())),
        "nodes_by_kind": dict(sorted(nodes_by_kind.items())),
        "extractors": dict(sorted(extractors.items())),
        "quality_gates": gates,
    }


def quality_gate(name: str, passed: bool, value: Any) -> dict[str, Any]:
    return {"name": name, "passed": passed, "value": value}


def safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return numerator / denominator


def semantic_component_summary(graph_payload: dict[str, Any]) -> dict[str, Any]:
    node_ids = {node["id"] for node in graph_payload["nodes"]}
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph_payload["edges"]:
        if edge["kind"] == "contains":
            continue
        if edge["from"] not in node_ids or edge["to"] not in node_ids:
            continue
        adjacency[edge["from"]].add(edge["to"])
        adjacency[edge["to"]].add(edge["from"])
    seen: set[str] = set()
    sizes: list[int] = []
    for node_id in node_ids:
        if node_id in seen:
            continue
        queue: deque[str] = deque([node_id])
        seen.add(node_id)
        size = 0
        while queue:
            current = queue.popleft()
            size += 1
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        sizes.append(size)
    largest = max(sizes, default=0)
    singletons = sum(1 for size in sizes if size == 1)
    return {
        "component_count": len(sizes),
        "largest_component_size": largest,
        "singleton_count": singletons,
        "singleton_ratio": round(safe_ratio(singletons, len(sizes)), 4),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def mark_not_ready(output: Path) -> None:
    ready = output / READY_FILE
    if ready.exists():
        ready.unlink()


def mark_ready(output: Path) -> None:
    write_text_atomic(output / READY_FILE, utc_now() + "\n")


def render_report(manifest: dict[str, Any], graph_payload: dict[str, Any]) -> str:
    quality = manifest["quality"]
    return "\n".join(
        [
            "# Codegraph Report",
            "",
            f"- Target: `{manifest['target']}`",
            f"- Output: `{manifest['output']}`",
            f"- Freshness: `{manifest['freshness']}`",
            f"- Quality: `{quality['status']}`",
            f"- Files indexed: {quality['file_count']}",
            f"- Paths skipped: {quality['skipped_count']}",
            f"- Nodes: {len(graph_payload['nodes'])}",
            f"- Edges: {len(graph_payload['edges'])}",
            f"- Evidence records: {len(graph_payload['evidence'])}",
            f"- Supported file ratio: {quality['supported_file_ratio']}",
            f"- Semantic edge density: {quality['semantic_edge_density']}",
            f"- Semantic components: {quality['semantic_component_count']}",
            f"- Semantic singletons: {quality['semantic_singleton_count']}",
            "",
            "## Quality Gates",
            "",
            *[
                f"- {gate['name']}: {'pass' if gate['passed'] else 'fail'} "
                f"({gate['value']})"
                for gate in quality["quality_gates"]
            ],
            "",
            "## Trust Notes",
            "",
            "- Non-containment edges are expected to carry evidence records.",
            "- Stale graphs must be refreshed or treated as advisory.",
            "- Human exports are generated from the canonical graph output.",
            "",
        ]
    )


def write_obsidian_export(path: Path, graph_payload: dict[str, Any], manifest: dict[str, Any]) -> None:
    final_path = path
    path = final_path.with_name(f".{final_path.name}.tmp")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    (path / ".obsidian").mkdir(exist_ok=True)
    write_json(path / ".obsidian" / "graph.json", obsidian_graph_settings())

    node_note_paths = unique_obsidian_note_paths(graph_payload["nodes"])
    nodes_by_id = {node["id"]: node for node in graph_payload["nodes"]}
    outgoing_edges: dict[str, list[dict[str, Any]]] = {}
    incoming_edges: dict[str, list[dict[str, Any]]] = {}
    for edge in graph_payload["edges"]:
        outgoing_edges.setdefault(edge["from"], []).append(edge)
        incoming_edges.setdefault(edge["to"], []).append(edge)

    (path / "index.md").write_text(
        "\n".join(
            [
                "# Codegraph Overview",
                "",
                f"Target: `{manifest['target']}`",
                f"Freshness: `{manifest['freshness']}`",
                f"Quality: `{manifest['quality']['status']}`",
                f"Nodes: {len(graph_payload['nodes'])}",
                f"Edges: {len(graph_payload['edges'])}",
                "",
                "## Navigation",
                "",
                "- [[Dashboards/Architecture|Architecture Dashboard]]",
                "- [[Dashboards/Entrypoints|Entrypoints Dashboard]]",
                "- [[Dashboards/Features|Feature Dashboard]]",
                "- [[Dashboards/Layers|Layer Dashboard]]",
                "- [[Dashboards/Research|Research Dashboard]]",
                "- [[Indexes/Architecture|Architecture]]",
                "- [[Indexes/Features|Features]]",
                "- [[Indexes/Layers|Layers]]",
                "- [[Indexes/Roles|Roles]]",
                "- [[Indexes/Domains|Domains]]",
                "- [[Indexes/Files|Files]]",
                "- [[Indexes/Symbols|Symbols]]",
                "- [[Indexes/Modules|Modules]]",
                "- [[Indexes/Concepts|Concepts]]",
                "- [[Indexes/Claims|Claims]]",
                "- [[Indexes/Assets|Assets]]",
                "- [[Indexes/Artifacts|Artifacts]]",
                "- [[Indexes/Config|Config]]",
                "- [[Indexes/Observability|Observability]]",
                "- [[Indexes/Directories|Directories]]",
                "- [[Indexes/Other|Other]]",
                "",
                "## Quality",
                "",
                *[
                    f"- {key}: `{value}`"
                    for key, value in sorted(manifest["quality"].items())
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )

    write_obsidian_indexes(path, graph_payload, node_note_paths)
    write_obsidian_dashboards(path, graph_payload, node_note_paths)
    for node in graph_payload["nodes"]:
        note_relative = node_note_paths[node["id"]]
        note_path = path / f"{note_relative}.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(
            render_obsidian_node_note(
                node,
                nodes_by_id,
                node_note_paths,
                outgoing_edges.get(node["id"], []),
                incoming_edges.get(node["id"], []),
            ),
            encoding="utf-8",
        )
    replace_directory(path, final_path)


def replace_directory(source: Path, destination: Path) -> None:
    backup = destination.with_name(f".{destination.name}.old")
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        destination.rename(backup)
    source.rename(destination)
    if backup.exists():
        shutil.rmtree(backup)


def safe_note_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in value)


def unique_obsidian_note_paths(nodes: list[dict[str, Any]]) -> dict[str, str]:
    paths = {node["id"]: obsidian_note_path(node) for node in nodes}
    grouped: dict[str, list[str]] = defaultdict(list)
    for node_id, path in paths.items():
        grouped[path].append(node_id)
    for path, node_ids in grouped.items():
        if len(node_ids) == 1:
            continue
        for node_id in sorted(node_ids):
            paths[node_id] = f"{path}__{safe_note_name(node_id)}"
    return paths


def note_line_suffix(node: dict[str, Any]) -> str:
    if node.get("range") and node["range"].get("start_line"):
        return f"_L{node['range']['start_line']}"
    return ""


def obsidian_note_path(node: dict[str, Any]) -> str:
    label = node["source_path"] or node["label"] or node["id"]
    name = safe_note_name(label)
    kind = node["kind"]
    if kind == "file":
        return f"Files/{name}"
    if kind == "directory":
        return f"Directories/{name}"
    if kind in {"function", "class"}:
        symbol_name = safe_note_name(node["label"] or node["id"])
        return f"Symbols/{name}__{symbol_name}{note_line_suffix(node)}"
    if kind == "module":
        return f"Modules/{name}"
    if kind == "imported_symbol":
        module = safe_note_name(str(node.get("attributes", {}).get("module", "module")))
        symbol = safe_note_name(node["label"] or node["id"])
        return f"Modules/{module}__{symbol}"
    if kind == "asset_file":
        return f"Assets/{name}"
    if kind == "artifact":
        return f"Artifacts/{name}"
    if kind == "config_file":
        return f"Config/{name}"
    if kind == "config_key":
        key_name = safe_note_name(node["label"] or node["id"])
        return f"Config/{name}__{key_name}{note_line_suffix(node)}"
    if kind == "log_file":
        return f"Observability/{name}"
    if kind == "log_statement":
        statement_name = safe_note_name(node["label"] or node["id"])
        return f"Observability/{name}__{statement_name}{note_line_suffix(node)}"
    if kind in {"architecture_root", "area", "domain", "layer", "role", "feature"}:
        return f"Architecture/{safe_note_name(kind)}/{name}"
    if kind == "section":
        section_name = safe_note_name(node["label"] or node["id"])
        return f"Docs/{name}__{section_name}{note_line_suffix(node)}"
    if kind == "reference":
        return f"Docs/{name}"
    if kind == "concept":
        return f"Concepts/{name}"
    if kind == "claim":
        claim_name = safe_note_name(node["label"] or node["id"])
        return f"Claims/{name}__{claim_name}{note_line_suffix(node)}"
    return f"Other/{safe_note_name(kind)}/{name}"


def render_obsidian_node_note(
    node: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
    node_note_paths: dict[str, str],
    outgoing_edges: list[dict[str, Any]],
    incoming_edges: list[dict[str, Any]],
) -> str:
    title = node["source_path"] or node["label"] or node["id"]
    lines = [
        f"# {title}",
        "",
        f"- Kind: `{node['kind']}`",
        f"- Node ID: `{node['id']}`",
    ]
    if node.get("source_path"):
        lines.append(f"- Source: `{node['source_path']}`")
    if node.get("range"):
        start_line = node["range"].get("start_line")
        if start_line:
            lines.append(f"- Start line: `{start_line}`")
    lines.extend(["", "## Outgoing", ""])
    lines.extend(render_obsidian_edge_links(outgoing_edges, nodes_by_id, node_note_paths, target_key="to"))
    lines.extend(["", "## Incoming", ""])
    lines.extend(render_obsidian_edge_links(incoming_edges, nodes_by_id, node_note_paths, target_key="from"))
    lines.append("")
    return "\n".join(lines)


def render_obsidian_edge_links(
    edges: list[dict[str, Any]],
    nodes_by_id: dict[str, dict[str, Any]],
    node_note_paths: dict[str, str],
    *,
    target_key: str,
) -> list[str]:
    if not edges:
        return ["- None"]
    lines: list[str] = []
    for edge in sorted(edges, key=lambda item: (item["kind"], item[target_key])):
        target_id = edge[target_key]
        target_node = nodes_by_id.get(target_id)
        target_path = node_note_paths.get(target_id)
        label = target_node["source_path"] or target_node["label"] if target_node else target_id
        if target_path and edge["kind"] != "contains":
            target = f"[[{target_path}|{label}]]"
        else:
            target = f"`{target_id}`"
        lines.append(f"- `{edge['kind']}` -> {target} ({edge['confidence']})")
    return lines


def write_obsidian_indexes(
    path: Path,
    graph_payload: dict[str, Any],
    node_note_paths: dict[str, str],
) -> None:
    index_specs = {
        "Architecture": {"architecture_root", "area", "domain", "layer", "role", "feature"},
        "Features": {"feature"},
        "Layers": {"layer"},
        "Roles": {"role"},
        "Domains": {"domain"},
        "Files": {"file"},
        "Symbols": {"function", "class"},
        "Modules": {"module"},
        "Concepts": {"concept"},
        "Claims": {"claim"},
        "Assets": {"asset_file"},
        "Artifacts": {"artifact"},
        "Config": {"config_file", "config_key"},
        "Observability": {"log_file", "log_statement"},
        "Directories": {"directory"},
    }
    indexed_kinds = set().union(*index_specs.values())
    indexes_dir = path / "Indexes"
    indexes_dir.mkdir(exist_ok=True)
    for title, kinds in index_specs.items():
        write_obsidian_index(indexes_dir / f"{title}.md", title, graph_payload, node_note_paths, kinds)
    write_obsidian_index(
        indexes_dir / "Other.md",
        "Other",
        graph_payload,
        node_note_paths,
        None,
        exclude_kinds=indexed_kinds,
    )


def write_obsidian_dashboards(
    path: Path,
    graph_payload: dict[str, Any],
    node_note_paths: dict[str, str],
) -> None:
    dashboards_dir = path / "Dashboards"
    dashboards_dir.mkdir(exist_ok=True)
    incoming_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph_payload["edges"]:
        incoming_by_target[edge["to"]].append(edge)
        outgoing_by_source[edge["from"]].append(edge)
    nodes_by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in graph_payload["nodes"]:
        nodes_by_kind[node["kind"]].append(node)

    write_entrypoints_dashboard(
        dashboards_dir / "Entrypoints.md",
        graph_payload,
        node_note_paths,
        nodes_by_kind,
        incoming_by_target,
        outgoing_by_source,
    )
    write_architecture_dashboard(
        dashboards_dir / "Architecture.md",
        graph_payload,
        node_note_paths,
        nodes_by_kind,
        incoming_by_target,
    )
    write_ranked_architecture_dashboard(
        dashboards_dir / "Features.md",
        "Features",
        nodes_by_kind["feature"],
        node_note_paths,
        incoming_by_target,
    )
    write_ranked_architecture_dashboard(
        dashboards_dir / "Layers.md",
        "Layers",
        nodes_by_kind["layer"],
        node_note_paths,
        incoming_by_target,
    )
    write_research_dashboard(
        dashboards_dir / "Research.md",
        nodes_by_kind,
        node_note_paths,
        incoming_by_target,
    )


def write_architecture_dashboard(
    path: Path,
    graph_payload: dict[str, Any],
    node_note_paths: dict[str, str],
    nodes_by_kind: dict[str, list[dict[str, Any]]],
    incoming_by_target: dict[str, list[dict[str, Any]]],
) -> None:
    lines = [
        "# Architecture Dashboard",
        "",
        f"- Nodes: {len(graph_payload['nodes'])}",
        f"- Edges: {len(graph_payload['edges'])}",
        f"- Areas: {len(nodes_by_kind['area'])}",
        f"- Domains: {len(nodes_by_kind['domain'])}",
        f"- Layers: {len(nodes_by_kind['layer'])}",
        f"- Roles: {len(nodes_by_kind['role'])}",
        f"- Features: {len(nodes_by_kind['feature'])}",
        "",
    ]
    for title, kind in (
        ("Top Areas", "area"),
        ("Top Domains", "domain"),
        ("Top Layers", "layer"),
        ("Top Roles", "role"),
        ("Top Features", "feature"),
    ):
        lines.extend([f"## {title}", ""])
        lines.extend(
            render_ranked_architecture_links(
                nodes_by_kind[kind],
                node_note_paths,
                incoming_by_target,
                limit=15,
            )
        )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_ranked_architecture_dashboard(
    path: Path,
    title: str,
    nodes: list[dict[str, Any]],
    node_note_paths: dict[str, str],
    incoming_by_target: dict[str, list[dict[str, Any]]],
) -> None:
    lines = [f"# {title}", ""]
    lines.extend(render_ranked_architecture_links(nodes, node_note_paths, incoming_by_target, limit=None))
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_entrypoints_dashboard(
    path: Path,
    graph_payload: dict[str, Any],
    node_note_paths: dict[str, str],
    nodes_by_kind: dict[str, list[dict[str, Any]]],
    incoming_by_target: dict[str, list[dict[str, Any]]],
    outgoing_by_source: dict[str, list[dict[str, Any]]],
) -> None:
    lines = [
        "# Entrypoints Dashboard",
        "",
        "## Agent Sequence",
        "",
        "- Run `status` before trusting the graph.",
        "- Run `doctor` before using the graph for planning.",
        "- Start with architecture, feature, layer, and important file entrypoints.",
        "- Use focused source inspection after the graph narrows the area.",
        "",
        "## Top Features",
        "",
    ]
    lines.extend(
        render_ranked_architecture_links(
            nodes_by_kind["feature"],
            node_note_paths,
            incoming_by_target,
            limit=12,
        )
    )
    lines.extend(["", "## Top Layers", ""])
    lines.extend(
        render_ranked_architecture_links(
            nodes_by_kind["layer"],
            node_note_paths,
            incoming_by_target,
            limit=12,
        )
    )
    lines.extend(["", "## Important Files", ""])
    lines.extend(
        render_ranked_file_links(
            nodes_by_kind["file"],
            node_note_paths,
            incoming_by_target,
            outgoing_by_source,
            limit=20,
        )
    )
    lines.extend(["", "## External Modules", ""])
    lines.extend(
        render_ranked_links(
            nodes_by_kind["module"],
            node_note_paths,
            incoming_by_target,
            edge_kinds={"imports"},
            empty_label="None",
            limit=20,
            suffix="importing edges",
        )
    )
    if nodes_by_kind["concept"] or nodes_by_kind["claim"]:
        lines.extend(["", "## Research", ""])
        lines.append("- [[Dashboards/Research|Research Dashboard]]")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_research_dashboard(
    path: Path,
    nodes_by_kind: dict[str, list[dict[str, Any]]],
    node_note_paths: dict[str, str],
    incoming_by_target: dict[str, list[dict[str, Any]]],
) -> None:
    lines = [
        "# Research Dashboard",
        "",
        f"- Concepts: {len(nodes_by_kind['concept'])}",
        f"- Claims: {len(nodes_by_kind['claim'])}",
        "",
        "## Top Concepts",
        "",
    ]
    lines.extend(
        render_ranked_links(
            nodes_by_kind["concept"],
            node_note_paths,
            incoming_by_target,
            edge_kinds={"mentions"},
            empty_label="None",
            limit=20,
            suffix="mentions",
        )
    )
    lines.extend(["", "## Top Claims", ""])
    lines.extend(
        render_ranked_links(
            nodes_by_kind["claim"],
            node_note_paths,
            incoming_by_target,
            edge_kinds={"contains"},
            empty_label="None",
            limit=20,
            suffix="source links",
        )
    )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def render_ranked_file_links(
    files: list[dict[str, Any]],
    node_note_paths: dict[str, str],
    incoming_by_target: dict[str, list[dict[str, Any]]],
    outgoing_by_source: dict[str, list[dict[str, Any]]],
    *,
    limit: int,
) -> list[str]:
    ranked = sorted(
        files,
        key=lambda node: (
            -semantic_edge_count(node["id"], incoming_by_target, outgoing_by_source),
            node["id"],
        ),
    )[:limit]
    if not ranked:
        return ["- None"]
    return [
        f"- [[{node_note_paths[node['id']]}|{node['source_path']}]] "
        f"({semantic_edge_count(node['id'], incoming_by_target, outgoing_by_source)} semantic edges)"
        for node in ranked
    ]


def semantic_edge_count(
    node_id: str,
    incoming_by_target: dict[str, list[dict[str, Any]]],
    outgoing_by_source: dict[str, list[dict[str, Any]]],
) -> int:
    edges = incoming_by_target[node_id] + outgoing_by_source[node_id]
    return sum(1 for edge in edges if edge["kind"] != "contains")


def render_ranked_links(
    nodes: list[dict[str, Any]],
    node_note_paths: dict[str, str],
    incoming_by_target: dict[str, list[dict[str, Any]]],
    *,
    edge_kinds: set[str],
    empty_label: str,
    limit: int | None,
    suffix: str,
) -> list[str]:
    ranked = sorted(
        nodes,
        key=lambda node: (-edge_kind_count(incoming_by_target[node["id"]], edge_kinds), node["id"]),
    )
    if limit is not None:
        ranked = ranked[:limit]
    if not ranked:
        return [f"- {empty_label}"]
    return [
        f"- [[{node_note_paths[node['id']]}|{node['label']}]] "
        f"({edge_kind_count(incoming_by_target[node['id']], edge_kinds)} {suffix})"
        for node in ranked
    ]


def render_ranked_architecture_links(
    nodes: list[dict[str, Any]],
    node_note_paths: dict[str, str],
    incoming_by_target: dict[str, list[dict[str, Any]]],
    *,
    limit: int | None,
) -> list[str]:
    ranked = sorted(
        nodes,
        key=lambda node: (-architecture_link_count(incoming_by_target[node["id"]]), node["id"]),
    )
    if limit is not None:
        ranked = ranked[:limit]
    if not ranked:
        return ["- None"]
    return [
        f"- [[{node_note_paths[node['id']]}|{node['label']}]] "
        f"({architecture_link_count(incoming_by_target[node['id']])} linked files)"
        for node in ranked
    ]


def architecture_link_count(edges: list[dict[str, Any]]) -> int:
    return sum(1 for edge in edges if edge["kind"] in {"belongs_to", "categorized_as"})


def edge_kind_count(edges: list[dict[str, Any]], kinds: set[str]) -> int:
    return sum(1 for edge in edges if edge["kind"] in kinds)


def write_obsidian_index(
    path: Path,
    title: str,
    graph_payload: dict[str, Any],
    node_note_paths: dict[str, str],
    kinds: set[str] | None,
    *,
    exclude_kinds: set[str] | None = None,
) -> None:
    lines = [f"# {title}", ""]
    for node in sorted(graph_payload["nodes"], key=lambda item: item["id"]):
        if kinds is not None and node["kind"] not in kinds:
            continue
        if exclude_kinds is not None and node["kind"] in exclude_kinds:
            continue
        label = node["source_path"] or node["label"] or node["id"]
        lines.append(f"- [[{node_note_paths[node['id']]}|{label}]]")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def obsidian_graph_settings() -> dict[str, Any]:
    return {
        "collapse-filter": False,
        "search": "path:Architecture OR path:Files",
        "showTags": False,
        "showAttachments": False,
        "hideUnresolved": True,
        "showOrphans": False,
        "collapse-color-groups": False,
        "colorGroups": [
            {"query": "path:Files", "color": {"a": 1, "rgb": 3896054}},
            {"query": "path:Symbols", "color": {"a": 1, "rgb": 2286942}},
            {"query": "path:Modules", "color": {"a": 1, "rgb": 16096779}},
            {"query": "path:Directories", "color": {"a": 1, "rgb": 9749432}},
            {"query": "path:Docs", "color": {"a": 1, "rgb": 11032055}},
            {"query": "path:Assets", "color": {"a": 1, "rgb": 53380}},
            {"query": "path:Artifacts", "color": {"a": 1, "rgb": 8947848}},
            {"query": "path:Other", "color": {"a": 1, "rgb": 15970423}},
            {"query": "path:Architecture", "color": {"a": 1, "rgb": 16766720}},
        ],
        "collapse-display": False,
        "showArrow": True,
        "textFadeMultiplier": -1,
        "nodeSizeMultiplier": 1,
        "lineSizeMultiplier": 1,
        "collapse-forces": False,
        "centerStrength": 0.35,
        "repelStrength": 13,
        "linkStrength": 1,
        "linkDistance": 250,
        "scale": 1,
        "close": False,
    }
