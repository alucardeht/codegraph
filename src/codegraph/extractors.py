from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

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
LOG_EXTENSIONS = {".log"}
ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".pdf"}
CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
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
CONFIG_KEY_RE = re.compile(r"^\s*[\"']?([A-Za-z_][\w.-]*)[\"']?\s*[:=]")
LOG_LEVEL_RE = re.compile(r"\b(DEBUG|INFO|WARN|WARNING|ERROR|FATAL|TRACE)\b", re.IGNORECASE)
PY_IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import\s+(.+)|import\s+(.+))")
JS_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+(?:.+?\s+from\s+)?[\"']([^\"']+)[\"']|export\s+.+?\s+from\s+[\"']([^\"']+)[\"']|const\s+.+?=\s+require\([\"']([^\"']+)[\"']\))"
)
JS_IMPORT_DETAIL_RE = re.compile(r"^\s*import\s+(.+?)\s+from\s+[\"']([^\"']+)[\"']")
JS_JSX_COMPONENT_RE = re.compile(r"<\s*([A-Z][A-Za-z0-9_$]*)\b")
PY_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)\s*\(")
PY_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][\w]*)\b")
JS_FUNC_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("
)
JS_CLASS_RE = re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)\b")


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
            "error": self.error,
        }


def extract_file_content(graph: Graph, target: Path, file_path: Path) -> ExtractionResult:
    relative = file_path.relative_to(target).as_posix()
    suffix = file_path.suffix.lower()
    content_domain = classify_content_domain(file_path)
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
        else:
            extract_code_lexical(graph, target, file_path, relative)
    except OSError as error:
        return ExtractionResult(
            relative,
            extractor,
            supported=True,
            content_domain=content_domain,
            error=str(error),
        )

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
    )


def classify_content_domain(path: Path) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    if (
        "generated" in parts
        or suffix in {".lock", ".patch"}
        or name.endswith(".lock")
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
    return "code.lexical"


def extract_markdown(graph: Graph, file_path: Path, relative: str) -> None:
    file_node = f"file:{relative}"
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()

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

        for match in MARKDOWN_LINK_RE.finditer(line):
            label = match.group(1).strip()
            href = match.group(2).strip()
            target_id = f"reference:{href}"
            graph.add_node(target_id, "reference", href, attributes={"label": label})
            evidence_id = graph.add_evidence(
                extractor="markdown",
                method="inline-link",
                source_locator=f"{relative}:{line_number}",
                snippet=match.group(0),
                confidence="PROVEN",
            )
            graph.add_edge(
                kind="references",
                source=file_node,
                target=target_id,
                confidence="PROVEN",
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
    artifact_node = f"artifact:{relative}"
    graph.add_node(
        artifact_node,
        "artifact",
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


def extract_code_lexical(graph: Graph, target: Path, file_path: Path, relative: str) -> None:
    file_node = f"file:{relative}"
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    imported_bindings: dict[str, str] = {}

    for line_number, snippet, module, names in multiline_js_imports(lines, file_path.suffix.lower()):
        target_id = add_import_relationship(
            graph,
            target,
            file_path,
            file_node,
            relative,
            line_number,
            snippet,
            module,
            names,
            imported_bindings,
        )
        if target_id:
            continue

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
            )

        definition = definition_from_line(line, file_path.suffix.lower())
        if definition:
            kind, name = definition
            node_id = f"symbol:{relative}#{name}:{line_number}"
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
) -> str:
    resolved = resolve_relative_import(target, file_path, module)
    if resolved:
        target_relative = resolved.relative_to(target).as_posix()
        target_id = f"file:{target_relative}"
        confidence = "DERIVED"
        method = "lexical-import+relative-resolution"
        for binding in names:
            imported_bindings[binding] = target_id
    else:
        target_id = f"module:{module}"
        graph.add_node(target_id, "module", module)
        confidence = "PROVEN"
        method = "lexical-import"
    evidence_id = graph.add_evidence(
        extractor="code.lexical",
        method=method,
        source_locator=f"{relative}:{line_number}",
        snippet=snippet,
        confidence=confidence,
    )
    graph.add_edge(
        kind="imports",
        source=file_node,
        target=target_id,
        confidence=confidence,
        evidence_id=evidence_id,
        attributes={"module": module},
    )
    if resolved is None:
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
                confidence=confidence,
                evidence_id=evidence_id,
                attributes={"module": module, "symbol": binding},
            )
            graph.add_edge(
                kind="imports",
                source=file_node,
                target=binding_id,
                confidence=confidence,
                evidence_id=evidence_id,
                attributes={"module": module, "symbol": binding},
            )
            imported_bindings[binding] = binding_id
    return target_id


def modules_from_line(line: str, suffix: str) -> list[str]:
    if suffix == ".py":
        match = PY_IMPORT_RE.match(line)
        if not match:
            return []
        if match.group(1):
            return [match.group(1)]
        return [part.strip().split(" as ")[0] for part in match.group(3).split(",") if part.strip()]

    if suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
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

    if suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        if match := JS_FUNC_RE.match(line):
            return ("function", match.group(1) or match.group(2))
        if match := JS_CLASS_RE.match(line):
            return ("class", match.group(1))

    return None


def multiline_js_imports(lines: list[str], suffix: str) -> list[tuple[int, str, str, list[str]]]:
    if suffix not in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        return []
    imports: list[tuple[int, str, str, list[str]]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not re.match(r"^\s*import\s+{\s*$", line):
            index += 1
            continue
        start_index = index
        block = [line]
        index += 1
        while index < len(lines):
            block.append(lines[index])
            if re.search(r"}\s+from\s+['\"][^'\"]+['\"]", lines[index]):
                break
            index += 1
        snippet = "\n".join(block)
        match = re.search(r"}\s+from\s+['\"]([^'\"]+)['\"]", snippet)
        if match:
            body = "\n".join(block)[block[0].find("{") + 1 : snippet.rfind("}")]
            names = []
            for item in body.split(","):
                item = item.strip()
                if not item:
                    continue
                names.append(item.split(" as ")[-1].strip())
            imports.append((start_index + 1, snippet, match.group(1), names))
        index += 1
    return imports


def imported_names_from_line(line: str, module: str, suffix: str) -> list[str]:
    if suffix not in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        return []
    match = JS_IMPORT_DETAIL_RE.match(line)
    if not match or match.group(2) != module:
        return []
    specifier = match.group(1).strip()
    names: list[str] = []
    default_part = specifier.split(",", 1)[0].strip()
    if default_part and not default_part.startswith("{") and not default_part.startswith("*"):
        names.append(default_part)
    if specifier.startswith("* as "):
        names.append(specifier.removeprefix("* as ").strip())
    if "{" in specifier and "}" in specifier:
        named = specifier[specifier.index("{") + 1 : specifier.index("}")]
        for item in named.split(","):
            item = item.strip()
            if not item:
                continue
            names.append(item.split(" as ")[-1].strip())
    return [name for name in names if name]


def jsx_components_from_line(line: str, suffix: str) -> list[str]:
    if suffix not in {".jsx", ".tsx"}:
        return []
    return JS_JSX_COMPONENT_RE.findall(line)


def imported_binding_node_id(module: str, binding: str) -> str:
    return f"imported-symbol:{module}#{binding}"


def resolve_relative_import(target: Path, file_path: Path, module: str) -> Path | None:
    if not module.startswith("."):
        return None
    base = (file_path.parent / module).resolve()
    candidates = [base]
    candidates.extend(base.with_suffix(suffix) for suffix in CODE_EXTENSIONS | MARKDOWN_EXTENSIONS)
    candidates.extend((base / f"index{suffix}") for suffix in CODE_EXTENSIONS)
    for candidate in candidates:
        try:
            candidate.relative_to(target)
        except ValueError:
            continue
        if candidate.is_file():
            return normalize_existing_path_case(candidate)
    return None


def normalize_existing_path_case(path: Path) -> Path:
    if not path.is_absolute():
        path = path.resolve()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        try:
            matches = {child.name.lower(): child.name for child in current.iterdir()}
        except OSError:
            return path
        actual = matches.get(part.lower())
        if actual is None:
            return path
        current = current / actual
    return current


def slug(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower()).strip("-")
    return clean or "section"
