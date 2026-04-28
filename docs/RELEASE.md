# Release Checklist

Use this checklist before publishing a tagged release or package.

## Preflight

- Confirm `main` is green in CI.
- Run local tests:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
```

- Run fixture scans:

```bash
for fixture in tests/fixtures/*; do
  out="$(mktemp -d)"
  rm -rf "$out"
  PYTHONPATH=src python3 -m codegraph scan "$fixture" --out "$out" --export-obsidian
  PYTHONPATH=src python3 -m codegraph doctor "$out"
done
```

## Documentation

- Update `README.md` for new commands or behavior.
- Update `AGENT_PROTOCOL.md` when agent-facing behavior changes.
- Update `ROADMAP.md` status for completed or deferred work.
- Update `CHANGELOG.md` with user-visible changes.

## Versioning

- Update `pyproject.toml`.
- Commit the version change.
- Tag the release.
- Push branch and tag.

## Trust Checks

- Generate a graph for at least one real project outside that target's repo.
- Run `doctor`, `overview`, and at least one focused `query`.
- Confirm generated output does not enter the scanned target.

