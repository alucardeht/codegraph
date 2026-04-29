# Changelog

## Unreleased

- Optional `codegraph.toml` configuration for scan policy, import aliases, and
  architecture feature markers.
- Import alias resolution for wildcard and prefix mappings.
- Python AST extraction for parser-backed imports, definitions, relative import
  levels, class methods, safe `self.method()` resolution, and evidenced
  decorator/base-class links.
- Stronger JS/TS module extraction for type imports, re-exports, `require`,
  dynamic `import()`, `require.resolve()`, and CommonJS export signals.
- Internal package import resolution from discovered `package.json` names.
- Incremental refresh cache for safe changed-file rebuilds.
- Extractor capability declarations in the manifest.
- Markdown concept and claim extraction with inferred confidence, concept-hub
  suppression, and simple reference/footnote citation capture.
- Quality summaries now expose observed node and edge kinds by extractor and
  content domain without penalizing non-code collections for code-style density.
- Obsidian entrypoints dashboard for human and agent starts.
- Obsidian research dashboard and indexes for concepts and claims.
- Obsidian dashboards for architecture, features, and layers.
- Operator commands for export rebuilds, Obsidian export path discovery, and
  confirmed output cleanup.
- Agent protocol, benchmark fixtures, release checklist, and CI workflow.

## 0.1.0

Initial public baseline.

- Evidence-backed scans for code, docs, configuration, logs, assets, and
  generated artifacts.
- Explicit output path and safe target-write defaults.
- Freshness status, refresh, watch, and ready marker.
- Compact query command with evidence and confidence filtering.
- Architecture enrichment for areas, domains, layers, roles, and features.
- Agent-oriented overview and graph doctor commands.
- Obsidian export with architecture-first navigation.
