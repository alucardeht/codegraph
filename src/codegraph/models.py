from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


Confidence = str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_path(path: Path) -> str:
    return path.as_posix()


@dataclass(frozen=True)
class SourceRange:
    start_line: int
    start_column: int = 1
    end_line: int | None = None
    end_column: int | None = None

    def to_dict(self) -> dict[str, int | None]:
        return {
            "start_line": self.start_line,
            "start_column": self.start_column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


@dataclass
class Node:
    id: str
    kind: str
    label: str
    source_path: str | None = None
    range: SourceRange | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "source_path": self.source_path,
            "range": self.range.to_dict() if self.range else None,
            "attributes": self.attributes,
        }


@dataclass
class Evidence:
    id: str
    extractor: str
    method: str
    source_locator: str
    snippet: str
    confidence: Confidence
    captured_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "extractor": self.extractor,
            "method": self.method,
            "source_locator": self.source_locator,
            "snippet": self.snippet,
            "confidence": self.confidence,
            "captured_at": self.captured_at,
        }


@dataclass
class Edge:
    id: str
    kind: str
    source: str
    target: str
    confidence: Confidence
    evidence_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "from": self.source,
            "to": self.target,
            "confidence": self.confidence,
            "evidence_id": self.evidence_id,
            "attributes": self.attributes,
        }
