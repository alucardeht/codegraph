from __future__ import annotations

import argparse
import json
import shutil
import time
import webbrowser
from pathlib import Path

from .overview import graph_doctor, graph_overview
from .scanner import OBSIDIAN_DIR, ScanOptions, scan, write_obsidian_export
from .query import load_graph, query_subgraph
from .status import graph_status, load_manifest


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "scan":
            require_output(args.output)
            manifest = scan(
                ScanOptions(
                    target=Path(args.target),
                    output=Path(args.output),
                    include=tuple(args.include),
                    disable_default_ignore=tuple(args.disable_default_ignore),
                    no_default_ignores=args.no_default_ignores,
                    allow_output_inside_target=args.allow_output_inside_target,
                    export_obsidian=args.export_obsidian,
                    replace_output=args.replace_output,
                    config=Path(args.config) if args.config else None,
                )
            )
            print(f"Graph written to {manifest['output']}")
            print(f"Freshness: {manifest['freshness']}")
            print(f"Quality: {manifest['quality']['status']}")
            return 0

        if args.command == "status":
            result = graph_status(Path(args.output))
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"Freshness: {result['freshness']}")
                if result["freshness"] == "stale":
                    print(f"Added: {len(result['added'])}")
                    print(f"Changed: {len(result['changed'])}")
                    print(f"Deleted: {len(result['deleted'])}")
                if result["freshness"] == "failed":
                    print(f"Reason: {result['reason']}")
            return 0 if result["freshness"] == "current" else 2

        if args.command == "refresh":
            manifest = load_manifest(Path(args.output).resolve())
            options = manifest.get("scan_options", {})
            refreshed = scan(
                ScanOptions(
                    target=Path(manifest["target"]),
                    output=Path(manifest["output"]),
                    include=tuple(options.get("include", [])),
                    disable_default_ignore=tuple(options.get("disable_default_ignore", [])),
                    no_default_ignores=bool(options.get("no_default_ignores", False)),
                    allow_output_inside_target=bool(
                        options.get("allow_output_inside_target", False)
                    ),
                    export_obsidian=bool(options.get("export_obsidian", False)),
                    incremental=True,
                    allow_existing_output=True,
                    config=Path(options["config"]) if options.get("config") else None,
                )
            )
            print(f"Graph refreshed at {refreshed['output']}")
            return 0

        if args.command == "watch":
            watch(Path(args.output), interval=args.interval)
            return 0

        if args.command == "query":
            result = query_subgraph(
                Path(args.output),
                node=args.node,
                depth=args.depth,
                confidence=set(args.confidence) if args.confidence else None,
                direction=args.direction,
                include_containment=args.include_containment,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if not result["warnings"] else 2

        if args.command == "overview":
            result = graph_overview(Path(args.output), limit=args.limit)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["freshness"]["freshness"] == "current" else 2

        if args.command == "doctor":
            result = graph_doctor(Path(args.output))
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"Doctor: {result['status']}")
                print(f"Freshness: {result['freshness']['freshness']}")
                print(f"Quality: {result['quality']['status']}")
                for item in result["checks"]:
                    status = "pass" if item["passed"] else "fail"
                    print(f"- {item['name']}: {status} ({item['value']})")
            return 0 if result["status"] == "passed" else 2

        if args.command == "export":
            output = Path(args.output).resolve()
            graph = load_graph(output)
            manifest = load_manifest(output)
            write_obsidian_export(output / OBSIDIAN_DIR, graph, manifest)
            print(f"Obsidian export written to {output / OBSIDIAN_DIR}")
            return 0

        if args.command == "open":
            obsidian_path = Path(args.output).resolve() / OBSIDIAN_DIR
            if not obsidian_path.is_dir():
                raise ValueError(f"No Obsidian export found at {obsidian_path}")
            print(obsidian_path)
            if args.system:
                webbrowser.open(obsidian_path.as_uri())
            return 0

        if args.command == "clean":
            output = Path(args.output).resolve()
            if not args.yes:
                raise ValueError("Refusing to delete output without --yes")
            validate_managed_output(output)
            shutil.rmtree(output)
            print(f"Deleted managed graph output {output}")
            return 0
    except ValueError as error:
        parser.exit(1, f"Error: {error}\n")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codegraph")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan a target into a graph output directory.")
    scan_parser.add_argument("target", help="Source collection to scan.")
    scan_parser.add_argument("--out", dest="output", required=True, help="Required output directory.")
    scan_parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Deliberately include a path that ignore policy would otherwise skip.",
    )
    scan_parser.add_argument(
        "--disable-default-ignore",
        action="append",
        default=[],
        help="Disable one built-in default ignore pattern, such as node_modules.",
    )
    scan_parser.add_argument(
        "--no-default-ignores",
        action="store_true",
        help="Disable all built-in default ignore patterns.",
    )
    scan_parser.add_argument(
        "--allow-output-inside-target",
        action="store_true",
        help="Explicitly permit output artifacts inside the scanned target.",
    )
    scan_parser.add_argument(
        "--export-obsidian",
        action="store_true",
        help="Generate a human-facing Obsidian export from the graph.",
    )
    scan_parser.add_argument(
        "--replace-output",
        action="store_true",
        help=(
            "Delete and recreate the entire --out directory before scanning. "
            "Use with care: every file inside that output directory is removed."
        ),
    )
    scan_parser.add_argument(
        "--config",
        help=(
            "Optional codegraph.toml path. Defaults to codegraph.toml in the target root "
            "when present."
        ),
    )

    status_parser = subparsers.add_parser("status", help="Check graph freshness.")
    status_parser.add_argument("output", help="Existing graph output directory.")
    status_parser.add_argument("--json", action="store_true", help="Print machine-readable status.")

    refresh_parser = subparsers.add_parser("refresh", help="Refresh an existing graph output.")
    refresh_parser.add_argument("output", help="Existing graph output directory.")

    watch_parser = subparsers.add_parser("watch", help="Periodically refresh a stale graph.")
    watch_parser.add_argument("output", help="Existing graph output directory.")
    watch_parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds.")

    query_parser = subparsers.add_parser("query", help="Return a focused evidence-backed subgraph.")
    query_parser.add_argument("output", help="Existing graph output directory.")
    query_parser.add_argument("--node", required=True, help="Node id, path, label, or substring.")
    query_parser.add_argument("--depth", type=int, default=1, help="Traversal depth.")
    query_parser.add_argument(
        "--direction",
        choices=["out", "in", "both"],
        default="out",
        help="Traversal direction. Defaults to outgoing edges only.",
    )
    query_parser.add_argument(
        "--include-containment",
        action="store_true",
        help="Include containment edges in traversal.",
    )
    query_parser.add_argument(
        "--confidence",
        action="append",
        choices=["PROVEN", "DERIVED", "INFERRED", "UNRESOLVED"],
        help="Allowed confidence class. May be repeated.",
    )

    overview_parser = subparsers.add_parser(
        "overview",
        help="Print a compact architecture-first summary for agents and operators.",
    )
    overview_parser.add_argument("output", help="Existing graph output directory.")
    overview_parser.add_argument(
        "--limit",
        type=int,
        default=12,
        help="Maximum number of ranked items per overview section.",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Validate graph integrity, freshness, quality gates, and Obsidian export consistency.",
    )
    doctor_parser.add_argument("output", help="Existing graph output directory.")
    doctor_parser.add_argument("--json", action="store_true", help="Print machine-readable diagnostics.")

    export_parser = subparsers.add_parser(
        "export",
        help="Rebuild human exports from an existing ready graph.",
    )
    export_parser.add_argument("output", help="Existing graph output directory.")

    open_parser = subparsers.add_parser(
        "open",
        help="Print the Obsidian export path, optionally opening it with the system default app.",
    )
    open_parser.add_argument("output", help="Existing graph output directory.")
    open_parser.add_argument(
        "--system",
        action="store_true",
        help="Open the Obsidian export directory using the system default handler.",
    )

    clean_parser = subparsers.add_parser(
        "clean",
        help="Delete a managed graph output directory. Requires --yes.",
    )
    clean_parser.add_argument("output", help="Existing graph output directory.")
    clean_parser.add_argument("--yes", action="store_true", help="Confirm deletion of the output directory.")

    return parser


def require_output(output: str | None) -> None:
    if not output:
        raise ValueError("Output directory is required. Pass --out explicitly.")


def validate_managed_output(output: Path) -> None:
    if not output.is_dir():
        raise ValueError(f"Output directory does not exist: {output}")
    if not (output / "manifest.json").is_file() or not (output / "graph.json").is_file():
        raise ValueError(f"Refusing to delete unmanaged directory: {output}")


def watch(output: Path, *, interval: float) -> None:
    print(f"Watching graph output {output}. Press Ctrl+C to stop.")
    try:
        while True:
            result = graph_status(output)
            if result["freshness"] == "stale":
                print("Graph is stale; refreshing.")
                manifest = load_manifest(output.resolve())
                options = manifest.get("scan_options", {})
                scan(
                    ScanOptions(
                        target=Path(manifest["target"]),
                        output=Path(manifest["output"]),
                        include=tuple(options.get("include", [])),
                        disable_default_ignore=tuple(options.get("disable_default_ignore", [])),
                        no_default_ignores=bool(options.get("no_default_ignores", False)),
                        allow_output_inside_target=bool(
                            options.get("allow_output_inside_target", False)
                        ),
                        export_obsidian=bool(options.get("export_obsidian", False)),
                        incremental=True,
                        allow_existing_output=True,
                        config=Path(options["config"]) if options.get("config") else None,
                    )
                )
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped.")
