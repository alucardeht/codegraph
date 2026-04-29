from __future__ import annotations

import ast
from dataclasses import dataclass
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
JS_JSX_COMPONENT_RE = re.compile(r"<\s*([A-Z][A-Za-z0-9_$]*)\b")
PY_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)\s*\(")
PY_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][\w]*)\b")
JS_FUNC_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\(?[A-Za-z_$,\s]*\)?\s*=>|\()"
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


EXTRACTOR_DECLARATIONS = (
    ExtractorDeclaration(
        "markdown",
        ("documentation",),
        ("reference", "section"),
        ("contains", "references"),
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
        ("artifact",),
        ("generated_from",),
    ),
    ExtractorDeclaration(
        "python.ast",
        ("code", "test"),
        ("class", "function", "module", "imported_symbol"),
        ("calls", "contains", "defines", "exports", "imports"),
    ),
    ExtractorDeclaration(
        "code.lexical",
        ("code", "test"),
        ("class", "function", "module", "imported_symbol"),
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
) -> ExtractionResult:
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
            extract_python_ast(graph, target, file_path, relative, import_aliases=import_aliases)
        else:
            extract_code_lexical(graph, target, file_path, relative, import_aliases=import_aliases)
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
    if suffix == ".py":
        return "python.ast"
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


def extract_python_ast(
    graph: Graph,
    target: Path,
    file_path: Path,
    relative: str,
    *,
    import_aliases: tuple[ImportAlias, ...] = (),
) -> None:
    source = file_path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError:
        extract_code_lexical(graph, target, file_path, relative, import_aliases=import_aliases)
        return

    file_node = f"file:{relative}"
    lines = source.splitlines()
    local_symbols: dict[str, str] = {}
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
                    {},
                    import_aliases,
                    extractor="python.ast",
                    method="ast-import",
                    confidence="PROVEN",
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
                {},
                import_aliases,
                extractor="python.ast",
                method="ast-import-from",
                confidence="PROVEN",
            )

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            symbol_id = f"symbol:{relative}#{node.name}:{node.lineno}"
            local_symbols[node.name] = symbol_id
            graph.add_node(
                symbol_id,
                kind,
                node.name,
                source_path=relative,
                range=SourceRange(node.lineno),
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
                source=file_node,
                target=symbol_id,
                confidence="PROVEN",
                evidence_id=evidence_id,
            )
            graph.add_edge(
                kind="defines",
                source=file_node,
                target=symbol_id,
                confidence="PROVEN",
                evidence_id=evidence_id,
            )

    for owner in ast.walk(tree):
        if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        owner_id = local_symbols.get(owner.name)
        if not owner_id:
            continue
        for node in ast.walk(owner):
            if not isinstance(node, ast.Call):
                continue
            called_name = python_call_name(node.func)
            target_id = local_symbols.get(called_name or "")
            if not called_name or not target_id or target_id == owner_id:
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
                attributes={"function": called_name},
            )


def extract_code_lexical(
    graph: Graph,
    target: Path,
    file_path: Path,
    relative: str,
    *,
    import_aliases: tuple[ImportAlias, ...] = (),
) -> None:
    file_node = f"file:{relative}"
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    imported_bindings: dict[str, str] = {}

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
                import_aliases,
                method=statement.method,
                edge_kind=statement.edge_kind,
                bind_names=statement.bind_names,
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
                    import_aliases,
                )

    for line_number, line in enumerate(lines, start=1):
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
    import_aliases: tuple[ImportAlias, ...],
    *,
    extractor: str = "code.lexical",
    method: str | None = None,
    confidence: str | None = None,
    edge_kind: str = "imports",
    bind_names: bool = True,
) -> str:
    resolved = resolve_import(target, file_path, module, import_aliases)
    if resolved:
        target_relative = resolved.relative_to(target).as_posix()
        target_id = f"file:{target_relative}"
        edge_confidence = confidence or "DERIVED"
        edge_method = method or "lexical-import+relative-resolution"
        if bind_names:
            for binding in names:
                imported_bindings[binding] = target_id
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
        attributes={"module": module},
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
                attributes={"module": module, "symbol": binding},
            )
            graph.add_edge(
                kind=edge_kind,
                source=file_node,
                target=binding_id,
                confidence=edge_confidence,
                evidence_id=evidence_id,
                attributes={"module": module, "symbol": binding},
            )
            if bind_names:
                imported_bindings[binding] = binding_id
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


def js_module_statements(lines: list[str], suffix: str) -> list[JsModuleStatement]:
    if suffix not in JS_EXTENSIONS:
        return []
    statements: list[JsModuleStatement] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped.startswith(("import", "export", "const ", "let ", "var ")):
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
        index += 1
    return statements


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
) -> Path | None:
    if module.startswith("./") or module.startswith("../"):
        return resolve_candidate_base(target, file_path.parent / module)
    if module.startswith("."):
        return resolve_python_relative_import(target, file_path, module)
    for base in alias_candidate_bases(target, module, aliases):
        resolved = resolve_candidate_base(target, base)
        if resolved:
            return resolved
    return None


def resolve_relative_import(target: Path, file_path: Path, module: str) -> Path | None:
    if not module.startswith("."):
        return None
    if module.startswith("./") or module.startswith("../"):
        return resolve_candidate_base(target, file_path.parent / module)
    return resolve_python_relative_import(target, file_path, module)


def resolve_python_relative_import(target: Path, file_path: Path, module: str) -> Path | None:
    level = len(module) - len(module.lstrip("."))
    remainder = module[level:]
    base = file_path.parent
    for _ in range(max(level - 1, 0)):
        base = base.parent
    if remainder:
        base = base / Path(*remainder.split("."))
    return resolve_candidate_base(target, base)


def resolve_candidate_base(target: Path, base: Path) -> Path | None:
    base = base.resolve()
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
