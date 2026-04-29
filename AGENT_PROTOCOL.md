# Codegraph Agent Protocol

This protocol is for AI agents and automation using an existing `codegraph`
output as a planning aid.

The graph is a first-orientation tool. It should narrow the search space and
surface relationships before source inspection begins. It does not replace
reading the source when a change must be made.

## Required Sequence

1. Run `codegraph status <output> --json`.
2. If freshness is not `current`, refresh the graph or stop and report staleness.
3. Run `codegraph doctor <output> --json`.
4. If doctor status is not `passed`, treat the graph as unsafe for planning.
5. Run `codegraph overview <output> --limit 20`.
6. Choose entrypoints from `agent_entrypoints`, `architecture`, or
   `important_files`.
7. When a narrower machine-readable slice is useful, run
   `codegraph query <output> --node <entrypoint>` with focused traversal.
8. Read source files after the graph has narrowed the likely area.

## Trust Rules

- `PROVEN`: direct extractor evidence. Safe as planning evidence when fresh.
- `DERIVED`: deterministic resolution based on proven facts. Safe for planning,
  but verify before edits.
- `INFERRED`: architecture or heuristic enrichment. Use for orientation and
  hypothesis generation.
- `UNRESOLVED`: attempted extraction with incomplete resolution. Treat as a
  warning and inspect source.

Never present stale graph data as current.

## Focused Subgraph Command

`codegraph query` is a graph subgraph inspector, not a search engine. Use it
after `overview` has identified a concrete node, file, feature, layer, role,
domain, symbol, concept, claim, or external module to inspect.

Default behavior is intentionally compact:

- outgoing traversal
- no containment traversal
- all confidence classes included

Use broader traversal deliberately:

```bash
codegraph query graph-out --node layer:screens --direction in --depth 1
codegraph query graph-out --node feature:Billing --direction in --depth 2
codegraph query graph-out --node src/app.py --confidence PROVEN --confidence DERIVED
```

Avoid `--include-containment` unless the task is explicitly about directory
shape. Containment can expand quickly on large targets.

## Handling Quality States

`passed`:

- Use the graph normally.
- Still verify source before editing.

`partial`:

- Use the graph for orientation.
- Surface the coverage warning in your plan or report.
- Prefer `PROVEN` and `DERIVED` edges.

`untrusted`:

- Do not rely on the graph for planning.
- Report the failing doctor or quality gates.
- Fall back to direct investigation.

## Impact Analysis Pattern

1. Start with the changed file, symbol, feature, layer, or external module.
2. Inspect incoming edges first to find dependents.
3. Inspect outgoing edges to find dependencies.
4. Inspect evidence on critical edges.
5. Read only the files returned by the focused subgraph before broad search.

Example:

```bash
codegraph query graph-out --node imported-symbol:legacy-sdk#OldClient --direction in --depth 1
```

## Migration Pattern

1. Inspect the old API or symbol with a focused subgraph.
2. Rank returned files by feature and layer from `overview`.
3. Migrate one feature/layer slice at a time.
4. Refresh the graph after the migration.
5. Inspect the old API again to confirm no known usages remain.

## Human Handoff

When reporting graph-backed findings to a human, include:

- freshness
- doctor status
- quality status
- focused graph command used
- confidence class of important edges
- any partial/untrusted warnings
