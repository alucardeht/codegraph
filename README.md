# codegraph

[![Test](https://github.com/alucardeht/codegraph/actions/workflows/test.yml/badge.svg)](https://github.com/alucardeht/codegraph/actions/workflows/test.yml)

Evidence-backed graph indexing for technical collections.

`codegraph` builds a durable graph from source code, documentation, research
folders, configuration, logs, and mixed technical collections. It is designed to
give both humans and AI agents a strong first map of a target without writing
artifacts into that target by default.

It is not a Graphify wrapper, not tied to TypeScript, and not limited to
software repositories.

## Product Contract

`codegraph` optimizes for trustworthy orientation, not decorative diagrams.

- Every scan requires an explicit output directory.
- The target repository or collection is read-only by default.
- Generated output is written outside the target unless explicitly allowed.
- Freshness is inspectable before a graph is trusted.
- Every meaningful non-containment edge should have evidence.
- Incomplete extraction is reported as `partial` or `untrusted`, not hidden.
- Obsidian is a human export layer; `graph.json` and `manifest.json` are the
  canonical machine artifacts.

## What It Produces

Each scan writes:

- `graph.json`: canonical nodes, edges, evidence, confidence, and provenance.
- `manifest.json`: scan options, ignore policy, fingerprints, freshness, and
  quality gates.
- `report.md`: human-readable quality summary.
- `.ready`: marker written only after the graph is fully generated.
- `obsidian/`: optional human navigation export when `--export-obsidian` is
  passed.

Optional project behavior can be configured with `codegraph.toml` in the target
root or with `--config <path>`.

## Install For Local Development

From this repository:

```bash
python3 -m pip install -e .
```

Or run without installing:

```bash
PYTHONPATH=src python3 -m codegraph --help
```

## Commands

### Scan

Create a new graph. `--out` is required and should normally point outside the
target.

```bash
codegraph scan /path/to/target --out /path/to/output --export-obsidian
```

Useful options:

- `--export-obsidian`: generate the human-facing Obsidian vault export.
- `--replace-output`: delete and recreate the entire output directory before
  scanning. Use only when that directory is known to be disposable.
- `--include <path>`: deliberately include a path that ignore policy would
  normally skip.
- `--disable-default-ignore <name>`: disable one built-in default ignore such as
  `node_modules`.
- `--no-default-ignores`: disable all built-in default ignores.
- `--allow-output-inside-target`: explicitly permit generated output inside the
  analyzed target.
- `--config <path>`: load an explicit `codegraph.toml`.

### Status

Check whether an existing graph is current.

```bash
codegraph status /path/to/output
codegraph status /path/to/output --json
```

Status compares target membership, file size, and modification time. It is meant
to be cheap enough for repeated checks.

### Refresh

Rebuild an existing graph using the stored manifest contract.

```bash
codegraph refresh /path/to/output
```

Refresh keeps the managed output directory and reuses cached per-file extraction
results when it is safe to do so. It falls back to a full rebuild when target
membership, config, ignore policy, or import alias resolution changes.

The graph is marked not ready while refresh is rebuilding, then marked ready
only after `graph.json`, `manifest.json`, reports, and optional exports are
written.

### Watch

Poll an existing graph and refresh when it becomes stale.

```bash
codegraph watch /path/to/output --interval 2
```

This keeps a graph alive for long-running work. Consumers should still check
`.ready` or use `status` before relying on the output.

### Overview

Print an architecture-first JSON summary for agents and operators.

```bash
codegraph overview /path/to/output --limit 12
```

Use this before broad code investigation. It returns:

- freshness and quality
- node and edge kind counts
- top areas, domains, layers, roles, and features
- important files ranked by semantic graph degree
- important external modules
- stable agent entrypoints such as `layer:screens` or `feature:LoginScreen`
- warnings when coverage is partial

### Query

Return a focused evidence-backed subgraph.

```bash
codegraph query /path/to/output --node feature:LoginScreen --direction in --depth 1
codegraph query /path/to/output --node src/screens/LoginScreen.tsx --depth 2
```

Defaults are intentionally compact:

- traversal is outgoing-only
- containment edges are skipped
- all confidence classes are allowed

Use broader traversal only when intentional:

```bash
codegraph query /path/to/output --node layer:screens --direction in --depth 1
codegraph query /path/to/output --node src --direction both --include-containment --depth 2
codegraph query /path/to/output --node SomeNode --confidence PROVEN --confidence DERIVED
```

### Doctor

Validate graph integrity, freshness, quality, and Obsidian export consistency.

```bash
codegraph doctor /path/to/output
codegraph doctor /path/to/output --json
```

Use `doctor` after generation, before opening a graph for serious work, or after
a watch/refresh cycle.

### Export

Rebuild the human export from an existing ready graph.

```bash
codegraph export /path/to/output
```

### Open

Print the Obsidian export path, or open it with the system default handler.

```bash
codegraph open /path/to/output
codegraph open /path/to/output --system
```

### Clean

Delete a managed graph output directory. This is intentionally explicit and
refuses to delete without `--yes`.

```bash
codegraph clean /path/to/output --yes
```

`clean` only deletes directories that look like `codegraph` outputs.

## Configuration

`codegraph.toml` is optional. Scans remain useful without it.

Example:

```toml
[scan]
include = ["fixtures"]
disable_default_ignore = ["node_modules"]

[imports.aliases]
"@/*" = "src/*"
"@components/*" = "src/components/*"

[architecture]
feature_markers = ["domains", "packages"]
generic_feature_names = ["internal"]
```

Supported sections:

- `[scan] include`: paths that should override ignore policy.
- `[scan] disable_default_ignore`: built-in ignore names to disable.
- `[scan] no_default_ignores`: disable every built-in ignore.
- `[imports.aliases]`: import path aliases. `*` wildcards are supported.
- `[architecture] feature_markers`: path segments whose next segment should be
  treated as a feature name.
- `[architecture] generic_feature_names`: additional names that should not
  become feature nodes.

The manifest records the config path, effective config, and config fingerprint.
Changing the config makes `status` report the graph as stale.

Scans also derive internal package aliases from discovered `package.json` files.
For example, a package named `@repo/ui` can make imports from `@repo/ui`
resolve to that package's source entrypoint instead of appearing as an external
module.

## Architecture Model

The graph has two complementary layers.

The evidence layer stores direct extracted facts:

- files and directories
- symbols and sections
- imports, exports, renders, definitions, references, and simple citations
- Python AST structure including class methods, relative import levels, safe
  local method call resolution, and evidenced decorator/base-class links
- JS/TS module forms including type imports, re-exports, `require`, dynamic
  `import()`, `require.resolve()`, and CommonJS export signals
- internal package imports derived from `package.json` names
- Markdown concepts and claim signals as inferred research/documentation edges,
  with concept-hub suppression and simple reference/footnote capture
- config files and keys
- logs and log statements
- assets and generated artifacts as metadata-backed nodes
- external modules and imported symbols

The architecture layer adds inferred orientation:

- `area`: top-level target area such as `src`, `docs`, or `assets`
- `domain`: material type such as code, documentation, configuration, asset, or
  observability
- `layer`: structural layer such as screens, components, hooks, networking,
  state, models, tests, utilities, docs, or config
- `role`: file role such as screen, component, hook, api, state, style, type,
  test, model, documentation, or configuration
- `feature`: product or topic grouping inferred from meaningful path segments

Architecture edges are `INFERRED`. They are meant for discovery and orientation,
while parser and lexical facts remain the stronger evidence for final changes.

The manifest includes extractor declarations so agents can see which node kinds
and edge kinds each extractor is expected to produce.
Quality summaries also record observed node and edge kinds by extractor and
content domain for auditability across code, docs, config, log, asset, and
artifact-heavy collections.

## Obsidian Export

When `--export-obsidian` is enabled, `codegraph` writes a navigable vault under
`<output>/obsidian`.

Important sections:

- `index.md`: freshness, quality, totals, and navigation.
- `Dashboards/Architecture.md`: ranked architecture summary.
- `Dashboards/Entrypoints.md`: recommended starts for humans and agents.
- `Dashboards/Domains.md`: material-domain hubs with linked file reasons.
- `Dashboards/Roles.md`: role hubs with linked file reasons.
- `Dashboards/Features.md`: ranked feature summary.
- `Dashboards/Layers.md`: ranked layer summary.
- `Dashboards/Graph Views.md`: human-readable graph search presets.
- `Dashboards/Research.md`: concepts and claims from documentation/research.
- `Indexes/Architecture.md`: high-level architecture nodes.
- `Indexes/Features.md`: product/topic groupings.
- `Indexes/Layers.md`: structural layers.
- `Indexes/Roles.md`: file roles.
- `Indexes/Domains.md`: material domains.
- `Indexes/Files.md`: source files.
- `Indexes/Concepts.md`: inferred documentation/research concepts.
- `Indexes/Claims.md`: inferred documentation/research claim signals.
- `Indexes/Assets.md`: asset metadata nodes.
- `Indexes/Artifacts.md`: generated or artifact metadata nodes.
- `Indexes/Config.md`: configuration files and keys.
- `Indexes/Observability.md`: log files and statements.

The default graph view search is tuned toward `Architecture` and `Files` so the
first visual impression is structural instead of a dense cloud of every symbol.
`Dashboards/Graph Views.md` also records human-readable filter presets without
depending on undocumented Obsidian vault schema beyond the generated
`.obsidian/graph.json`.

Architecture dashboards include trust notes and now surface top linked files
with visible `belongs_to` / `categorized_as` reasons plus semantic edge counts.
Treat those hubs as orientation for where to look next, then confirm the linked
source note or file before making edits.

## Agent Workflow

For an AI agent using an existing graph:

1. Run `codegraph status <output> --json`.
2. If stale, run `codegraph refresh <output>` or ask the operator.
3. Run `codegraph doctor <output> --json`.
4. Run `codegraph overview <output> --limit 20`.
5. Pick stable entrypoints from `agent_entrypoints`.
6. Use `query` to inspect focused subgraphs before falling back to direct file
   search.
7. Treat `INFERRED` edges as orientation and `PROVEN`/`DERIVED` edges as stronger
   planning evidence.

For the full protocol, see [AGENT_PROTOCOL.md](AGENT_PROTOCOL.md).

This workflow is meant to reduce broad grep passes, not ban source inspection.
The graph should answer "where should I look first?" and "what is connected to
this?" before deeper implementation work begins.

## Human Workflow

For a human reading a target:

1. Generate with `--export-obsidian`.
2. Open `<output>/obsidian` as a vault or copy/link it into an existing vault.
3. Start from `index.md`.
4. Open the graph view; the default filter emphasizes Architecture and Files.
5. Use `Dashboards/Features.md`, `Dashboards/Layers.md`, `Dashboards/Domains.md`,
   and `Dashboards/Roles.md` to pivot from hubs into concrete files with visible
   reasons and counts.
6. Check the trust notes before treating inferred architecture as planning proof.

## Quality Status

`passed` means the graph met the current integrity and coverage gates.

`partial` means the graph is useful but should not be treated as complete. Common
causes:

- unsupported assets or binary files
- unknown file types
- extractor failures
- supported files with too little semantic information
- coverage below configured thresholds

`untrusted` means critical integrity or very low coverage made the graph unsafe
as a planning artifact.

## Ignore Behavior

Default ignores protect scans from generated, vendored, dependency, cache, and
build surfaces. Examples include dependency folders, VCS metadata, build outputs,
and generated graph artifacts.

Use explicit override flags when those paths are intentionally part of the
analysis. Overrides are recorded in `manifest.json`.

## Development

Run tests:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
```

The test suite includes benchmark fixtures for:

- alias-heavy TypeScript application structure
- non-code research notes
- configuration, logs, assets, and generated artifacts

Generate a disposable fixture graph:

```bash
PYTHONPATH=src python3 -m codegraph scan ./tests --out /tmp/codegraph-tests --export-obsidian
PYTHONPATH=src python3 -m codegraph overview /tmp/codegraph-tests
PYTHONPATH=src python3 -m codegraph doctor /tmp/codegraph-tests
```
