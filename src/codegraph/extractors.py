from __future__ import annotations

import ast
from dataclasses import dataclass, field
import re
from pathlib import Path

from .config import ImportAlias
from .graph import Graph
from .models import SourceRange


MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdx"}
CONFIG_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".env"}
CONFIG_FILENAMES = {
    ".editorconfig",
    ".env",
    ".gitignore",
    ".npmrc",
    ".nvmrc",
    ".prettierignore",
    ".prettierrc",
    "dockerfile",
    "makefile",
}
LOCKFILE_FILENAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "cargo.lock",
    "gemfile.lock",
    "poetry.lock",
}
LOG_EXTENSIONS = {".log"}
ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".pdf"}
JS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
CODE_EXTENSIONS = {
    ".py",
    *JS_EXTENSIONS,
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
    ".rb",
    ".php",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".sh",
}

MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
MARKDOWN_REFERENCE_LINK_RE = re.compile(r"\[([^\]]+)\]\[([^\]]+)\]")
MARKDOWN_REFERENCE_SHORTCUT_RE = re.compile(r"(?<!\!)\[([^\]]+)\]\[\]")
MARKDOWN_REFERENCE_DEFINITION_RE = re.compile(r"^\s*\[([^\]]+)\]:\s*(\S+)(?:\s+\"([^\"]+)\")?\s*$")
MARKDOWN_FOOTNOTE_REFERENCE_RE = re.compile(r"\[\^([^\]]+)\]")
MARKDOWN_FOOTNOTE_DEFINITION_RE = re.compile(r"^\s*\[\^([^\]]+)\]:\s*(.+)$")
MARKDOWN_HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z][A-Za-z0-9_-]{2,})")
MARKDOWN_KEY_TERM_RE = re.compile(r"`([^`\n]{3,80})`|\*\*([^*\n]{3,80})\*\*")
MARKDOWN_CLAIM_RE = re.compile(
    r"\b(supports?|contradicts?|depends on|requires|enables|prevents|derived from)\b",
    re.IGNORECASE,
)
STOP_CONCEPTS = {
    "and",
    "are",
    "but",
    "can",
    "for",
    "from",
    "into",
    "the",
    "this",
    "that",
    "with",
    "note",
    "notes",
    "section",
    "sections",
    "concept",
    "concepts",
    "method",
    "methods",
}
CONFIG_KEY_RE = re.compile(r"^\s*[\"']?([A-Za-z_][\w.-]*)[\"']?\s*[:=]")
LOG_LEVEL_RE = re.compile(r"\b(DEBUG|INFO|WARN|WARNING|ERROR|FATAL|TRACE)\b", re.IGNORECASE)
PY_IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import\s+(.+)|import\s+(.+))")
JS_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+(?:type\s+)?(?:.+?\s+from\s+)?[\"']([^\"']+)[\"']|export\s+(?:type\s+)?.+?\s+from\s+[\"']([^\"']+)[\"']|(?:const|let|var)\s+.+?=\s+require\([\"']([^\"']+)[\"']\))"
)
JS_IMPORT_DETAIL_RE = re.compile(r"^\s*import\s+(?:type\s+)?(.+?)\s+from\s+[\"']([^\"']+)[\"']")
JS_IMPORT_FROM_RE = re.compile(
    r"^\s*import\s+(?P<type>type\s+)?(?P<specifier>.+?)\s+from\s+[\"'](?P<module>[^\"']+)[\"']",
    re.DOTALL,
)
JS_SIDE_EFFECT_IMPORT_RE = re.compile(r"^\s*import\s+[\"'](?P<module>[^\"']+)[\"']")
JS_EXPORT_FROM_RE = re.compile(
    r"^\s*export\s+(?P<type>type\s+)?(?P<specifier>.+?)\s+from\s+[\"'](?P<module>[^\"']+)[\"']",
    re.DOTALL,
)
JS_REQUIRE_RE = re.compile(
    r"^\s*(?:const|let|var)\s+(?P<specifier>.+?)\s*=\s*require\([\"'](?P<module>[^\"']+)[\"']\)",
    re.DOTALL,
)
JS_DYNAMIC_IMPORT_RE = re.compile(r"\bimport\(\s*[\"']([^\"']+)[\"']\s*\)")
JS_REQUIRE_RESOLVE_RE = re.compile(r"\brequire\.resolve\(\s*[\"']([^\"']+)[\"']\s*\)")
JS_COMMONJS_EXPORT_REQUIRE_RE = re.compile(
    r"^\s*(?P<target>module\.exports|exports\.[A-Za-z_$][\w$]*)\s*=\s*require\(\s*[\"'](?P<module>[^\"']+)[\"']\s*\)"
)
JS_COMMONJS_EXPORT_LOCAL_RE = re.compile(
    r"^\s*(?P<target>module\.exports|exports\.[A-Za-z_$][\w$]*)\s*=\s*(?P<name>[A-Za-z_$][\w$]*)\s*;?\s*$"
)
JS_JSX_COMPONENT_RE = re.compile(r"<\s*([A-Z][A-Za-z0-9_$]*)\b")
PY_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)\s*\(")
PY_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][\w]*)\b")
JS_FUNC_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\(?[A-Za-z_$,\s]*\)?\s*=>|\()"
)
JS_CLASS_RE = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)\b")
JS_EXPORTED_LOCAL_RE = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("
    r"|^\s*export\s+(?:default\s+)?class\s+([A-Za-z_$][\w$]*)\b"
    r"|^\s*export\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)\b"
)


@dataclass(frozen=True)
class ExtractionResult:
    source_path: str
    extractor: str
    supported: bool
    content_domain: str
    node_count: int = 0
    edge_count: int = 0
    evidence_count: int = 0
    relationship_edge_count: int = 0
    node_kinds: tuple[str, ...] = ()
    edge_kinds: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "extractor": self.extractor,
            "supported": self.supported,
            "content_domain": self.content_domain,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "evidence_count": self.evidence_count,
            "relationship_edge_count": self.relationship_edge_count,
            "node_kinds": list(self.node_kinds),
            "edge_kinds": list(self.edge_kinds),
            "error": self.error,
        }


@dataclass(frozen=True)
class ExtractorDeclaration:
    extractor: str
    content_domains: tuple[str, ...]
    node_kinds: tuple[str, ...]
    edge_kinds: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "extractor": self.extractor,
            "content_domains": list(self.content_domains),
            "node_kinds": list(self.node_kinds),
            "edge_kinds": list(self.edge_kinds),
        }


@dataclass(frozen=True)
class JsModuleStatement:
    line_number: int
    snippet: str
    module: str
    names: list[str]
    edge_kind: str
    bind_names: bool
    method: str


@dataclass
class ExtractionContext:
    import_resolution_cache: dict[tuple[str, str, tuple[tuple[str, str], ...]], Path | None] = field(
        default_factory=dict
    )
    candidate_resolution_cache: dict[str, Path | None] = field(default_factory=dict)
    normalized_path_case_cache: dict[str, Path] = field(default_factory=dict)


EXTRACTOR_DECLARATIONS = (
    ExtractorDeclaration(
        "markdown",
        ("documentation",),
        ("claim", "concept", "reference", "section"),
        ("contains", "mentions", "references", "cites", "supports", "contradicts", "depends_on", "derived_from"),
    ),
    ExtractorDeclaration(
        "config.lexical",
        ("configuration",),
        ("config_file", "config_key"),
        ("configures", "defines"),
    ),
    ExtractorDeclaration(
        "log.lexical",
        ("observability",),
        ("log_file", "log_statement"),
        ("diagnoses", "emits_log"),
    ),
    ExtractorDeclaration(
        "asset.metadata",
        ("asset",),
        ("asset_file",),
        ("stores_asset",),
    ),
    ExtractorDeclaration(
        "artifact.metadata",
        ("generated",),
        ("artifact", "lockfile"),
        ("generated_from",),
    ),
    ExtractorDeclaration(
        "python.ast",
        ("code", "test"),
        ("class", "function", "module", "imported_symbol"),
        ("calls", "contains", "defines", "exports", "imports", "depends_on"),
    ),
    ExtractorDeclaration(
        "code.lexical",
        ("code", "test"),
        ("class", "function", "module", "imported_symbol", "symbol"),
        ("contains", "defines", "exports", "imports", "renders"),
    ),
)


def extractor_declarations_payload() -> list[dict[str, object]]:
    return [item.to_dict() for item in EXTRACTOR_DECLARATIONS]


def extract_file_content(
    graph: Graph,
    target: Path,
    file_path: Path,
    *,
    import_aliases: tuple[ImportAlias, ...] = (),
    context: ExtractionContext | None = None,
) -> ExtractionResult:
    context = context or ExtractionContext()
    relative = file_path.relative_to(target).as_posix()
    suffix = file_path.suffix.lower()
    content_domain = classify_content_domain(Path(relative))
    if not is_supported_file(file_path):
        return ExtractionResult(relative, "none", supported=False, content_domain=content_domain)

    before_nodes = len(graph.nodes)
    before_edges = len(graph.edges)
    before_evidence = len(graph.evidence)
    extractor = extractor_id(file_path)
    try:
        if suffix in MARKDOWN_EXTENSIONS:
            extract_markdown(graph, file_path, relative)
        elif content_domain == "configuration":
            extract_config(graph, file_path, relative)
        elif content_domain == "observability":
            extract_log(graph, file_path, relative)
        elif content_domain == "asset":
            extract_asset(graph, file_path, relative)
        elif content_domain == "generated":
            extract_generated_artifact(graph, file_path, relative)
        elif suffix == ".py":
            extract_python_ast(graph, target, file_path, relative, import_aliases=import_aliases, context=context)
        else:
            extract_code_lexical(graph, target, file_path, relative, import_aliases=import_aliases, context=context)
    except OSError as error:
        return ExtractionResult(
            relative,
            extractor,
            supported=True,
            content_domain=content_domain,
            error=str(error),
        )

    new_nodes = list(graph.nodes.values())[before_nodes:]
    new_edges = list(graph.edges.values())[before_edges:]
    relationship_edges = [edge for edge in new_edges if edge.kind != "contains"]
    return ExtractionResult(
        relative,
        extractor,
        supported=True,
        content_domain=content_domain,
        node_count=len(graph.nodes) - before_nodes,
        edge_count=len(graph.edges) - before_edges,
        evidence_count=len(graph.evidence) - before_evidence,
        relationship_edge_count=len(relationship_edges),
        node_kinds=tuple(sorted({node.kind for node in new_nodes})),
        edge_kinds=tuple(sorted({edge.kind for edge in new_edges})),
    )


def classify_content_domain(path: Path) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    if (
        "generated" in parts
        or suffix in {".lock", ".patch"}
        or name.endswith(".lock")
        or name in LOCKFILE_FILENAMES
        or name == ".gitkeep"
    ):
        return "generated"
    if suffix in ASSET_EXTENSIONS:
        return "asset"
    if suffix in LOG_EXTENSIONS:
        return "observability"
    if (
        suffix in CONFIG_EXTENSIONS
        or name in CONFIG_FILENAMES
        or name.endswith("rc")
        or name.startswith(".env")
        or ".husky" in parts
    ):
        return "configuration"
    if suffix in MARKDOWN_EXTENSIONS:
        return "documentation"
    if suffix in CODE_EXTENSIONS:
        if "__tests__" in parts or "tests" in parts or ".test." in name or ".spec." in name:
            return "test"
        return "code"
    return "unknown"


def is_supported_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    name = path.name.lower()
    domain = classify_content_domain(path)
    return (
        suffix in MARKDOWN_EXTENSIONS
        or suffix in CODE_EXTENSIONS
        or suffix in CONFIG_EXTENSIONS
        or suffix in LOG_EXTENSIONS
        or name in CONFIG_FILENAMES
        or name.endswith("rc")
        or domain in {"asset", "configuration", "generated"}
    )


def extractor_id(path: Path) -> str:
    suffix = path.suffix.lower()
    domain = classify_content_domain(path)
    if suffix in MARKDOWN_EXTENSIONS:
        return "markdown"
    if domain == "configuration":
        return "config.lexical"
    if domain == "observability":
        return "log.lexical"
    if domain == "asset":
        return "asset.metadata"
    if domain == "generated":
        return "artifact.metadata"
    if suffix == ".py":
        return "python.ast"
    return "code.lexical"


def extract_markdown(graph: Graph, file_path: Path, relative: str) -> None:
    file_node = f"file:{relative}"
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    current_section_node = file_node
    reference_targets: dict[str, str] = {}
    for line in lines:
        for reference_id, href, _label in markdown_reference_definitions_from_line(line):
            reference_targets[reference_id] = href
        for reference_id, _value in markdown_footnote_definitions_from_line(line):
            reference_targets[reference_id] = f"footnote:{reference_id}"

    for line_number, line in enumerate(lines, start=1):
        heading = MARKDOWN_HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            node_id = f"section:{relative}#{slug(title)}:{line_number}"
            graph.add_node(
                node_id,
                "section",
                title,
                source_path=relative,
                range=SourceRange(line_number),
                attributes={"level": level},
            )
            evidence_id = graph.add_evidence(
                extractor="markdown",
                method="heading",
                source_locator=f"{relative}:{line_number}",
                snippet=line,
                confidence="PROVEN",
            )
            graph.add_edge(
                kind="contains",
                source=file_node,
                target=node_id,
                confidence="PROVEN",
                evidence_id=evidence_id,
            )
            current_section_node = node_id

        line_concepts = markdown_concepts_from_line(line)

        for match in MARKDOWN_LINK_RE.finditer(line):
            add_markdown_reference(
                graph,
                current_section_node,
                relative,
                line_number,
                line,
                label=match.group(1).strip(),
                href=match.group(2).strip(),
                method="inline-link",
                edge_kind="references",
            )

        for label, reference_id in markdown_reference_links_from_line(line):
            add_markdown_reference(
                graph,
                current_section_node,
                relative,
                line_number,
                line,
                label=label,
                href=reference_targets.get(reference_id, reference_id),
                method="reference-link",
                edge_kind="cites",
                attributes={"reference_id": reference_id},
            )

        for reference_id, href, label in markdown_reference_definitions_from_line(line):
            add_markdown_reference(
                graph,
                current_section_node,
                relative,
                line_number,
                line,
                label=label or reference_id,
                href=href,
                method="reference-definition",
                edge_kind="cites",
                attributes={"reference_id": reference_id},
            )

        for reference_id, value in markdown_footnote_definitions_from_line(line):
            add_markdown_reference(
                graph,
                current_section_node,
                relative,
                line_number,
                line,
                label=f"footnote {reference_id}",
                href=f"footnote:{reference_id}",
                method="footnote-definition",
                edge_kind="cites",
                attributes={"reference_id": reference_id, "value": value[:120]},
            )

        for reference_id in markdown_footnote_references_from_line(line):
            add_markdown_reference(
                graph,
                current_section_node,
                relative,
                line_number,
                line,
                label=f"footnote {reference_id}",
                href=f"footnote:{reference_id}",
                method="footnote-reference",
                edge_kind="cites",
                attributes={"reference_id": reference_id},
            )

        for concept in line_concepts:
            concept_id = f"concept:{slug(concept)}"
            graph.add_node(concept_id, "concept", concept)
            evidence_id = graph.add_evidence(
                extractor="markdown",
                method="concept-mention",
                source_locator=f"{relative}:{line_number}",
                snippet=line,
                confidence="INFERRED",
            )
            graph.add_edge(
                kind="mentions",
                source=current_section_node,
                target=concept_id,
                confidence="INFERRED",
                evidence_id=evidence_id,
            )

        claim = markdown_claim_from_line(line)
        if claim:
            claim_node = f"claim:{relative}#{line_number}:{slug(claim['verb'])}"
            graph.add_node(
                claim_node,
                "claim",
                claim["label"],
                source_path=relative,
                range=SourceRange(line_number),
                attributes={"verb": claim["verb"]},
            )
            evidence_id = graph.add_evidence(
                extractor="markdown",
                method="claim-signal",
                source_locator=f"{relative}:{line_number}",
                snippet=line,
                confidence="INFERRED",
            )
            graph.add_edge(
                kind="contains",
                source=current_section_node,
                target=claim_node,
                confidence="INFERRED",
                evidence_id=evidence_id,
            )
            graph.add_edge(
                kind=claim["edge_kind"],
                source=claim_node,
                target=current_section_node,
                confidence="INFERRED",
                evidence_id=evidence_id,
            )
            for concept in line_concepts:
                graph.add_edge(
                    kind="mentions",
                    source=claim_node,
                    target=f"concept:{slug(concept)}",
                    confidence="INFERRED",
                    evidence_id=evidence_id,
                )


def extract_config(graph: Graph, file_path: Path, relative: str) -> None:
    file_node = f"file:{relative}"
    config_node = f"config:{relative}"
    graph.add_node(
        config_node,
        "config_file",
        file_path.name,
        source_path=relative,
        attributes={"format": file_path.suffix.lower() or file_path.name.lower()},
    )
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except UnicodeError:
        lines = []
    snippet = next((line for line in lines if line.strip()), file_path.name)
    evidence_id = graph.add_evidence(
        extractor="config.lexical",
        method="config-file",
        source_locator=f"{relative}:1",
        snippet=snippet,
        confidence="PROVEN",
    )
    graph.add_edge(
        kind="configures",
        source=file_node,
        target=config_node,
        confidence="PROVEN",
        evidence_id=evidence_id,
    )
    for line_number, line in enumerate(lines[:200], start=1):
        match = CONFIG_KEY_RE.match(line)
        if not match:
            continue
        key = match.group(1)
        key_node = f"config-key:{relative}#{slug(key)}:{line_number}"
        graph.add_node(
            key_node,
            "config_key",
            key,
            source_path=relative,
            range=SourceRange(line_number),
        )
        key_evidence = graph.add_evidence(
            extractor="config.lexical",
            method="config-key",
            source_locator=f"{relative}:{line_number}",
            snippet=line,
            confidence="PROVEN",
        )
        graph.add_edge(
            kind="defines",
            source=config_node,
            target=key_node,
            confidence="PROVEN",
            evidence_id=key_evidence,
        )


def markdown_concepts_from_line(line: str) -> list[str]:
    if MARKDOWN_HEADING_RE.match(line):
        return []
    concepts: list[str] = []
    for match in MARKDOWN_HASHTAG_RE.finditer(line):
        concepts.append(match.group(1).replace("-", " ").replace("_", " ").strip())
    for match in MARKDOWN_KEY_TERM_RE.finditer(line):
        value = match.group(1) or match.group(2)
        concepts.append(value.strip())
    return dedupe_preserve_order(
        normalized
        for concept in concepts
        if (normalized := normalize_markdown_concept(concept))
    )


def normalize_markdown_concept(value: str) -> str:
    clean = re.sub(r"\s+", " ", value.strip(" .,:;()[]{}")).strip()
    if not clean:
        return ""
    words = clean.split()
    if len(words) > 1 and words[-1].lower() in {"concept", "concepts", "topic", "topics"}:
        clean = " ".join(words[:-1]).strip()
        words = clean.split()
    if len(clean) < 3 or len(clean) > 80:
        return ""
    lowered_words = [word.lower() for word in words]
    if clean.lower() in STOP_CONCEPTS or all(word in STOP_CONCEPTS for word in lowered_words):
        return ""
    return clean


def markdown_claim_from_line(line: str) -> dict[str, str] | None:
    clean = line.strip()
    if not clean or clean.startswith("#") or len(clean.split()) < 4:
        return None
    match = MARKDOWN_CLAIM_RE.search(clean)
    if not match:
        return None
    verb = match.group(1).lower()
    edge_kind = {
        "support": "supports",
        "supports": "supports",
        "contradict": "contradicts",
        "contradicts": "contradicts",
        "depends on": "depends_on",
        "require": "depends_on",
        "requires": "depends_on",
        "derived from": "derived_from",
    }.get(verb, "supports")
    return {"verb": verb, "edge_kind": edge_kind, "label": clean[:120]}


def markdown_reference_links_from_line(line: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for label, reference_id in MARKDOWN_REFERENCE_LINK_RE.findall(line):
        clean_label = normalize_markdown_concept(label) or label.strip()
        clean_reference_id = reference_id.strip()
        if clean_label and clean_reference_id:
            links.append((clean_label, clean_reference_id))
    for reference_id in MARKDOWN_REFERENCE_SHORTCUT_RE.findall(line):
        clean_reference_id = reference_id.strip()
        if clean_reference_id:
            links.append((clean_reference_id, clean_reference_id))
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for item in links:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def markdown_reference_definitions_from_line(line: str) -> list[tuple[str, str, str | None]]:
    match = MARKDOWN_REFERENCE_DEFINITION_RE.match(line)
    if not match:
        return []
    return [(match.group(1).strip(), match.group(2).strip(), match.group(3).strip() if match.group(3) else None)]


def markdown_footnote_references_from_line(line: str) -> list[str]:
    return dedupe_preserve_order(match.strip() for match in MARKDOWN_FOOTNOTE_REFERENCE_RE.findall(line))


def markdown_footnote_definitions_from_line(line: str) -> list[tuple[str, str]]:
    match = MARKDOWN_FOOTNOTE_DEFINITION_RE.match(line)
    if not match:
        return []
    return [(match.group(1).strip(), match.group(2).strip())]


def add_markdown_reference(
    graph: Graph,
    source_node: str,
    relative: str,
    line_number: int,
    snippet: str,
    *,
    label: str,
    href: str,
    method: str,
    edge_kind: str,
    attributes: dict[str, str] | None = None,
) -> None:
    reference_attributes = {"label": label}
    if attributes:
        reference_attributes.update(attributes)
    target_id = href if href.startswith("reference:") else f"reference:{href}"
    graph.add_node(target_id, "reference", href.removeprefix("reference:"), attributes=reference_attributes)
    evidence_id = graph.add_evidence(
        extractor="markdown",
        method=method,
        source_locator=f"{relative}:{line_number}",
        snippet=snippet,
        confidence="PROVEN",
    )
    graph.add_edge(
        kind=edge_kind,
        source=source_node,
        target=target_id,
        confidence="PROVEN",
        evidence_id=evidence_id,
        attributes=attributes or {},
    )


def extract_log(graph: Graph, file_path: Path, relative: str) -> None:
    file_node = f"file:{relative}"
    log_node = f"log:{relative}"
    graph.add_node(log_node, "log_file", file_path.name, source_path=relative)
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    snippet = next((line for line in lines if line.strip()), file_path.name)
    evidence_id = graph.add_evidence(
        extractor="log.lexical",
        method="log-file",
        source_locator=f"{relative}:1",
        snippet=snippet,
        confidence="PROVEN",
    )
    graph.add_edge(
        kind="diagnoses",
        source=file_node,
        target=log_node,
        confidence="PROVEN",
        evidence_id=evidence_id,
    )
    seen_levels: set[str] = set()
    for line_number, line in enumerate(lines[:200], start=1):
        match = LOG_LEVEL_RE.search(line)
        if not match:
            continue
        level = match.group(1).upper()
        if level in seen_levels:
            continue
        seen_levels.add(level)
        statement_node = f"log-statement:{relative}#{level}:{line_number}"
        graph.add_node(
            statement_node,
            "log_statement",
            level,
            source_path=relative,
            range=SourceRange(line_number),
        )
        statement_evidence = graph.add_evidence(
            extractor="log.lexical",
            method="log-level",
            source_locator=f"{relative}:{line_number}",
            snippet=line,
            confidence="PROVEN",
        )
        graph.add_edge(
            kind="emits_log",
            source=log_node,
            target=statement_node,
            confidence="PROVEN",
            evidence_id=statement_evidence,
        )


def extract_asset(graph: Graph, file_path: Path, relative: str) -> None:
    file_node = f"file:{relative}"
    asset_node = f"asset:{relative}"
    graph.add_node(
        asset_node,
        "asset_file",
        file_path.name,
        source_path=relative,
        attributes={
            "extension": file_path.suffix.lower(),
            "size": file_path.stat().st_size,
        },
    )
    evidence_id = graph.add_evidence(
        extractor="asset.metadata",
        method="file-metadata",
        source_locator=relative,
        snippet=file_path.name,
        confidence="PROVEN",
    )
    graph.add_edge(
        kind="stores_asset",
        source=file_node,
        target=asset_node,
        confidence="PROVEN",
        evidence_id=evidence_id,
    )


def extract_generated_artifact(graph: Graph, file_path: Path, relative: str) -> None:
    file_node = f"file:{relative}"
    artifact_kind = "lockfile" if is_lockfile_path(file_path) else "artifact"
    artifact_node = f"{artifact_kind}:{relative}"
    graph.add_node(
        artifact_node,
        artifact_kind,
        file_path.name,
        source_path=relative,
        attributes={
            "extension": file_path.suffix.lower(),
            "size": file_path.stat().st_size,
        },
    )
    evidence_id = graph.add_evidence(
        extractor="artifact.metadata",
        method="file-metadata",
        source_locator=relative,
        snippet=file_path.name,
        confidence="PROVEN",
    )
    graph.add_edge(
        kind="generated_from",
        source=artifact_node,
        target=file_node,
        confidence="PROVEN",
        evidence_id=evidence_id,
    )


def extract_python_ast(
    graph: Graph,
    target: Path,
    file_path: Path,
    relative: str,
    *,
    import_aliases: tuple[ImportAlias, ...] = (),
    context: ExtractionContext | None = None,
) -> None:
    context = context or ExtractionContext()
    source = file_path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError:
        extract_code_lexical(graph, target, file_path, relative, import_aliases=import_aliases)
        return

    file_node = f"file:{relative}"
    lines = source.splitlines()
    local_symbols: dict[str, str] = {}
    imported_bindings: dict[str, str] = {}
    imported_binding_confidences: dict[str, str] = {}
    class_methods: dict[tuple[str, str], str] = {}
    owner_by_symbol: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add_import_relationship(
                    graph,
                    target,
                    file_path,
                    file_node,
                    relative,
                    node.lineno,
                    line_at(lines, node.lineno),
                    alias.name,
                    [alias.asname or alias.name.split(".", 1)[0]],
                    imported_bindings,
                    imported_binding_confidences,
                    import_aliases,
                    context=context,
                    extractor="python.ast",
                    method="ast-import",
                )
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            names = [alias.asname or alias.name for alias in node.names if alias.name != "*"]
            add_import_relationship(
                graph,
                target,
                file_path,
                file_node,
                relative,
                node.lineno,
                line_at(lines, node.lineno),
                module,
                names,
                imported_bindings,
                imported_binding_confidences,
                import_aliases,
                context=context,
                extractor="python.ast",
                method="ast-import-from",
                edge_attributes={"relative_level": node.level} if node.level else None,
            )

    def register_definition(
        node: ast.AST,
        *,
        owner_id: str,
        owner_kind: str,
        owner_name: str | None = None,
    ) -> None:
        if isinstance(node, ast.ClassDef):
            kind = "class"
            symbol_id = f"symbol:{relative}#{node.name}:{node.lineno}"
            local_symbols[node.name] = symbol_id
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "function"
            if owner_name:
                symbol_id = f"symbol:{relative}#{owner_name}.{node.name}:{node.lineno}"
                class_methods[(owner_name, node.name)] = symbol_id
                owner_by_symbol[symbol_id] = owner_name
            else:
                symbol_id = f"symbol:{relative}#{node.name}:{node.lineno}"
                local_symbols[node.name] = symbol_id
        else:
            return
        graph.add_node(
            symbol_id,
            kind,
            node.name,
            source_path=relative,
            range=SourceRange(node.lineno),
            attributes={"owner": owner_name} if owner_name else None,
        )
        evidence_id = graph.add_evidence(
            extractor="python.ast",
            method=f"{kind}-definition",
            source_locator=f"{relative}:{node.lineno}",
            snippet=line_at(lines, node.lineno),
            confidence="PROVEN",
        )
        graph.add_edge(
            kind="contains",
            source=owner_id,
            target=symbol_id,
            confidence="PROVEN",
            evidence_id=evidence_id,
        )
        graph.add_edge(
            kind="defines",
            source=owner_id,
            target=symbol_id,
            confidence="PROVEN",
            evidence_id=evidence_id,
        )
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    register_definition(
                        child,
                        owner_id=symbol_id,
                        owner_kind="class",
                        owner_name=node.name,
                    )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            register_definition(node, owner_id=file_node, owner_kind="file")

    for node in ast.walk(tree):
        symbol_id = local_symbols.get(node.name) if isinstance(node, ast.ClassDef) else None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner_name = find_python_owner_class(tree, node)
            symbol_id = (
                class_methods.get((owner_name, node.name))
                if owner_name
                else local_symbols.get(node.name)
            )
        if not symbol_id:
            continue
        for reference_node, relationship in python_relationship_targets(node):
            target_id, relationship_confidence = resolve_python_reference_target(
                reference_node,
                local_symbols=local_symbols,
                imported_bindings=imported_bindings,
                imported_binding_confidences=imported_binding_confidences,
            )
            if not target_id or target_id == symbol_id:
                continue
            evidence_id = graph.add_evidence(
                extractor="python.ast",
                method=relationship,
                source_locator=f"{relative}:{reference_node.lineno}",
                snippet=line_at(lines, reference_node.lineno),
                confidence=relationship_confidence,
            )
            graph.add_edge(
                kind="depends_on",
                source=symbol_id,
                target=target_id,
                confidence=relationship_confidence,
                evidence_id=evidence_id,
                attributes={"relationship": relationship},
            )

    for owner in ast.walk(tree):
        if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        owner_class = find_python_owner_class(tree, owner)
        owner_id = class_methods.get((owner_class, owner.name)) if owner_class else local_symbols.get(owner.name)
        if not owner_id:
            continue
        for node in ast.walk(owner):
            if not isinstance(node, ast.Call):
                continue
            target_id = resolve_python_call_target(
                node.func,
                owner_class=owner_class,
                owner_id=owner_id,
                local_symbols=local_symbols,
                class_methods=class_methods,
            )
            if not target_id or target_id == owner_id:
                continue
            evidence_id = graph.add_evidence(
                extractor="python.ast",
                method="call",
                source_locator=f"{relative}:{node.lineno}",
                snippet=line_at(lines, node.lineno),
                confidence="PROVEN",
            )
            graph.add_edge(
                kind="calls",
                source=owner_id,
                target=target_id,
                confidence="PROVEN",
                evidence_id=evidence_id,
                attributes={"function": python_call_name(node.func)},
            )


def extract_code_lexical(
    graph: Graph,
    target: Path,
    file_path: Path,
    relative: str,
    *,
    import_aliases: tuple[ImportAlias, ...] = (),
    context: ExtractionContext | None = None,
) -> None:
    context = context or ExtractionContext()
    file_node = f"file:{relative}"
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    imported_bindings: dict[str, str] = {}
    imported_binding_confidences: dict[str, str] = {}
    local_definitions: dict[str, str] = {}
    local_binding_lines: dict[str, int] = {}

    if file_path.suffix.lower() in JS_EXTENSIONS:
        for statement in js_module_statements(lines, file_path.suffix.lower()):
            add_import_relationship(
                graph,
                target,
                file_path,
                file_node,
                relative,
                statement.line_number,
                statement.snippet,
                statement.module,
                statement.names,
                imported_bindings,
                imported_binding_confidences,
                import_aliases,
                context=context,
                method=statement.method,
                edge_kind=statement.edge_kind,
                bind_names=statement.bind_names,
            )
        for line_number, line in enumerate(lines, start=1):
            for module, method, edge_kind in js_inline_module_references(line):
                add_import_relationship(
                    graph,
                    target,
                    file_path,
                    file_node,
                    relative,
                    line_number,
                    line,
                    module,
                    [],
                    imported_bindings,
                    imported_binding_confidences,
                    import_aliases,
                    context=context,
                    method=method,
                    edge_kind=edge_kind,
                    bind_names=False,
                )

    if file_path.suffix.lower() not in JS_EXTENSIONS:
        for line_number, line in enumerate(lines, start=1):
            for module in modules_from_line(line, file_path.suffix.lower()):
                add_import_relationship(
                    graph,
                    target,
                    file_path,
                    file_node,
                    relative,
                    line_number,
                    line,
                    module,
                    imported_names_from_line(line, module, file_path.suffix.lower()),
                    imported_bindings,
                    imported_binding_confidences,
                    import_aliases,
                    context=context,
                )

    for line_number, line in enumerate(lines, start=1):
        if file_path.suffix.lower() in JS_EXTENSIONS:
            binding_name = js_local_binding_name(line)
            if binding_name:
                local_binding_lines.setdefault(binding_name, line_number)
        definition = definition_from_line(line, file_path.suffix.lower())
        if definition:
            kind, name = definition
            node_id = f"symbol:{relative}#{name}:{line_number}"
            local_definitions[name] = node_id
            graph.add_node(
                node_id,
                kind,
                name,
                source_path=relative,
                range=SourceRange(line_number),
            )
            evidence_id = graph.add_evidence(
                extractor="code.lexical",
                method=f"{kind}-definition",
                source_locator=f"{relative}:{line_number}",
                snippet=line,
                confidence="PROVEN",
            )
            graph.add_edge(
                kind="contains",
                source=file_node,
                target=node_id,
                confidence="PROVEN",
                evidence_id=evidence_id,
            )
            graph.add_edge(
                kind="defines",
                source=file_node,
                target=node_id,
                confidence="PROVEN",
                evidence_id=evidence_id,
            )
            if file_path.suffix.lower() in JS_EXTENSIONS and js_exports_local_name(line) == name:
                graph.add_edge(
                    kind="exports",
                    source=file_node,
                    target=node_id,
                    confidence="PROVEN",
                    evidence_id=evidence_id,
                    attributes={"symbol": name},
                )

    if file_path.suffix.lower() in JS_EXTENSIONS:
        for line_number, line in enumerate(lines, start=1):
            export_name = js_commonjs_local_export_name(line)
            if export_name and export_name not in local_definitions:
                ensure_js_local_binding_definition(
                    graph,
                    file_node,
                    relative,
                    lines,
                    local_definitions,
                    local_binding_lines,
                    export_name,
                )
            target_id = local_definitions.get(export_name or "")
            if not export_name or not target_id:
                continue
            evidence_id = graph.add_evidence(
                extractor="code.lexical",
                method="lexical-commonjs-export",
                source_locator=f"{relative}:{line_number}",
                snippet=line,
                confidence="PROVEN",
            )
            graph.add_edge(
                kind="exports",
                source=file_node,
                target=target_id,
                confidence="PROVEN",
                evidence_id=evidence_id,
                attributes={"symbol": export_name},
            )

    rendered_targets: set[tuple[str, str]] = set()
    for line_number, line in enumerate(lines, start=1):
        for component in jsx_components_from_line(line, file_path.suffix.lower()):
            target_id = imported_bindings.get(component)
            if not target_id:
                continue
            key = (component, target_id)
            if key in rendered_targets:
                continue
            rendered_targets.add(key)
            evidence_id = graph.add_evidence(
                extractor="code.lexical",
                method="jsx-render",
                source_locator=f"{relative}:{line_number}",
                snippet=line,
                confidence="DERIVED",
            )
            graph.add_edge(
                kind="renders",
                source=file_node,
                target=target_id,
                confidence="DERIVED",
                evidence_id=evidence_id,
                attributes={"component": component},
            )


def add_import_relationship(
    graph: Graph,
    target: Path,
    file_path: Path,
    file_node: str,
    relative: str,
    line_number: int,
    snippet: str,
    module: str,
    names: list[str],
    imported_bindings: dict[str, str],
    imported_binding_confidences: dict[str, str] | None,
    import_aliases: tuple[ImportAlias, ...],
    *,
    context: ExtractionContext | None = None,
    extractor: str = "code.lexical",
    method: str | None = None,
    confidence: str | None = None,
    edge_kind: str = "imports",
    bind_names: bool = True,
    edge_attributes: dict[str, object] | None = None,
) -> str:
    context = context or ExtractionContext()
    resolved = resolve_import(target, file_path, module, import_aliases, context=context)
    if resolved:
        target_relative = resolved.relative_to(target).as_posix()
        target_id = f"file:{target_relative}"
        edge_confidence = confidence or "DERIVED"
        edge_method = method or "lexical-import+relative-resolution"
        if bind_names:
            for binding in names:
                imported_bindings[binding] = target_id
                if imported_binding_confidences is not None:
                    imported_binding_confidences[binding] = edge_confidence
    else:
        target_id = f"module:{module}"
        graph.add_node(target_id, "module", module)
        edge_confidence = confidence or "PROVEN"
        edge_method = method or "lexical-import"
    evidence_id = graph.add_evidence(
        extractor=extractor,
        method=edge_method,
        source_locator=f"{relative}:{line_number}",
        snippet=snippet,
        confidence=edge_confidence,
    )
    graph.add_edge(
        kind=edge_kind,
        source=file_node,
        target=target_id,
        confidence=edge_confidence,
        evidence_id=evidence_id,
        attributes={"module": module, **(edge_attributes or {})},
    )
    if names and resolved is None:
        for binding in names:
            binding_id = imported_binding_node_id(module, binding)
            graph.add_node(
                binding_id,
                "imported_symbol",
                binding,
                attributes={"module": module},
            )
            graph.add_edge(
                kind="exports",
                source=target_id,
                target=binding_id,
                confidence=edge_confidence,
                evidence_id=evidence_id,
                attributes={"module": module, "symbol": binding, **(edge_attributes or {})},
            )
            graph.add_edge(
                kind=edge_kind,
                source=file_node,
                target=binding_id,
                confidence=edge_confidence,
                evidence_id=evidence_id,
                attributes={"module": module, "symbol": binding, **(edge_attributes or {})},
            )
            if bind_names:
                imported_bindings[binding] = binding_id
                if imported_binding_confidences is not None:
                    imported_binding_confidences[binding] = edge_confidence
    return target_id


def line_at(lines: list[str], line_number: int) -> str:
    if 1 <= line_number <= len(lines):
        return lines[line_number - 1]
    return ""


def python_call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def find_python_owner_class(tree: ast.AST, target: ast.AST) -> str | None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if target in node.body:
            return node.name
    return None


def python_relationship_targets(node: ast.AST) -> list[tuple[ast.AST, str]]:
    relationships: list[tuple[ast.AST, str]] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        for decorator in node.decorator_list:
            relationships.append((decorator.func if isinstance(decorator, ast.Call) else decorator, "decorator"))
    if isinstance(node, ast.ClassDef):
        for base in node.bases:
            relationships.append((base, "base-class"))
    return relationships


def resolve_python_reference_target(
    node: ast.AST,
    *,
    local_symbols: dict[str, str],
    imported_bindings: dict[str, str],
    imported_binding_confidences: dict[str, str],
) -> tuple[str | None, str]:
    if isinstance(node, ast.Call):
        return resolve_python_reference_target(
            node.func,
            local_symbols=local_symbols,
            imported_bindings=imported_bindings,
            imported_binding_confidences=imported_binding_confidences,
        )
    if isinstance(node, ast.Name):
        target_id = local_symbols.get(node.id)
        if target_id:
            return target_id, "PROVEN"
        target_id = imported_bindings.get(node.id)
        if target_id:
            return target_id, imported_binding_confidences.get(node.id, "DERIVED")
        return None, "UNRESOLVED"
    if isinstance(node, ast.Attribute):
        target_id = local_symbols.get(node.attr)
        if target_id:
            return target_id, "PROVEN"
        target_id = imported_bindings.get(node.attr)
        if target_id:
            return target_id, imported_binding_confidences.get(node.attr, "DERIVED")
        return None, "UNRESOLVED"
    return None, "UNRESOLVED"


def resolve_python_call_target(
    node: ast.AST,
    *,
    owner_class: str | None,
    owner_id: str,
    local_symbols: dict[str, str],
    class_methods: dict[tuple[str, str], str],
) -> str | None:
    if (
        owner_class
        and isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ):
        return class_methods.get((owner_class, node.attr))
    called_name = python_call_name(node)
    if not called_name:
        return None
    return local_symbols.get(called_name)


def modules_from_line(line: str, suffix: str) -> list[str]:
    if suffix == ".py":
        match = PY_IMPORT_RE.match(line)
        if not match:
            return []
        if match.group(1):
            return [match.group(1)]
        return [part.strip().split(" as ")[0] for part in match.group(3).split(",") if part.strip()]

    if suffix in JS_EXTENSIONS:
        match = JS_IMPORT_RE.match(line)
        if not match:
            return []
        return [group for group in match.groups() if group]

    return []


def definition_from_line(line: str, suffix: str) -> tuple[str, str] | None:
    if suffix == ".py":
        if match := PY_DEF_RE.match(line):
            return ("function", match.group(1))
        if match := PY_CLASS_RE.match(line):
            return ("class", match.group(1))

    if suffix in JS_EXTENSIONS:
        if match := JS_FUNC_RE.match(line):
            return ("function", match.group(1) or match.group(2))
        if match := JS_CLASS_RE.match(line):
            return ("class", match.group(1))

    return None


def js_exports_local_name(line: str) -> str | None:
    match = JS_EXPORTED_LOCAL_RE.match(line)
    if not match:
        return None
    return next((group for group in match.groups() if group), None)


def js_commonjs_local_export_name(line: str) -> str | None:
    match = JS_COMMONJS_EXPORT_LOCAL_RE.match(line.strip())
    if not match:
        return None
    return match.group("name")


def js_local_binding_name(line: str) -> str | None:
    match = re.match(r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\b", line)
    if not match:
        return None
    return match.group(1)


def ensure_js_local_binding_definition(
    graph: Graph,
    file_node: str,
    relative: str,
    lines: list[str],
    local_definitions: dict[str, str],
    local_binding_lines: dict[str, int],
    name: str,
) -> str | None:
    line_number = local_binding_lines.get(name)
    if not line_number:
        return None
    node_id = local_definitions.get(name, f"symbol:{relative}#{name}:{line_number}")
    if node_id in graph.nodes:
        local_definitions[name] = node_id
        return node_id
    local_definitions[name] = node_id
    graph.add_node(
        node_id,
        "symbol",
        name,
        source_path=relative,
        range=SourceRange(line_number),
    )
    evidence_id = graph.add_evidence(
        extractor="code.lexical",
        method="symbol-definition",
        source_locator=f"{relative}:{line_number}",
        snippet=line_at(lines, line_number),
        confidence="PROVEN",
    )
    graph.add_edge(
        kind="contains",
        source=file_node,
        target=node_id,
        confidence="PROVEN",
        evidence_id=evidence_id,
    )
    graph.add_edge(
        kind="defines",
        source=file_node,
        target=node_id,
        confidence="PROVEN",
        evidence_id=evidence_id,
    )
    return node_id


def js_module_statements(lines: list[str], suffix: str) -> list[JsModuleStatement]:
    if suffix not in JS_EXTENSIONS:
        return []
    statements: list[JsModuleStatement] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped.startswith(("import", "export", "const ", "let ", "var ", "module.exports", "exports.")):
            index += 1
            continue

        start_index = index
        block = [line]
        if stripped.startswith(("import", "export")) and " from " in line and quote_count_is_open(line):
            index += 1
            while index < len(lines):
                block.append(lines[index])
                if re.search(r"\bfrom\s+['\"][^'\"]+['\"]", "\n".join(block)):
                    break
                index += 1
        elif stripped.startswith(("import", "export")) and "{" in line and " from " not in line:
            index += 1
            while index < len(lines):
                block.append(lines[index])
                if re.search(r"\bfrom\s+['\"][^'\"]+['\"]", "\n".join(block)):
                    break
                index += 1

        snippet = "\n".join(block)
        normalized = " ".join(part.strip() for part in block)
        if match := JS_IMPORT_FROM_RE.match(normalized):
            type_only = bool(match.group("type"))
            statements.append(
                JsModuleStatement(
                    start_index + 1,
                    snippet,
                    match.group("module"),
                    js_names_from_specifier(match.group("specifier")),
                    "imports",
                    not type_only,
                    "lexical-type-import" if type_only else "lexical-import",
                )
            )
        elif match := JS_SIDE_EFFECT_IMPORT_RE.match(normalized):
            statements.append(
                JsModuleStatement(
                    start_index + 1,
                    snippet,
                    match.group("module"),
                    [],
                    "imports",
                    False,
                    "lexical-side-effect-import",
                )
            )
        elif match := JS_EXPORT_FROM_RE.match(normalized):
            type_only = bool(match.group("type"))
            statements.append(
                JsModuleStatement(
                    start_index + 1,
                    snippet,
                    match.group("module"),
                    js_names_from_specifier(match.group("specifier")),
                    "exports",
                    False,
                    "lexical-type-re-export" if type_only else "lexical-re-export",
                )
            )
        elif match := JS_REQUIRE_RE.match(normalized):
            statements.append(
                JsModuleStatement(
                    start_index + 1,
                    snippet,
                    match.group("module"),
                    js_names_from_require(match.group("specifier")),
                    "imports",
                    True,
                    "lexical-require",
                )
            )
        elif match := JS_COMMONJS_EXPORT_REQUIRE_RE.match(normalized):
            statements.append(
                JsModuleStatement(
                    start_index + 1,
                    snippet,
                    match.group("module"),
                    [],
                    "exports",
                    False,
                    "lexical-commonjs-export-require",
                )
            )
        index += 1
    return statements


def js_inline_module_references(line: str) -> list[tuple[str, str, str]]:
    references: list[tuple[str, str, str]] = []
    for module in JS_DYNAMIC_IMPORT_RE.findall(line):
        references.append((module, "lexical-dynamic-import", "imports"))
    for module in JS_REQUIRE_RESOLVE_RE.findall(line):
        references.append((module, "lexical-require-resolve", "imports"))
    seen: set[tuple[str, str, str]] = set()
    result: list[tuple[str, str, str]] = []
    for item in references:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def quote_count_is_open(line: str) -> bool:
    return line.count("{") > line.count("}")


def js_names_from_specifier(specifier: str) -> list[str]:
    specifier = specifier.strip().rstrip(";")
    if specifier == "*":
        return []
    if specifier.startswith("* as "):
        return [specifier.removeprefix("* as ").strip()]
    names: list[str] = []
    named_block = text_between_braces(specifier)
    default_part = specifier
    if named_block is not None:
        default_part = specifier[: specifier.index("{")].strip().rstrip(",")
    if default_part and not default_part.startswith("{") and not default_part.startswith("*"):
        first_default = split_top_level_commas(default_part)[0].strip()
        if first_default:
            names.append(first_default)
    if named_block is not None:
        names.extend(js_names_from_named_block(named_block, alias_separator=" as "))
    return dedupe_preserve_order(name for name in names if name)


def js_names_from_require(specifier: str) -> list[str]:
    specifier = specifier.strip().rstrip(";")
    named_block = text_between_braces(specifier)
    if named_block is not None:
        return js_names_from_named_block(named_block, alias_separator=":")
    if match := re.match(r"^[A-Za-z_$][\w$]*$", specifier):
        return [match.group(0)]
    return []


def js_names_from_named_block(block: str, *, alias_separator: str) -> list[str]:
    names: list[str] = []
    for item in split_top_level_commas(block):
        item = item.strip()
        if not item:
            continue
        if alias_separator in item:
            names.append(item.split(alias_separator, 1)[1].strip())
        else:
            names.append(item)
    return dedupe_preserve_order(clean_js_binding_name(name) for name in names if clean_js_binding_name(name))


def text_between_braces(value: str) -> str | None:
    if "{" not in value or "}" not in value:
        return None
    return value[value.index("{") + 1 : value.rindex("}")]


def split_top_level_commas(value: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in value:
        if char in "({[":
            depth += 1
        elif char in ")}]" and depth:
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def clean_js_binding_name(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^(?:type|typeof)\s+", "", value)
    value = value.split("=", 1)[0].strip()
    match = re.match(r"^[A-Za-z_$][\w$]*$", value)
    return match.group(0) if match else ""


def dedupe_preserve_order(values: object) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def imported_names_from_line(line: str, module: str, suffix: str) -> list[str]:
    if suffix not in JS_EXTENSIONS:
        return []
    match = JS_IMPORT_DETAIL_RE.match(line)
    if not match or match.group(2) != module:
        return []
    return js_names_from_specifier(match.group(1))


def jsx_components_from_line(line: str, suffix: str) -> list[str]:
    if suffix not in {".jsx", ".tsx"}:
        return []
    return JS_JSX_COMPONENT_RE.findall(line)


def imported_binding_node_id(module: str, binding: str) -> str:
    return f"imported-symbol:{module}#{binding}"


def resolve_import(
    target: Path,
    file_path: Path,
    module: str,
    aliases: tuple[ImportAlias, ...],
    *,
    context: ExtractionContext | None = None,
) -> Path | None:
    context = context or ExtractionContext()
    cache_key = (str(file_path), module, import_aliases_key(aliases))
    if cache_key in context.import_resolution_cache:
        return context.import_resolution_cache[cache_key]
    if module.startswith("./") or module.startswith("../"):
        resolved = resolve_candidate_base(target, file_path.parent / module, context=context)
        context.import_resolution_cache[cache_key] = resolved
        return resolved
    if module.startswith("."):
        resolved = resolve_python_relative_import(target, file_path, module, context=context)
        context.import_resolution_cache[cache_key] = resolved
        return resolved
    for base in alias_candidate_bases(target, module, aliases):
        resolved = resolve_candidate_base(target, base, context=context)
        if resolved:
            context.import_resolution_cache[cache_key] = resolved
            return resolved
    context.import_resolution_cache[cache_key] = None
    return None


def resolve_relative_import(target: Path, file_path: Path, module: str) -> Path | None:
    if not module.startswith("."):
        return None
    if module.startswith("./") or module.startswith("../"):
        return resolve_candidate_base(target, file_path.parent / module)
    return resolve_python_relative_import(target, file_path, module)


def resolve_python_relative_import(
    target: Path,
    file_path: Path,
    module: str,
    *,
    context: ExtractionContext | None = None,
) -> Path | None:
    level = len(module) - len(module.lstrip("."))
    remainder = module[level:]
    base = file_path.parent
    for _ in range(max(level - 1, 0)):
        base = base.parent
    if remainder:
        base = base / Path(*remainder.split("."))
    return resolve_candidate_base(target, base, context=context)


def resolve_candidate_base(target: Path, base: Path, *, context: ExtractionContext | None = None) -> Path | None:
    context = context or ExtractionContext()
    target = target.resolve()
    base = base.resolve()
    cache_key = str(base)
    if cache_key in context.candidate_resolution_cache:
        return context.candidate_resolution_cache[cache_key]
    candidates = [base]
    candidates.extend(base.with_suffix(suffix) for suffix in CODE_EXTENSIONS | MARKDOWN_EXTENSIONS)
    candidates.extend((base / f"index{suffix}") for suffix in CODE_EXTENSIONS)
    for candidate in candidates:
        try:
            candidate.relative_to(target)
        except ValueError:
            continue
        if candidate.is_file():
            resolved = normalize_existing_path_case(candidate, context=context)
            context.candidate_resolution_cache[cache_key] = resolved
            return resolved
    context.candidate_resolution_cache[cache_key] = None
    return None


def alias_candidate_bases(target: Path, module: str, aliases: tuple[ImportAlias, ...]) -> list[Path]:
    bases: list[Path] = []
    for alias in aliases:
        replaced = apply_alias(module, alias)
        if replaced:
            bases.append(target / replaced)
    return bases


def apply_alias(module: str, alias: ImportAlias) -> str | None:
    pattern = alias.pattern
    target = alias.target
    if "*" in pattern:
        prefix, suffix = pattern.split("*", 1)
        if not module.startswith(prefix) or (suffix and not module.endswith(suffix)):
            return None
        middle_end = len(module) - len(suffix) if suffix else len(module)
        wildcard = module[len(prefix):middle_end]
        return target.replace("*", wildcard)
    clean_pattern = pattern.rstrip("/")
    clean_target = target.rstrip("/")
    if module == clean_pattern:
        return clean_target
    if module.startswith(f"{clean_pattern}/"):
        rest = module[len(clean_pattern) + 1 :]
        return f"{clean_target}/{rest}"
    return None


def normalize_existing_path_case(path: Path, *, context: ExtractionContext | None = None) -> Path:
    context = context or ExtractionContext()
    if not path.is_absolute():
        path = path.resolve()
    cache_key = str(path)
    cached = context.normalized_path_case_cache.get(cache_key)
    if cached:
        return cached
    current = Path(path.anchor)
    for part in path.parts[1:]:
        try:
            matches = {child.name.lower(): child.name for child in current.iterdir()}
        except OSError:
            context.normalized_path_case_cache[cache_key] = path
            return path
        actual = matches.get(part.lower())
        if actual is None:
            context.normalized_path_case_cache[cache_key] = path
            return path
        current = current / actual
    context.normalized_path_case_cache[cache_key] = current
    return current


def import_aliases_key(aliases: tuple[ImportAlias, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((alias.pattern, alias.target) for alias in aliases)


def is_lockfile_path(path: Path) -> bool:
    name = path.name.lower()
    return path.suffix.lower() == ".lock" or name.endswith(".lock") or name in LOCKFILE_FILENAMES


def slug(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower()).strip("-")
    return clean or "section"
