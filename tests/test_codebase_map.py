"""
@author: Kurok1 <im.kurokyhanc@gmail.com>
@since: 0.1.0
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "codebase-map"
    / "scripts"
    / "codebase_map.py"
)
SPEC = importlib.util.spec_from_file_location("codebase_map_script", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load codebase-map script: {SCRIPT_PATH}")
CODEBASE_MAP = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CODEBASE_MAP
with mock.patch.object(sys, "path", [str(SCRIPT_PATH.parent), *sys.path]):
    SPEC.loader.exec_module(CODEBASE_MAP)
CODEBASE_HOOK = sys.modules["codebase_hook"]


class CodebaseMapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name).resolve()
        self._init_repository(self.root)
        (self.root / "README.md").write_text("workspace\n", encoding="utf-8")
        self.frontend = self._create_nested_repository("frontend", "src/app.ts")
        self.backend = self._create_nested_repository("backend", "src/api.py")
        (self.root / ".gitmodules").write_text(
            """[submodule "frontend"]
\tpath = frontend
\turl = ../frontend.git
[submodule "backend"]
\tpath = backend
\turl = ../backend.git
""",
            encoding="utf-8",
        )
        for module_root in (self.frontend, self.backend):
            index = module_root / "docs" / ".codebase-map" / "CODEMAP.md"
            index.parent.mkdir(parents=True)
            index.write_text(f"# {module_root.name}\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def _init_repository(path: Path) -> None:
        subprocess.run(
            ["git", "init", "-q", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )

    def _create_nested_repository(self, name: str, source_path: str) -> Path:
        module_root = self.root / name
        source = module_root / source_path
        source.parent.mkdir(parents=True)
        source.write_text(f"// {name}\n", encoding="utf-8")
        self._init_repository(module_root)
        return module_root

    def _run_hook(self, event: str, payload: dict[str, object]) -> tuple[int, str]:
        output = io.StringIO()
        with (
            mock.patch.object(
                CODEBASE_HOOK.sys,
                "stdin",
                io.StringIO(json.dumps(payload)),
            ),
            redirect_stdout(output),
        ):
            result = CODEBASE_HOOK.handle_hook(event)
        return result, output.getvalue()

    def test_session_start_enables_continuous_mode_and_lists_submodule_maps(self) -> None:
        context = CODEBASE_HOOK.build_start_context(self.root, "startup")

        self.assertIn(
            "Use $codebase-map in continuous maintenance mode",
            context,
        )
        self.assertIn('source="startup"', context)
        self.assertIn("current conversation", context)
        self.assertIn("natural knowledge checkpoints", context)
        self.assertIn("frontend/docs/.codebase-map/CODEMAP.md", context)
        self.assertIn("backend/docs/.codebase-map/CODEMAP.md", context)

    def test_session_start_injects_existing_root_map(self) -> None:
        index = self.root / "docs" / ".codebase-map" / "CODEMAP.md"
        index.parent.mkdir(parents=True)
        index.write_text("# Root map\n", encoding="utf-8")

        context = CODEBASE_HOOK.build_start_context(self.root, "resume")

        self.assertIn("<CODEMAP>\n# Root map\n\n</CODEMAP>", context)
        self.assertIn('source="resume"', context)

    def test_session_start_without_a_map_still_activates_maintenance(self) -> None:
        with tempfile.TemporaryDirectory() as empty_directory:
            context = CODEBASE_HOOK.build_start_context(
                Path(empty_directory).resolve(),
                "clear",
            )

        self.assertIn(
            "Use $codebase-map in continuous maintenance mode",
            context,
        )
        self.assertIn("No root CODEMAP.md exists", context)
        self.assertIn("Do not scan the repository merely to populate the map", context)

    def test_compact_source_requests_an_immediate_context_checkpoint(self) -> None:
        context = CODEBASE_HOOK.build_start_context(self.root, "compact")

        self.assertIn('source="compact"', context)
        self.assertIn("Compaction just completed", context)
        self.assertIn("Before continuing the active task", context)
        self.assertIn("retained conversation context", context)
        self.assertIn("current conversation and focused source as evidence inputs", context)

    def test_session_start_hook_emits_additional_context_for_compact(self) -> None:
        result, output = self._run_hook(
            "session-start",
            {
                "hook_event_name": "SessionStart",
                "cwd": str(self.root),
                "session_id": "session-1",
                "source": "compact",
            },
        )

        response = json.loads(output)
        self.assertEqual(result, 0)
        self.assertEqual(
            response["hookSpecificOutput"]["hookEventName"],
            "SessionStart",
        )
        self.assertIn(
            'source="compact"',
            response["hookSpecificOutput"]["additionalContext"],
        )

    def test_unknown_session_start_source_is_rejected(self) -> None:
        with self.assertRaises(CODEBASE_HOOK.MapError):
            CODEBASE_HOOK.build_start_context(self.root, "unknown")

    def test_codex_sources_keep_the_existing_output_contract(self) -> None:
        for source in ("startup", "resume", "clear", "compact", "fork"):
            with self.subTest(source=source):
                result, output = self._run_hook(
                    "session-start",
                    {
                        "hook_event_name": "SessionStart",
                        "cwd": str(self.root),
                        "source": source,
                    },
                )
                self.assertEqual(result, 0)
                self.assertEqual(
                    json.loads(output),
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "SessionStart",
                            "additionalContext": CODEBASE_HOOK.build_start_context(
                                self.root, source
                            ),
                        }
                    },
                )

    def test_athena_events_emit_developer_prompts_from_the_workspace(self) -> None:
        index = self.root / "docs" / ".codebase-map" / "CODEMAP.md"
        index.parent.mkdir(parents=True)
        index.write_text("# 项目地图\n", encoding="utf-8")
        for event_name, source in (
            ("SessionStarted", "startup"),
            ("SessionResumed", "resume"),
            ("PostCompact", "compact"),
        ):
            with self.subTest(event_name=event_name):
                result, output = self._run_hook(
                    "session-start",
                    {
                        "hookName": event_name,
                        "workspace": str(self.root),
                        "sessionId": "athena-session",
                        "model": {
                            "provider": "openai",
                            "modelId": "test-model",
                            "thinkingLevel": "high",
                        },
                        "timestamp": "2026-10-20T00:00:00.000Z",
                        "cwd": str(self.frontend),
                        "source": "ignored-for-athena",
                    },
                )
                self.assertEqual(result, 0)
                self.assertEqual(
                    json.loads(output),
                    {
                        "additionalPrompt": CODEBASE_HOOK.build_start_context(
                            self.root, source
                        ),
                        "role": "developer",
                    },
                )
                self.assertIn("# 项目地图", output)

    def test_athena_preserves_an_explicit_non_git_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            (parent / "package.json").write_text("{}", encoding="utf-8")
            workspace = parent / "nested workspace"
            workspace.mkdir()
            for root, text in (
                (parent, "# Parent map must not be injected\n"),
                (workspace, "# Explicit workspace map\n"),
            ):
                index = root / "docs" / ".codebase-map" / "CODEMAP.md"
                index.parent.mkdir(parents=True)
                index.write_text(text, encoding="utf-8")

            _, output = self._run_hook(
                "session-start",
                {"hookName": "SessionStarted", "workspace": str(workspace)},
            )

        context = json.loads(output)["additionalPrompt"]
        self.assertIn("# Explicit workspace map", context)
        self.assertNotIn("# Parent map must not be injected", context)

    def test_athena_resolves_the_owning_git_worktree(self) -> None:
        _, output = self._run_hook(
            "session-start",
            {"hookName": "SessionResumed", "workspace": str(self.frontend / "src")},
        )

        context = json.loads(output)["additionalPrompt"]
        self.assertIn("<CODEMAP>\n# frontend\n", context)
        self.assertNotIn("<SUBMODULE_CODEMAPS>", context)

    def test_antigravity_matches_registered_worktree_in_a_multi_root_session(self) -> None:
        nested = self.root / "services" / "api"
        nested.mkdir(parents=True)
        payload = {"workspacePaths": [str(self.backend), str(nested)]}
        steps = CODEBASE_HOOK.antigravity_hook_response("session-start", payload, self.root)["injectSteps"]
        context = steps[0]["systemMessage"]["systemMessage"]
        self.assertIn("No root CODEMAP.md exists", context)
        self.assertIn("frontend/docs/.codebase-map/CODEMAP.md", context)
        self.assertNotIn("<CODEMAP>", context)

        for paths in ([], [str(self.backend / "src")], [str(self.root / "missing")]):
            with self.subTest(paths=paths):
                self.assertEqual(
                    CODEBASE_HOOK.antigravity_hook_response(
                        "session-start", {"workspacePaths": paths}, self.root
                    ),
                    {"injectSteps": []},
                )

    def test_antigravity_reads_the_linked_worktrees_own_map(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory).resolve() / "linked"
            created = subprocess.run(
                ["git", "-C", str(self.root), "worktree", "add", "-q", str(worktree)],
                capture_output=True, text=True,
            )
            if created.returncode and "not a valid object name" in created.stderr:
                self.skipTest("This Git version requires a commit to create a linked worktree")
            created.check_returncode()
            index = worktree / "docs" / ".codebase-map" / "CODEMAP.md"
            index.parent.mkdir(parents=True)
            index.write_text("# Linked map", encoding="utf-8")
            payload = {"workspacePaths": [str(self.root), str(index.parent)]}
            response = CODEBASE_HOOK.antigravity_hook_response("session-start", payload, worktree)
            self.assertIn("# Linked map", response["injectSteps"][0]["systemMessage"]["systemMessage"])

    def test_pre_invocation_is_scoped_and_never_builds_map_context(self) -> None:
        with mock.patch.object(CODEBASE_HOOK, "build_start_context", side_effect=AssertionError):
            response = CODEBASE_HOOK.antigravity_hook_response(
                "pre-invocation", {"workspacePaths": [str(self.backend / "src")]}, self.backend
            )
        message = response["injectSteps"][0]["systemMessage"]["systemMessage"]
        self.assertIn(str(self.backend), message)
        self.assertIn("CODEBASE_MAP_CHECKPOINT", message)
        self.assertEqual(len(message.splitlines()), 1)
        self.assertNotIn("<CODEMAP>", message)

    def test_antigravity_rejects_invalid_and_unbound_payloads(self) -> None:
        for payload, root in (
            ({"workspacePaths": [str(self.root)]}, None),
            ({"workspacePaths": [str(self.root)]}, Path("relative")),
            ({}, self.root),
            ({"workspacePaths": str(self.root)}, self.root),
            ({"workspacePaths": [1]}, self.root),
            ({"workspacePaths": ["relative/path"]}, self.root),
            ({"workspacePaths": [str(self.root)], "hook_event_name": "SessionStart"}, self.root),
        ):
            with self.subTest(payload=payload, root=root), self.assertRaises(CODEBASE_HOOK.MapError):
                CODEBASE_HOOK.antigravity_hook_response("session-start", payload, root)

    def test_invalid_hook_inputs_fail_without_context_or_tracebacks(self) -> None:
        payloads = [
            "not-json",
            "[]",
            "null",
            json.dumps({"hook_event_name": "Stop"}),
            *[
                json.dumps({"hook_event_name": "SessionStart", "source": source})
                for source in ("unknown", [], {}, False)
            ],
            json.dumps({"hook_event_name": "SessionStart", "cwd": []}),
            json.dumps({"workspace": str(self.root)}),
            json.dumps({"hookName": ["SessionStarted"], "workspace": str(self.root)}),
            json.dumps({"hookName": "ThreadFinished", "workspace": str(self.root)}),
            json.dumps(
                {
                    "hookName": "SessionStarted",
                    "hook_event_name": "SessionStart",
                    "workspace": str(self.root),
                }
            ),
            *[
                json.dumps({"hookName": "SessionStarted", "workspace": workspace})
                for workspace in (
                    None, "", [], 42, "relative/path", "\x00",
                    str(self.root / "missing"), str(self.root / "README.md"),
                )
            ],
        ]
        for script in (CODEBASE_HOOK, CODEBASE_MAP):
            for payload in payloads:
                with self.subTest(script=script.__name__, payload=payload):
                    output = io.StringIO()
                    errors = io.StringIO()
                    with (
                        mock.patch.object(sys, "stdin", io.StringIO(payload)),
                        redirect_stdout(output),
                        redirect_stderr(errors),
                    ):
                        result = script.main(["hook", "session-start"])
                    self.assertEqual(result, 2)
                    self.assertEqual(output.getvalue(), "")
                    self.assertTrue(errors.getvalue().strip())
                    self.assertNotIn("Traceback", errors.getvalue())

    def test_legacy_hook_cli_delegates_to_the_standalone_runner(self) -> None:
        payloads = [
            {
                "hook_event_name": "SessionStart",
                "cwd": str(self.root),
                "source": "compact",
            },
            *[
                {"hookName": event_name, "workspace": str(self.root)}
                for event_name in ("SessionStarted", "SessionResumed", "PostCompact")
            ],
        ]
        standalone = self.root / "standalone hook" / "codebase-hook.py"
        standalone.parent.mkdir()
        shutil.copyfile(SCRIPT_PATH.with_name("codebase_hook.py"), standalone)
        for payload in payloads:
            responses = []
            for script in (SCRIPT_PATH, SCRIPT_PATH.with_name("codebase_hook.py"), standalone):
                with self.subTest(script=script, payload=payload):
                    completed = subprocess.run(
                        [sys.executable, "-B", str(script), "hook", "session-start"],
                        check=False,
                        input=json.dumps(payload),
                        capture_output=True,
                        text=True,
                        cwd=self.backend,
                        timeout=5,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    responses.append(json.loads(completed.stdout))

            self.assertEqual(responses[0], responses[1])
            self.assertEqual(responses[0], responses[2])

    def test_runner_has_no_runtime_evidence_pipeline(self) -> None:
        self.assertFalse(hasattr(CODEBASE_MAP, "ensure_pending"))
        self.assertFalse(hasattr(CODEBASE_MAP, "record_post_tool_use"))
        self.assertFalse(hasattr(CODEBASE_MAP, "acknowledge_pending"))

        with (
            self.assertRaises(SystemExit),
            redirect_stderr(io.StringIO()),
        ):
            CODEBASE_MAP.build_parser().parse_args(["hook", "stop"])

    def test_validate_accepts_a_reachable_verified_map(self) -> None:
        source = self.root / "src" / "app.py"
        source.parent.mkdir()
        source.write_text("def start():\n    return True\n", encoding="utf-8")
        target = self.root / "docs" / ".codebase-map"
        detail = target / "architecture" / "runtime.md"
        detail.parent.mkdir(parents=True)
        (target / "CODEMAP.md").write_text(
            "# Map\n\n[Runtime](architecture/runtime.md)\n",
            encoding="utf-8",
        )
        detail.write_text(
            "# Runtime\n\n[src/app.py](../../../src/app.py) → `start()`\n",
            encoding="utf-8",
        )

        result = CODEBASE_MAP.validate_map(self.root)

        self.assertTrue(result["valid"])
        self.assertEqual(result["documents"], 2)
        self.assertEqual(result["checked_coordinates"], 1)

    def test_validate_rejects_an_unreachable_map_document(self) -> None:
        target = self.root / "docs" / ".codebase-map"
        target.mkdir(parents=True)
        (target / "CODEMAP.md").write_text("# Map\n", encoding="utf-8")
        (target / "orphan.md").write_text("# Orphan\n", encoding="utf-8")

        result = CODEBASE_MAP.validate_map(self.root)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("unreachable" in error for error in result["errors"]),
            result["errors"],
        )

    def test_validate_allows_supporting_files_without_graph_reachability(self) -> None:
        target = self.root / "docs" / ".codebase-map"
        assets = target / "assets"
        assets.mkdir(parents=True)
        (target / "CODEMAP.md").write_text(
            "# Map\n\n![Runtime diagram](assets/runtime.svg)\n",
            encoding="utf-8",
        )
        (assets / "runtime.svg").write_text("<svg></svg>\n", encoding="utf-8")
        (assets / "runtime.drawio").write_text("<mxfile/>\n", encoding="utf-8")

        result = CODEBASE_MAP.validate_map(self.root)

        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["documents"], 1)
        self.assertEqual(result["supporting_files"], 2)
        self.assertEqual(result["checked_links"], 1)

    def test_validate_rejects_a_missing_linked_supporting_file(self) -> None:
        target = self.root / "docs" / ".codebase-map"
        target.mkdir(parents=True)
        (target / "CODEMAP.md").write_text(
            "# Map\n\n![Runtime diagram](assets/missing.svg)\n",
            encoding="utf-8",
        )

        result = CODEBASE_MAP.validate_map(self.root)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("missing link target" in error for error in result["errors"]),
            result["errors"],
        )

    def test_status_reports_context_checkpoint_mode(self) -> None:
        target = self.root / "docs" / ".codebase-map"
        assets = target / "assets"
        assets.mkdir(parents=True)
        (target / "CODEMAP.md").write_text("# Map\n", encoding="utf-8")
        (assets / "runtime.svg").write_text("<svg></svg>\n", encoding="utf-8")

        result = CODEBASE_MAP.status(argparse.Namespace(project_root=str(self.root)))

        self.assertEqual(result["maintenance_mode"], "session-context-checkpoints")
        self.assertEqual(result["markdown_documents"], 1)
        self.assertEqual(
            result["supporting_files"],
            ["docs/.codebase-map/assets/runtime.svg"],
        )

    def test_skill_allows_implicit_invocation(self) -> None:
        skill_config = SCRIPT_PATH.parent.parent / "agents" / "openai.yaml"

        self.assertNotIn(
            "allow_implicit_invocation",
            skill_config.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
