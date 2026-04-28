from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path


DEFAULT_IGNORE_PATTERNS = [
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    ".coverage",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "__pycache__",
    ".expo",
    ".next",
    ".turbo",
    ".gradle",
    "Pods",
    "DerivedData",
    ".DS_Store",
]

TARGET_IGNORE_FILES = [
    ".gitignore",
    ".npmignore",
    ".dockerignore",
]


@dataclass(frozen=True)
class IgnoreDecision:
    ignored: bool
    reason: str | None = None


@dataclass(frozen=True)
class IgnoreRule:
    pattern: str
    source: str
    negated: bool = False

    def matches(self, relative_path: str, is_dir: bool) -> bool:
        path = relative_path.rstrip("/")
        pattern = self.pattern.rstrip("/")
        if not pattern:
            return False
        candidates = [path, f"{path}/"] if is_dir else [path]
        if "/" not in pattern:
            parts = path.split("/")
            return any(fnmatch.fnmatch(part, pattern) for part in parts)
        return any(
            fnmatch.fnmatch(candidate, pattern)
            or fnmatch.fnmatch(candidate, f"{pattern}/**")
            or candidate.startswith(f"{pattern}/")
            for candidate in candidates
        )


class IgnorePolicy:
    def __init__(
        self,
        *,
        target: Path,
        include: list[str] | None = None,
        disable_default: list[str] | None = None,
        no_default_ignores: bool = False,
        runtime_ignore: list[str] | None = None,
    ) -> None:
        self.target = target
        self.includes = [item.strip().strip("/") for item in include or [] if item.strip()]
        self.disable_default = {
            item.strip().strip("/") for item in disable_default or [] if item.strip()
        }
        self.rules: list[IgnoreRule] = []

        if not no_default_ignores:
            for pattern in DEFAULT_IGNORE_PATTERNS:
                if pattern not in self.disable_default:
                    self.rules.append(IgnoreRule(pattern=pattern, source="default"))

        self.rules.extend(load_target_ignore_rules(target))
        for pattern in runtime_ignore or []:
            clean = pattern.strip().strip("/")
            if clean:
                self.rules.append(IgnoreRule(pattern=clean, source="runtime"))

    def decide(self, relative_path: str, *, is_dir: bool) -> IgnoreDecision:
        normalized = relative_path.strip("/")
        if any(path_matches(normalized, include, is_dir=is_dir) for include in self.includes):
            return IgnoreDecision(False, "explicit include")

        ignored = False
        reason: str | None = None
        for rule in self.rules:
            if rule.matches(normalized, is_dir):
                ignored = not rule.negated
                reason = f"{rule.source}:{rule.pattern}"
        return IgnoreDecision(ignored, reason if ignored else None)

    def to_dict(self) -> dict[str, object]:
        return {
            "default_patterns": [
                rule.pattern for rule in self.rules if rule.source == "default"
            ],
            "target_ignore_files": TARGET_IGNORE_FILES,
            "include_overrides": self.includes,
            "disabled_default_patterns": sorted(self.disable_default),
            "rules": [
                {"pattern": rule.pattern, "source": rule.source, "negated": rule.negated}
                for rule in self.rules
            ],
        }


def load_target_ignore_rules(target: Path) -> list[IgnoreRule]:
    rules: list[IgnoreRule] = []
    for ignore_file in TARGET_IGNORE_FILES:
        path = target / ignore_file
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            pattern = line[1:] if negated else line
            pattern = pattern.strip().strip("/")
            if pattern:
                rules.append(IgnoreRule(pattern=pattern, source=ignore_file, negated=negated))
    return rules


def path_matches(relative_path: str, pattern: str, *, is_dir: bool) -> bool:
    normalized = relative_path.rstrip("/")
    clean_pattern = pattern.rstrip("/")
    if normalized == clean_pattern or normalized.startswith(f"{clean_pattern}/"):
        return True
    if is_dir and clean_pattern.startswith(f"{normalized}/"):
        return True
    if "/" not in clean_pattern:
        return any(part == clean_pattern or fnmatch.fnmatch(part, clean_pattern) for part in normalized.split("/"))
    candidates = [normalized, f"{normalized}/"] if is_dir else [normalized]
    return any(fnmatch.fnmatch(candidate, clean_pattern) for candidate in candidates)
