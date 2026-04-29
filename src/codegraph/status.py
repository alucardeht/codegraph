from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ignore import IgnorePolicy
from .scanner import MANIFEST_FILE, READY_FILE, discover_files


def load_manifest(output: Path) -> dict[str, Any]:
    manifest_path = output / MANIFEST_FILE
    if not manifest_path.is_file():
        raise ValueError(f"No manifest found at {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def graph_status(output: Path) -> dict[str, Any]:
    output = output.resolve()
    manifest = load_manifest(output)
    if not (output / READY_FILE).is_file():
        return {
            "freshness": "building",
            "reason": "ready_marker_missing",
            "target": manifest.get("target"),
            "output": str(output),
        }
    target = Path(manifest["target"]).resolve()
    if not target.is_dir():
        return {
            "freshness": "failed",
            "reason": "target_missing",
            "target": str(target),
            "output": str(output),
        }

    options = manifest.get("effective_scan_options") or manifest.get("scan_options", {})
    policy = IgnorePolicy(
        target=target,
        include=options.get("include", []),
        disable_default=options.get("disable_default_ignore", []),
        no_default_ignores=bool(options.get("no_default_ignores", False)),
        runtime_ignore=runtime_ignore_patterns(target, output),
    )
    skipped: list[dict[str, str]] = []
    files = discover_files(target, policy, skipped)
    current = stat_files(target, files)
    previous = manifest.get("source_fingerprints", {})
    config_changed = changed_config(manifest)

    added = sorted(set(current) - set(previous))
    deleted = sorted(set(previous) - set(current))
    changed = sorted(
        path
        for path in set(current) & set(previous)
        if current[path].get("mtime_ns") != previous[path].get("mtime_ns")
        or current[path].get("size") != previous[path].get("size")
    )

    freshness = "current" if not added and not deleted and not changed and not config_changed else "stale"
    return {
        "freshness": freshness,
        "target": str(target),
        "output": str(output),
        "added": added,
        "deleted": deleted,
        "changed": changed,
        "config_changed": config_changed,
        "indexed_file_count": len(previous),
        "current_file_count": len(current),
    }


def runtime_ignore_patterns(target: Path, output: Path) -> list[str]:
    try:
        return [output.relative_to(target).as_posix()]
    except ValueError:
        return []


def stat_files(target: Path, files: list[Path]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for file_path in files:
        relative = file_path.relative_to(target).as_posix()
        stat = file_path.stat()
        metadata[relative] = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    return metadata


def changed_config(manifest: dict[str, Any]) -> bool:
    previous = manifest.get("config_fingerprint")
    config_path = manifest.get("scan_options", {}).get("config")
    if not previous and not config_path:
        return False
    if not config_path:
        return False
    path = Path(config_path)
    if not path.is_file():
        return True
    stat = path.stat()
    return previous != {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
