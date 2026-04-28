from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tomllib


CONFIG_FILENAME = "codegraph.toml"


@dataclass(frozen=True)
class ImportAlias:
    pattern: str
    target: str

    def to_dict(self) -> dict[str, str]:
        return {"pattern": self.pattern, "target": self.target}


@dataclass(frozen=True)
class CodegraphConfig:
    path: Path | None = None
    include: tuple[str, ...] = ()
    disable_default_ignore: tuple[str, ...] = ()
    no_default_ignores: bool = False
    import_aliases: tuple[ImportAlias, ...] = ()
    feature_markers: tuple[str, ...] = ()
    generic_feature_names: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path) if self.path else None,
            "include": list(self.include),
            "disable_default_ignore": list(self.disable_default_ignore),
            "no_default_ignores": self.no_default_ignores,
            "import_aliases": [item.to_dict() for item in self.import_aliases],
            "feature_markers": list(self.feature_markers),
            "generic_feature_names": list(self.generic_feature_names),
        }


def load_codegraph_config(target: Path, explicit_path: Path | None = None) -> CodegraphConfig:
    path = resolve_config_path(target, explicit_path)
    if path is None:
        return CodegraphConfig()
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"Could not read config file {path}: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"Invalid TOML config file {path}: {error}") from error
    return parse_config_payload(path, payload)


def resolve_config_path(target: Path, explicit_path: Path | None) -> Path | None:
    if explicit_path:
        path = explicit_path.expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"Config file does not exist: {path}")
        return path
    candidate = target / CONFIG_FILENAME
    return candidate if candidate.is_file() else None


def parse_config_payload(path: Path, payload: dict[str, Any]) -> CodegraphConfig:
    scan = table(payload, "scan")
    imports = table(payload, "imports")
    architecture = table(payload, "architecture")
    aliases = table(imports, "aliases")
    return CodegraphConfig(
        path=path,
        include=string_tuple(scan.get("include", ()), "scan.include"),
        disable_default_ignore=string_tuple(
            scan.get("disable_default_ignore", ()),
            "scan.disable_default_ignore",
        ),
        no_default_ignores=bool(scan.get("no_default_ignores", False)),
        import_aliases=parse_import_aliases(aliases),
        feature_markers=string_tuple(architecture.get("feature_markers", ()), "architecture.feature_markers"),
        generic_feature_names=string_tuple(
            architecture.get("generic_feature_names", ()),
            "architecture.generic_feature_names",
        ),
    )


def table(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"Config section [{key}] must be a table")
    return value


def string_tuple(value: Any, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        raise ValueError(f"Config value {key} must be a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"Config value {key} must be a list of strings")
        clean = item.strip().strip("/")
        if clean:
            result.append(clean)
    return tuple(result)


def parse_import_aliases(aliases: dict[str, Any]) -> tuple[ImportAlias, ...]:
    parsed: list[ImportAlias] = []
    for pattern, target in sorted(aliases.items()):
        if not isinstance(pattern, str) or not isinstance(target, str):
            raise ValueError("Import aliases must map string patterns to string targets")
        clean_pattern = pattern.strip()
        clean_target = target.strip()
        if clean_pattern and clean_target:
            parsed.append(ImportAlias(clean_pattern, clean_target))
    return tuple(parsed)


def config_fingerprint(config: CodegraphConfig) -> dict[str, int] | None:
    if config.path is None:
        return None
    stat = config.path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
