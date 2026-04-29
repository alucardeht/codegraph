from __future__ import annotations

import json
import contextlib
import io
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from codegraph import extractors as extractor_module
from codegraph.cli import main
from codegraph.extractors import ExtractionContext, classify_content_domain, resolve_import
from codegraph.ignore import IgnorePolicy
from codegraph.scanner import ScanOptions, unique_obsidian_note_paths, scan
from codegraph.status import graph_status


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class CodegraphTests(unittest.TestCase):
    def test_scan_requires_external_output_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "target"
            target.mkdir()
            output = target / "graph"
            with self.assertRaisesRegex(ValueError, "inside the target"):
                scan(ScanOptions(target=target, output=output))

    def test_scan_writes_graph_manifest_report_and_obsidian_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            (target / "README.md").write_text(
                "# Project\n\nSee [Architecture](docs/architecture.md).\n",
                encoding="utf-8",
            )
            (target / "app.py").write_text(
                "import os\n\nfrom package.module import thing\n\nclass App:\n    pass\n",
                encoding="utf-8",
            )

            manifest = scan(ScanOptions(target=target, output=output, export_obsidian=True))
            graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["freshness"], "current")
            self.assertTrue((output / "manifest.json").is_file())
            self.assertTrue((output / "report.md").is_file())
            self.assertTrue((output / ".ready").is_file())
            self.assertTrue((output / "obsidian" / "index.md").is_file())
            self.assertTrue((output / "obsidian" / "Indexes" / "Architecture.md").is_file())
            self.assertTrue((output / "obsidian" / "Indexes" / "Features.md").is_file())
            self.assertTrue((output / "obsidian" / "Indexes" / "Layers.md").is_file())
            self.assertTrue((output / "obsidian" / "Dashboards" / "Architecture.md").is_file())
            self.assertTrue((output / "obsidian" / "Dashboards" / "Entrypoints.md").is_file())
            self.assertTrue((output / "obsidian" / "Dashboards" / "Domains.md").is_file())
            self.assertTrue((output / "obsidian" / "Dashboards" / "Roles.md").is_file())
            self.assertTrue((output / "obsidian" / "Dashboards" / "Features.md").is_file())
            self.assertTrue((output / "obsidian" / "Dashboards" / "Layers.md").is_file())
            self.assertTrue((output / "obsidian" / "Dashboards" / "Graph Views.md").is_file())
            self.assertTrue(
                (output / "obsidian" / "Symbols" / "app.py__App_L5.md").is_file()
            )
            index = (output / "obsidian" / "index.md").read_text(encoding="utf-8")
            self.assertGreaterEqual(len(graph["nodes"]), 5)
            self.assertTrue(any(edge["kind"] == "references" for edge in graph["edges"]))
            self.assertTrue(any(edge["kind"] == "imports" for edge in graph["edges"]))
            self.assertTrue(any(edge["kind"] == "defines" for edge in graph["edges"]))
            self.assertTrue(any(edge["kind"] == "belongs_to" for edge in graph["edges"]))
            self.assertTrue(any(node["kind"] == "layer" for node in graph["nodes"]))
            self.assertTrue(any(node["id"] == "domain:documentation" for node in graph["nodes"]))
            self.assertTrue(any(node["id"] == "area:root" for node in graph["nodes"]))
            self.assertEqual(manifest["quality"]["missing_edge_endpoint_count"], 0)
            self.assertEqual(manifest["quality"]["missing_evidence_reference_count"], 0)
            self.assertEqual(manifest["quality"]["invalid_source_path_count"], 0)
            self.assertIn("quality_gates", manifest["quality"])
            self.assertIn("documentation", manifest["quality"]["content_domain_counts"])
            self.assertIn("[[Dashboards/Graph Views|Graph Views Dashboard]]", index)
            self.assertIn("## Trust Notes", index)
            self.assertIn("Verify the linked source note or file before making edits", index)
            self.assertTrue(
                any(
                    item["extractor"] == "python.ast"
                    and "function" in item["node_kinds"]
                    and "calls" in item["edge_kinds"]
                    for item in manifest["extractor_declarations"]
                )
            )
            non_contains_edges = [
                edge for edge in graph["edges"] if edge["kind"] != "contains"
            ]
            self.assertTrue(all(edge["evidence_id"] for edge in non_contains_edges))

            overview_stdout = io.StringIO()
            with contextlib.redirect_stdout(overview_stdout):
                overview_code = main(["overview", str(output), "--limit", "5"])
            overview = json.loads(overview_stdout.getvalue())
            self.assertEqual(overview_code, 0)
            self.assertIn("architecture", overview)
            self.assertIn("important_files", overview)

            doctor_stdout = io.StringIO()
            with contextlib.redirect_stdout(doctor_stdout):
                doctor_code = main(["doctor", str(output), "--json"])
            doctor = json.loads(doctor_stdout.getvalue())
            self.assertEqual(doctor_code, 0)
            self.assertEqual(doctor["status"], "passed")
            self.assertTrue(
                any(item["name"] == "obsidian_note_paths_unique_casefold" and item["passed"] for item in doctor["checks"])
            )
            self.assertTrue(
                any(item["name"] == "obsidian_note_paths_not_reserved" and item["passed"] for item in doctor["checks"])
            )

            with contextlib.redirect_stdout(io.StringIO()) as export_stdout:
                export_code = main(["export", str(output)])
            self.assertEqual(export_code, 0)
            self.assertIn("Obsidian export written", export_stdout.getvalue())

            with contextlib.redirect_stdout(io.StringIO()) as open_stdout:
                open_code = main(["open", str(output)])
            self.assertEqual(open_code, 0)
            self.assertEqual(open_stdout.getvalue().strip(), str((output / "obsidian").resolve()))

    def test_obsidian_entrypoints_dashboard_ranks_navigation_starts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            (target / "src" / "screens" / "Home").mkdir(parents=True)
            (target / "src" / "components").mkdir(parents=True)
            (target / "src" / "screens" / "Home" / "HomeScreen.tsx").write_text(
                "import { Button } from '../../components/Button'\n"
                "export function HomeScreen() { return <Button /> }\n",
                encoding="utf-8",
            )
            (target / "src" / "components" / "Button.tsx").write_text(
                "import { Clickable } from 'external-ui'\n"
                "export function Button() { return <Clickable /> }\n",
                encoding="utf-8",
            )

            scan(ScanOptions(target=target, output=output, export_obsidian=True))
            entrypoints = (output / "obsidian" / "Dashboards" / "Entrypoints.md").read_text(
                encoding="utf-8"
            )
            index = (output / "obsidian" / "index.md").read_text(encoding="utf-8")

            self.assertIn("[[Dashboards/Entrypoints|Entrypoints Dashboard]]", index)
            self.assertIn("## Agent Sequence", entrypoints)
            self.assertIn("## Important Files", entrypoints)
            self.assertIn("HomeScreen.tsx", entrypoints)

    def test_obsidian_architecture_dashboards_show_top_files_and_graph_views(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            (target / "src" / "screens").mkdir(parents=True)
            (target / "src" / "hooks").mkdir(parents=True)
            (target / "src" / "api").mkdir(parents=True)
            (target / "src" / "screens" / "CheckoutScreen.tsx").write_text(
                "import { useCheckout } from '../hooks/useCheckout'\n"
                "import { fetchCheckout } from '../api/checkoutApi'\n"
                "export function CheckoutScreen() { useCheckout(); return fetchCheckout() }\n",
                encoding="utf-8",
            )
            (target / "src" / "hooks" / "useCheckout.ts").write_text(
                "export function useCheckout() { return null }\n",
                encoding="utf-8",
            )
            (target / "src" / "api" / "checkoutApi.ts").write_text(
                "export function fetchCheckout() { return null }\n",
                encoding="utf-8",
            )

            scan(ScanOptions(target=target, output=output, export_obsidian=True))

            features = (output / "obsidian" / "Dashboards" / "Features.md").read_text(encoding="utf-8")
            layers = (output / "obsidian" / "Dashboards" / "Layers.md").read_text(encoding="utf-8")
            roles = (output / "obsidian" / "Dashboards" / "Roles.md").read_text(encoding="utf-8")
            domains = (output / "obsidian" / "Dashboards" / "Domains.md").read_text(encoding="utf-8")
            graph_views = (output / "obsidian" / "Dashboards" / "Graph Views.md").read_text(
                encoding="utf-8"
            )
            architecture = (output / "obsidian" / "Dashboards" / "Architecture.md").read_text(
                encoding="utf-8"
            )

            self.assertIn("## Top Hubs With Files", features)
            self.assertIn("CheckoutScreen.tsx", features)
            self.assertIn("belongs_to x1", features)
            self.assertIn("semantic edges", features)
            self.assertIn("## Top Hubs With Files", layers)
            self.assertIn("CheckoutScreen.tsx", layers)
            self.assertIn("## Trust Notes", roles)
            self.assertIn("## Trust Notes", domains)
            self.assertIn("Use these search presets in the Obsidian graph view search box.", graph_views)
            self.assertIn("`path:Architecture OR path:Files`", graph_views)
            self.assertIn("[[Dashboards/Domains|Domains Dashboard]]", architecture)
            self.assertIn("[[Dashboards/Roles|Roles Dashboard]]", architecture)
            self.assertIn("[[Dashboards/Graph Views|Graph Views Dashboard]]", architecture)

    def test_architecture_enrichment_links_roles_layers_and_import_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            (target / "src" / "screens" / "HomeScreen").mkdir(parents=True)
            (target / "src" / "components" / "Button").mkdir(parents=True)
            (target / "src" / "hooks").mkdir(parents=True)
            (target / "src" / "networking").mkdir(parents=True)
            (target / "src" / "screens" / "HomeScreen" / "HomeScreen.tsx").write_text(
                "import { useHome } from '../../hooks/useHome'\n"
                "import { Button } from '../../components/Button/Button'\n"
                "import { getHome } from '../../networking/homeApi'\n"
                "export function HomeScreen() { useHome(); return null }\n",
                encoding="utf-8",
            )
            (target / "src" / "components" / "Button" / "Button.tsx").write_text(
                "export function Button() { return null }\n",
                encoding="utf-8",
            )
            (target / "src" / "hooks" / "useHome.ts").write_text(
                "export function useHome() { return null }\n",
                encoding="utf-8",
            )
            (target / "src" / "networking" / "homeApi.ts").write_text(
                "export function getHome() { return null }\n",
                encoding="utf-8",
            )

            scan(ScanOptions(target=target, output=output))
            graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))
            node_ids = {node["id"] for node in graph["nodes"]}
            edges = {(edge["kind"], edge["from"], edge["to"]) for edge in graph["edges"]}

            self.assertIn("area:src", node_ids)
            self.assertIn("layer:screens", node_ids)
            self.assertIn("feature:HomeScreen", node_ids)
            self.assertIn("feature:Button", node_ids)
            self.assertNotIn("feature:components", node_ids)
            self.assertIn("role:hook", node_ids)
            self.assertIn("role:api", node_ids)
            self.assertIn(
                (
                    "uses_hook",
                    "file:src/screens/HomeScreen/HomeScreen.tsx",
                    "file:src/hooks/useHome.ts",
                ),
                edges,
            )
            self.assertIn(
                (
                    "calls_api",
                    "file:src/screens/HomeScreen/HomeScreen.tsx",
                    "file:src/networking/homeApi.ts",
                ),
                edges,
            )

    def test_scan_requires_replace_output_for_non_empty_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            (target / "README.md").write_text("# One\n", encoding="utf-8")

            scan(ScanOptions(target=target, output=output, export_obsidian=True))
            stale_note = output / "obsidian" / "stale.md"
            stale_note.write_text("old\n", encoding="utf-8")
            (target / "README.md").write_text("# Two\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "not empty"):
                scan(ScanOptions(target=target, output=output, export_obsidian=True))
            self.assertTrue(stale_note.exists())

    def test_scan_replace_output_deletes_and_recreates_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            output.mkdir()
            stale_note = output / "user-note.md"
            stale_note.write_text("old\n", encoding="utf-8")
            (target / "README.md").write_text("# Fresh\n", encoding="utf-8")

            scan(
                ScanOptions(
                    target=target,
                    output=output,
                    export_obsidian=True,
                    replace_output=True,
                )
            )

            self.assertFalse(stale_note.exists())
            self.assertTrue((output / ".ready").is_file())
            self.assertTrue((output / "manifest.json").is_file())

    def test_clean_requires_confirmation_and_managed_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            (target / "README.md").write_text("# Fresh\n", encoding="utf-8")
            scan(ScanOptions(target=target, output=output))

            with self.assertRaises(SystemExit):
                with contextlib.redirect_stderr(io.StringIO()):
                    main(["clean", str(output)])
            self.assertTrue(output.exists())

            with contextlib.redirect_stdout(io.StringIO()):
                clean_code = main(["clean", str(output), "--yes"])
            self.assertEqual(clean_code, 0)
            self.assertFalse(output.exists())

            unmanaged = root / "unmanaged"
            unmanaged.mkdir()
            with self.assertRaises(SystemExit):
                with contextlib.redirect_stderr(io.StringIO()):
                    main(["clean", str(unmanaged), "--yes"])

    def test_scan_refuses_non_empty_unmanaged_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            output.mkdir()
            (output / "user-note.md").write_text("keep me\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "not empty"):
                scan(ScanOptions(target=target, output=output))

    def test_status_detects_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            source = target / "README.md"
            source.write_text("# One\n", encoding="utf-8")

            scan(ScanOptions(target=target, output=output))
            self.assertEqual(graph_status(output)["freshness"], "current")

            time.sleep(0.01)
            source.write_text("# Two\n", encoding="utf-8")
            status = graph_status(output)
            self.assertEqual(status["freshness"], "stale")
            self.assertEqual(status["changed"], ["README.md"])

    def test_refresh_reuses_unchanged_extraction_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            (target / "src").mkdir(parents=True)
            (target / "src" / "helper.ts").write_text(
                "export function helper() { return 1 }\n",
                encoding="utf-8",
            )
            (target / "src" / "feature.ts").write_text(
                "import { helper } from './helper'\n"
                "export function feature() { return helper() }\n",
                encoding="utf-8",
            )

            scan(ScanOptions(target=target, output=output))
            time.sleep(0.01)
            (target / "src" / "helper.ts").write_text(
                "export function helper() { return 2 }\n",
                encoding="utf-8",
            )

            with contextlib.redirect_stdout(io.StringIO()):
                refresh_code = main(["refresh", str(output)])
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(refresh_code, 0)
            self.assertEqual(manifest["refresh"]["mode"], "incremental")
            self.assertEqual(manifest["refresh"]["changed"], ["src/helper.ts"])
            self.assertGreaterEqual(manifest["refresh"]["cache"]["reused"], 1)
            self.assertEqual(graph_status(output)["freshness"], "current")

    def test_refresh_rebuilds_safely_when_files_are_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            (target / "src").mkdir(parents=True)
            helper = target / "src" / "helper.ts"
            helper.write_text(
                "export function helper() { return 1 }\n",
                encoding="utf-8",
            )
            (target / "src" / "feature.ts").write_text(
                "import { helper } from './helper'\n"
                "export function feature() { return helper() }\n",
                encoding="utf-8",
            )

            scan(ScanOptions(target=target, output=output))
            helper.unlink()

            with contextlib.redirect_stdout(io.StringIO()):
                refresh_code = main(["refresh", str(output)])
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))
            node_ids = {node["id"] for node in graph["nodes"]}

            self.assertEqual(refresh_code, 0)
            self.assertEqual(manifest["refresh"]["mode"], "full")
            self.assertEqual(manifest["refresh"]["reason"], "deleted_files")
            self.assertNotIn("file:src/helper.ts", node_ids)
            self.assertEqual(graph_status(output)["freshness"], "current")

    def test_default_ignore_can_be_overridden_for_child_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "target"
            target.mkdir()
            (target / "node_modules" / "kept").mkdir(parents=True)
            (target / "node_modules" / "kept" / "index.js").write_text(
                "export function kept() {}\n",
                encoding="utf-8",
            )
            (target / "node_modules" / "other").mkdir()
            (target / "node_modules" / "other" / "index.js").write_text(
                "export function other() {}\n",
                encoding="utf-8",
            )
            policy = IgnorePolicy(target=target, include=["node_modules/kept"])
            self.assertFalse(policy.decide("node_modules", is_dir=True).ignored)
            self.assertFalse(policy.decide("node_modules/kept", is_dir=True).ignored)
            self.assertTrue(policy.decide("node_modules/other", is_dir=True).ignored)

    def test_config_file_resolves_import_aliases_and_feature_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            (target / "src" / "domains" / "Billing" / "screens").mkdir(parents=True)
            (target / "src" / "components" / "Button").mkdir(parents=True)
            (target / "codegraph.toml").write_text(
                "[imports.aliases]\n"
                '"@/*" = "src/*"\n\n'
                "[architecture]\n"
                'feature_markers = ["domains"]\n',
                encoding="utf-8",
            )
            (target / "src" / "domains" / "Billing" / "screens" / "InvoiceScreen.tsx").write_text(
                "import { Button } from '@/components/Button/Button'\n"
                "export function InvoiceScreen() { return <Button /> }\n",
                encoding="utf-8",
            )
            (target / "src" / "components" / "Button" / "Button.tsx").write_text(
                "export function Button() { return null }\n",
                encoding="utf-8",
            )

            scan(ScanOptions(target=target, output=output))
            graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            edges = {(edge["kind"], edge["from"], edge["to"]) for edge in graph["edges"]}
            node_ids = {node["id"] for node in graph["nodes"]}

            self.assertEqual(
                manifest["config"]["path"],
                str((target / "codegraph.toml").resolve()),
            )
            self.assertEqual(
                manifest["config"]["import_aliases"],
                [{"pattern": "@/*", "target": "src/*"}],
            )
            self.assertIn("feature:Billing", node_ids)
            self.assertIn(
                (
                    "imports",
                    "file:src/domains/Billing/screens/InvoiceScreen.tsx",
                    "file:src/components/Button/Button.tsx",
                ),
                edges,
            )
            self.assertIn(
                (
                    "renders",
                    "file:src/domains/Billing/screens/InvoiceScreen.tsx",
                    "file:src/components/Button/Button.tsx",
                ),
                edges,
            )

            time.sleep(0.01)
            (target / "codegraph.toml").write_text(
                "[imports.aliases]\n"
                '"@/*" = "src/*"\n'
                '"@components/*" = "src/components/*"\n',
                encoding="utf-8",
            )
            status = graph_status(output)
            self.assertEqual(status["freshness"], "stale")
            self.assertTrue(status["config_changed"])

    def test_package_json_names_resolve_internal_workspace_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            (target / "apps" / "web" / "src").mkdir(parents=True)
            (target / "packages" / "ui" / "src").mkdir(parents=True)
            (target / "packages" / "ui" / "package.json").write_text(
                '{"name": "@repo/ui", "source": "src/index.ts"}\n',
                encoding="utf-8",
            )
            (target / "packages" / "ui" / "src" / "index.ts").write_text(
                "export { Card } from './Card'\n",
                encoding="utf-8",
            )
            (target / "packages" / "ui" / "src" / "Card.tsx").write_text(
                "export function Card() { return null }\n",
                encoding="utf-8",
            )
            (target / "apps" / "web" / "src" / "Home.tsx").write_text(
                "import { Card } from '@repo/ui'\n"
                "export function Home() { return <Card /> }\n",
                encoding="utf-8",
            )

            scan(ScanOptions(target=target, output=output))
            graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            edges = {(edge["kind"], edge["from"], edge["to"]) for edge in graph["edges"]}

            self.assertIn(
                {"pattern": "@repo/ui", "target": "packages/ui/src/index.ts"},
                manifest["internal_package_aliases"],
            )
            self.assertIn(
                (
                    "imports",
                    "file:apps/web/src/Home.tsx",
                    "file:packages/ui/src/index.ts",
                ),
                edges,
            )
            self.assertIn(
                (
                    "exports",
                    "file:packages/ui/src/index.ts",
                    "file:packages/ui/src/Card.tsx",
                ),
                edges,
            )
            self.assertIn(
                (
                    "renders",
                    "file:apps/web/src/Home.tsx",
                    "file:packages/ui/src/index.ts",
                ),
                edges,
            )

    def test_cli_scan_requires_out_argument(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "target"
            target.mkdir()
            with self.assertRaises(SystemExit) as raised:
                with contextlib.redirect_stderr(io.StringIO()):
                    main(["scan", str(target)])
            self.assertNotEqual(raised.exception.code, 0)

    def test_query_returns_focused_subgraph_with_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            (target / "README.md").write_text("# Project\n\nSee [Design](design.md).\n", encoding="utf-8")
            (target / "design.md").write_text("# Design\n", encoding="utf-8")
            scan(ScanOptions(target=target, output=output))

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["query", str(output), "--node", "README.md", "--depth", "1"])
            result = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(result["nodes"])
            self.assertTrue(result["edges"])
            self.assertTrue(result["evidence"])

    def test_query_excludes_containment_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            (target / "src").mkdir(parents=True)
            (target / "src" / "helper.ts").write_text(
                "export function helper() { return 1 }\n",
                encoding="utf-8",
            )
            (target / "src" / "feature.ts").write_text(
                "import { helper } from './helper'\nexport function feature() { return helper() }\n",
                encoding="utf-8",
            )
            (target / "src" / "sibling.ts").write_text(
                "export function sibling() { return 2 }\n",
                encoding="utf-8",
            )
            scan(ScanOptions(target=target, output=output))

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "query",
                        str(output),
                        "--node",
                        "src/feature.ts",
                        "--depth",
                        "2",
                    ]
                )
            result = json.loads(stdout.getvalue())
            node_ids = {node["id"] for node in result["nodes"]}
            self.assertEqual(code, 0)
            self.assertIn("file:src/helper.ts", node_ids)
            self.assertNotIn("file:src/sibling.ts", node_ids)
            self.assertTrue(all(edge["kind"] != "contains" for edge in result["edges"]))

    def test_tsx_imports_resolve_case_and_render_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            (target / "src").mkdir(parents=True)
            (target / "src" / "FeatureFlag.tsx").write_text(
                "export function FeatureFlag() { return null }\\n",
                encoding="utf-8",
            )
            (target / "src" / "Screen.tsx").write_text(
                "import { FeatureFlag } from './featureFlag'\\n"
                "export function Screen() { return <FeatureFlag /> }\\n",
                encoding="utf-8",
            )
            manifest = scan(ScanOptions(target=target, output=output))
            graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["quality"]["missing_edge_endpoint_count"], 0)
            self.assertTrue(
                any(
                    edge["kind"] == "renders"
                    and edge["from"] == "file:src/Screen.tsx"
                    and edge["to"] == "file:src/FeatureFlag.tsx"
                    for edge in graph["edges"]
                )
            )

    def test_python_ast_extractor_records_methods_calls_and_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            (target / "pkg").mkdir(parents=True)
            (target / "pkg" / "base.py").write_text(
                "class Base:\n"
                "    pass\n",
                encoding="utf-8",
            )
            (target / "pkg" / "decorators.py").write_text(
                "def traced(function):\n"
                "    return function\n",
                encoding="utf-8",
            )
            (target / "pkg" / "app.py").write_text(
                "from .base import Base\n"
                "from .decorators import traced\n\n"
                "class Service(Base):\n"
                "    @traced\n"
                "    def helper(self):\n"
                "        return 1\n\n"
                "    def run(self):\n"
                "        return self.helper()\n",
                encoding="utf-8",
            )

            scan(ScanOptions(target=target, output=output))
            graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))
            edges = {(edge["kind"], edge["from"], edge["to"]) for edge in graph["edges"]}
            edge_records = {
                (edge["kind"], edge["from"], edge["to"]): edge
                for edge in graph["edges"]
            }
            evidence_by_id = {item["id"]: item for item in graph["evidence"]}
            evidence_extractors = {item["extractor"] for item in graph["evidence"]}
            import_edges = [
                edge
                for edge in graph["edges"]
                if edge["kind"] == "imports" and edge["from"] == "file:pkg/app.py"
            ]

            self.assertIn("python.ast", evidence_extractors)
            self.assertIn(
                (
                    "contains",
                    "symbol:pkg/app.py#Service:4",
                    "symbol:pkg/app.py#Service.helper:6",
                ),
                edges,
            )
            self.assertIn(
                (
                    "calls",
                    "symbol:pkg/app.py#Service.run:9",
                    "symbol:pkg/app.py#Service.helper:6",
                ),
                edges,
            )
            self.assertIn(
                (
                    "depends_on",
                    "symbol:pkg/app.py#Service:4",
                    "file:pkg/base.py",
                ),
                edges,
            )
            self.assertIn(
                (
                    "depends_on",
                    "symbol:pkg/app.py#Service.helper:6",
                    "file:pkg/decorators.py",
                ),
                edges,
            )
            self.assertTrue(
                any(
                    edge["attributes"].get("module") == ".base"
                    and edge["attributes"].get("relative_level") == 1
                    for edge in import_edges
                )
            )
            self.assertTrue(all(edge["confidence"] == "DERIVED" for edge in import_edges))
            base_dep = edge_records[("depends_on", "symbol:pkg/app.py#Service:4", "file:pkg/base.py")]
            decorator_dep = edge_records[
                ("depends_on", "symbol:pkg/app.py#Service.helper:6", "file:pkg/decorators.py")
            ]
            self.assertEqual(base_dep["confidence"], "DERIVED")
            self.assertEqual(decorator_dep["confidence"], "DERIVED")
            self.assertEqual(evidence_by_id[base_dep["evidence_id"]]["confidence"], "DERIVED")
            self.assertEqual(evidence_by_id[decorator_dep["evidence_id"]]["confidence"], "DERIVED")

    def test_tsx_external_named_imports_are_queryable_and_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            (target / "src").mkdir(parents=True)
            (target / "src" / "Screen.tsx").write_text(
                "import { Clickable, Surface } from 'external-ui'\\n"
                "export function Screen() { return <Surface><Clickable /></Surface> }\\n",
                encoding="utf-8",
            )
            scan(ScanOptions(target=target, output=output))
            graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))
            node_ids = {node["id"] for node in graph["nodes"]}
            self.assertIn("imported-symbol:external-ui#Surface", node_ids)
            self.assertIn("imported-symbol:external-ui#Clickable", node_ids)
            self.assertTrue(
                any(
                    edge["kind"] == "renders"
                    and edge["from"] == "file:src/Screen.tsx"
                    and edge["to"] == "imported-symbol:external-ui#Surface"
                    for edge in graph["edges"]
                )
            )
            self.assertTrue(
                any(
                    edge["kind"] == "renders"
                    and edge["from"] == "file:src/Screen.tsx"
                    and edge["to"] == "imported-symbol:external-ui#Clickable"
                    for edge in graph["edges"]
                )
            )

    def test_js_ts_module_forms_create_navigation_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            (target / "src" / "components").mkdir(parents=True)
            (target / "src" / "components" / "Button.tsx").write_text(
                "export function Button() { return null }\n",
                encoding="utf-8",
            )
            (target / "src" / "components" / "types.ts").write_text(
                "export type ButtonProps = { label: string }\n",
                encoding="utf-8",
            )
            (target / "src" / "components" / "tokens.ts").write_text(
                "export const primary = 'blue'\n",
                encoding="utf-8",
            )
            (target / "src" / "components" / "index.ts").write_text(
                "export { Button } from './Button'\n"
                "export type { ButtonProps } from './types'\n"
                "export * from './tokens'\n",
                encoding="utf-8",
            )
            (target / "src" / "Screen.tsx").write_text(
                "import React, {\n"
                "  type ReactNode,\n"
                "  useMemo as useReactMemo,\n"
                "} from 'react'\n"
                "import type { ButtonProps } from './components/types'\n"
                "import { Button } from './components'\n"
                "const { Surface, Clickable: PrimaryClickable } = require('external-ui')\n"
                "export default function Screen() { return <><Button /><Surface /></> }\n",
                encoding="utf-8",
            )

            scan(ScanOptions(target=target, output=output))
            graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))
            edges = {(edge["kind"], edge["from"], edge["to"]) for edge in graph["edges"]}
            node_ids = {node["id"] for node in graph["nodes"]}
            methods = {item["method"] for item in graph["evidence"]}

            self.assertIn(
                (
                    "exports",
                    "file:src/components/index.ts",
                    "file:src/components/Button.tsx",
                ),
                edges,
            )
            self.assertIn(
                (
                    "exports",
                    "file:src/components/index.ts",
                    "file:src/components/types.ts",
                ),
                edges,
            )
            self.assertIn(
                (
                    "imports",
                    "file:src/Screen.tsx",
                    "file:src/components/index.ts",
                ),
                edges,
            )
            self.assertIn("imported-symbol:external-ui#Surface", node_ids)
            self.assertIn("imported-symbol:external-ui#PrimaryClickable", node_ids)
            self.assertIn("lexical-re-export", methods)
            self.assertIn("lexical-type-import", methods)
            self.assertIn("lexical-require", methods)
            self.assertTrue(
                any(
                    edge["kind"] == "renders"
                    and edge["from"] == "file:src/Screen.tsx"
                    and edge["to"] == "imported-symbol:external-ui#Surface"
                    for edge in graph["edges"]
                )
            )
            self.assertTrue(
                any(
                    edge["kind"] == "exports"
                    and edge["from"] == "file:src/Screen.tsx"
                    and edge["to"] == "symbol:src/Screen.tsx#Screen:8"
                    for edge in graph["edges"]
                )
            )

    def test_js_ts_lexical_extractor_covers_dynamic_imports_and_commonjs_exports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            (target / "src").mkdir(parents=True)
            (target / "src" / "feature.ts").write_text(
                "export default class Feature {}\n"
                "export async function loadFeature() { return Feature }\n",
                encoding="utf-8",
            )
            (target / "src" / "consumer.ts").write_text(
                "const shared = 1\n"
                "const lazyFeature = import('./feature')\n"
                "const featurePath = require.resolve('./feature')\n"
                "module.exports = require('./feature')\n"
                "exports.shared = shared\n",
                encoding="utf-8",
            )

            scan(ScanOptions(target=target, output=output))
            graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))
            edges = {(edge["kind"], edge["from"], edge["to"]) for edge in graph["edges"]}
            methods = {item["method"] for item in graph["evidence"]}

            self.assertIn(("imports", "file:src/consumer.ts", "file:src/feature.ts"), edges)
            self.assertIn(("exports", "file:src/consumer.ts", "file:src/feature.ts"), edges)
            self.assertIn(("exports", "file:src/consumer.ts", "symbol:src/consumer.ts#shared:1"), edges)
            self.assertIn("lexical-commonjs-export", methods)
            self.assertIn("lexical-dynamic-import", methods)
            self.assertIn("lexical-require-resolve", methods)
            self.assertIn("lexical-commonjs-export-require", methods)

    def test_lockfiles_are_classified_as_generated_lockfiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            (target / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
            (target / "poetry.lock").write_text("[[package]]\nname = \"demo\"\n", encoding="utf-8")

            manifest = scan(ScanOptions(target=target, output=output))
            graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))
            lockfile_nodes = {
                node["source_path"]: node for node in graph["nodes"] if node["kind"] == "lockfile"
            }

            self.assertEqual(classify_content_domain(Path("package-lock.json")), "generated")
            self.assertEqual(classify_content_domain(Path("poetry.lock")), "generated")
            self.assertEqual(manifest["quality"]["content_domain_counts"]["generated"], 2)
            self.assertIn("package-lock.json", lockfile_nodes)
            self.assertIn("poetry.lock", lockfile_nodes)
            self.assertFalse(
                any(
                    node["kind"] == "config_file"
                    and node.get("source_path") in {"package-lock.json", "poetry.lock"}
                    for node in graph["nodes"]
                )
            )

    def test_import_resolution_context_caches_repeated_relative_lookups(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            (target / "src").mkdir(parents=True)
            feature = target / "src" / "feature.ts"
            consumer = target / "src" / "consumer.ts"
            feature.write_text("export const feature = 1\n", encoding="utf-8")
            consumer.write_text("import './feature'\n", encoding="utf-8")

            context = ExtractionContext()
            with mock.patch(
                "codegraph.extractors.resolve_candidate_base",
                wraps=extractor_module.resolve_candidate_base,
            ) as resolve_candidate_base_mock:
                first = resolve_import(target, consumer, "./feature", (), context=context)
                second = resolve_import(target, consumer, "./feature", (), context=context)

            expected_feature = feature.resolve()
            self.assertEqual(first, expected_feature)
            self.assertEqual(second, expected_feature)
            self.assertEqual(resolve_candidate_base_mock.call_count, 1)

    def test_config_and_log_files_are_classified_domains(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            (target / "app.json").write_text('{"expo": {"name": "Demo"}}\n', encoding="utf-8")
            (target / "runtime.log").write_text("INFO boot\nERROR down\n", encoding="utf-8")
            manifest = scan(ScanOptions(target=target, output=output))
            graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["quality"]["unsupported_file_count"], 0)
            self.assertEqual(manifest["quality"]["content_domain_counts"]["configuration"], 1)
            self.assertEqual(manifest["quality"]["content_domain_counts"]["observability"], 1)
            self.assertTrue(any(edge["kind"] == "configures" for edge in graph["edges"]))
            self.assertTrue(any(edge["kind"] == "emits_log" for edge in graph["edges"]))

    def test_obsidian_export_keeps_config_and_log_notes_unique(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            (target / "app.json").write_text(
                '{\n  "expo": {\n    "name": "Demo",\n    "slug": "demo"\n  }\n}\n',
                encoding="utf-8",
            )
            (target / "runtime.log").write_text(
                "INFO boot\nERROR down\n",
                encoding="utf-8",
            )

            scan(ScanOptions(target=target, output=output, export_obsidian=True))

            self.assertTrue((output / "obsidian" / "Config" / "app.json__expo_L2.md").is_file())
            self.assertTrue((output / "obsidian" / "Config" / "app.json__name_L3.md").is_file())
            self.assertTrue((output / "obsidian" / "Config" / "app.json__slug_L4.md").is_file())
            self.assertTrue(
                (output / "obsidian" / "Observability" / "runtime.log__INFO_L1.md").is_file()
            )
            self.assertTrue(
                (output / "obsidian" / "Observability" / "runtime.log__ERROR_L2.md").is_file()
            )

    def test_obsidian_export_keeps_casefold_colliding_notes_unique(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            (target / "settings.json").write_text(
                '{\n  "Name": "Upper",\n  "name": "Lower"\n}\n',
                encoding="utf-8",
            )

            scan(ScanOptions(target=target, output=output, export_obsidian=True))

            config_dir = output / "obsidian" / "Config"
            config_notes = [path.name for path in config_dir.iterdir() if path.name.startswith("settings.json__")]

            self.assertGreaterEqual(len(config_notes), 2)
            self.assertEqual(len(config_notes), len({name.casefold() for name in config_notes}))

            doctor_stdout = io.StringIO()
            with contextlib.redirect_stdout(doctor_stdout):
                doctor_code = main(["doctor", str(output), "--json"])
            doctor = json.loads(doctor_stdout.getvalue())

            self.assertEqual(doctor_code, 0)
            self.assertEqual(doctor["status"], "passed")
            self.assertTrue(
                any(item["name"] == "obsidian_note_paths_unique_casefold" and item["passed"] for item in doctor["checks"])
            )

    def test_unique_obsidian_note_paths_avoid_reserved_and_casefold_collisions(self) -> None:
        nodes = [
            {"id": "node:a", "kind": "file", "label": "a", "source_path": "a", "range": None},
            {"id": "node:b", "kind": "file", "label": "b", "source_path": "b", "range": None},
            {"id": "node:c", "kind": "file", "label": "c", "source_path": "c", "range": None},
        ]

        with mock.patch(
            "codegraph.scanner.obsidian_note_path",
            side_effect=["index", "Index", "Dashboards/Features"],
        ):
            note_paths = unique_obsidian_note_paths(nodes)

        normalized = {value.casefold() for value in note_paths.values()}
        self.assertEqual(len(normalized), len(note_paths))
        self.assertNotIn("index", normalized)
        self.assertNotIn("dashboards/features", normalized)

    def test_obsidian_export_exposes_research_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            (target / "notes.md").write_text(
                "# Notes\n\n"
                "The `stable graph` concept supports #research-synthesis work.\n",
                encoding="utf-8",
            )

            scan(ScanOptions(target=target, output=output, export_obsidian=True))
            index = (output / "obsidian" / "index.md").read_text(encoding="utf-8")
            research = (output / "obsidian" / "Dashboards" / "Research.md").read_text(
                encoding="utf-8"
            )

            self.assertIn("[[Dashboards/Research|Research Dashboard]]", index)
            self.assertTrue((output / "obsidian" / "Indexes" / "Concepts.md").is_file())
            self.assertTrue((output / "obsidian" / "Indexes" / "Claims.md").is_file())
            self.assertIn("stable graph", research)
            self.assertIn("research synthesis", research)

    def test_assets_are_supported_as_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            (target / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            manifest = scan(ScanOptions(target=target, output=output, export_obsidian=True))
            graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["quality"]["unsupported_file_count"], 0)
            self.assertEqual(manifest["quality"]["status"], "passed")
            self.assertEqual(manifest["quality"]["content_domain_counts"]["asset"], 1)
            self.assertEqual(
                manifest["quality"]["observed_kinds"]["by_extractor"]["asset.metadata"]["node_kinds"],
                ["asset_file"],
            )
            self.assertEqual(
                manifest["quality"]["observed_kinds"]["by_content_domain"]["asset"]["edge_kinds"],
                ["stores_asset"],
            )
            self.assertTrue(any(node["kind"] == "asset_file" for node in graph["nodes"]))
            self.assertTrue(any(edge["kind"] == "stores_asset" for edge in graph["edges"]))
            self.assertTrue((output / "obsidian" / "Indexes" / "Assets.md").is_file())

    def test_unknown_files_make_quality_partial(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            (target / "mystery.blob").write_text("unknown\n", encoding="utf-8")
            manifest = scan(ScanOptions(target=target, output=output))

            self.assertEqual(manifest["quality"]["status"], "partial")
            self.assertEqual(manifest["quality"]["unsupported_file_count"], 1)
            self.assertEqual(manifest["quality"]["unsupported_by_domain"]["unknown"], 1)

    def test_benchmark_fixtures_generate_trusted_overviews(self) -> None:
        fixtures = ["alias_app", "research_notes", "ops_collection"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for fixture in fixtures:
                target = FIXTURES_DIR / fixture
                output = root / fixture
                with self.subTest(fixture=fixture):
                    scan(ScanOptions(target=target, output=output, export_obsidian=True))

                    doctor_stdout = io.StringIO()
                    with contextlib.redirect_stdout(doctor_stdout):
                        doctor_code = main(["doctor", str(output), "--json"])
                    doctor = json.loads(doctor_stdout.getvalue())
                    self.assertEqual(doctor_code, 0)
                    self.assertEqual(doctor["status"], "passed")
                    self.assertEqual(doctor["quality"]["status"], "passed")

                    overview_stdout = io.StringIO()
                    with contextlib.redirect_stdout(overview_stdout):
                        overview_code = main(["overview", str(output), "--limit", "4"])
                    overview = json.loads(overview_stdout.getvalue())
                    self.assertEqual(overview_code, 0)
                    self.assertFalse(overview["warnings"])
                    self.assertTrue(overview["architecture"]["domains"])

            alias_output = root / "alias_app"
            query_stdout = io.StringIO()
            with contextlib.redirect_stdout(query_stdout):
                query_code = main(
                    [
                        "query",
                        str(alias_output),
                        "--node",
                        "feature:Billing",
                        "--direction",
                        "in",
                        "--depth",
                        "1",
                    ]
                )
            query = json.loads(query_stdout.getvalue())
            self.assertEqual(query_code, 0)
            self.assertTrue(
                any(node.get("source_path") == "src/domains/Billing/screens/InvoiceScreen.tsx" for node in query["nodes"])
            )

    def test_markdown_extracts_claim_concepts_and_simple_citations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            output = root / "graph"
            target.mkdir()
            (target / "notes.md").write_text(
                "# Notes\n\n"
                "The `stable graph` concept supports [source evidence][src] and #research-synthesis work.[^1]\n"
                "[src]: https://example.com/source\n"
                "[^1]: Footnote support\n"
                "The method depends on `source evidence` for trust.\n",
                encoding="utf-8",
            )

            scan(ScanOptions(target=target, output=output))
            graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))
            node_kinds = {node["kind"] for node in graph["nodes"]}
            node_ids = {node["id"] for node in graph["nodes"]}
            edge_kinds = {edge["kind"] for edge in graph["edges"]}
            inferred_evidence = [
                item
                for item in graph["evidence"]
                if item["extractor"] == "markdown" and item["confidence"] == "INFERRED"
            ]

            self.assertIn("concept", node_kinds)
            self.assertIn("claim", node_kinds)
            self.assertIn("reference", node_kinds)
            self.assertIn("mentions", edge_kinds)
            self.assertIn("supports", edge_kinds)
            self.assertIn("depends_on", edge_kinds)
            self.assertIn("cites", edge_kinds)
            self.assertNotIn("concept:concept", node_ids)
            self.assertIn("concept:stable-graph", node_ids)
            self.assertIn("reference:https://example.com/source", node_ids)
            self.assertTrue(inferred_evidence)


if __name__ == "__main__":
    unittest.main()
