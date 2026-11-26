"""
@author: Kurok1 <im.kurokyhanc@gmail.com>
@since: 1.2.0
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "setup-codebase-hook"
    / "scripts"
    / "setup_codebase_hook.py"
)
SPEC = importlib.util.spec_from_file_location("setup_codebase_hook_script", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load setup-codebase-hook script: {SCRIPT_PATH}")
SETUP = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SETUP
SPEC.loader.exec_module(SETUP)


class SetupCodebaseHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name).resolve()
        self.user_home = self.root / "user home"
        self.user_home.mkdir()
        self.shared_hook = self.user_home / ".codebase-map" / "codebase-hook.py"
        home_patch = mock.patch.object(SETUP.Path, "home", return_value=self.user_home)
        home_patch.start()
        self.addCleanup(home_patch.stop)
        (self.root / "package.json").write_text(
            '{"name":"setup-hooks-test","version":"1.0.0"}\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _setup(self, project_root: Path | None = None) -> dict[str, Any]:
        return SETUP.setup_project_hooks(project_root or self.root)

    @staticmethod
    def _owned_handlers(payload: dict[str, Any], event_name: str) -> list[dict[str, Any]]:
        hook_event = SETUP.PROJECT_HOOK_SPECS[event_name]["hook_event"]
        return [
            handler
            for group in payload["hooks"][event_name]
            for handler in group["hooks"]
            if SETUP.is_codebase_map_handler(handler, hook_event)
        ]

    def test_setup_uses_explicit_non_git_directory_without_ancestor_discovery(self) -> None:
        nested = self.root / "src" / "nested"
        nested.mkdir(parents=True)

        result = self._setup(nested)

        hooks_path = nested / ".codex" / "hooks.json"
        payload = json.loads(hooks_path.read_text(encoding="utf-8"))
        self.assertTrue(result["configured"])
        self.assertTrue(result["changed"])
        self.assertTrue(result["script_created"])
        self.assertEqual(Path(result["script"]), self.shared_hook)
        self.assertEqual(self.shared_hook.read_bytes(), SETUP.CODEBASE_HOOK_SOURCE.read_bytes())
        self.assertFalse((self.shared_hook.parent / "hooks.json").exists())
        self.assertFalse((self.user_home / ".codex").exists())
        self.assertEqual(Path(result["project_root"]), nested)
        self.assertEqual(Path(result["hooks_file"]), hooks_path)
        self.assertFalse((self.root / ".codex").exists())
        self.assertEqual(set(payload["hooks"]), set(SETUP.PROJECT_HOOK_SPECS))
        self.assertEqual(
            payload["hooks"]["SessionStart"][0]["matcher"],
            "startup|resume|clear|compact",
        )
        for event_name in SETUP.PROJECT_HOOK_SPECS:
            handlers = self._owned_handlers(payload, event_name)
            self.assertEqual(len(handlers), 1)
            self.assertIn(str(self.shared_hook), handlers[0]["command"])
            self.assertNotIn(str(SETUP.CODEBASE_HOOK_SOURCE), handlers[0]["command"])
            self.assertNotIn("PLUGIN_ROOT", handlers[0]["command"])
            self.assertIn(
                str(self.shared_hook),
                handlers[0]["commandWindows"],
            )

    def test_setup_preserves_other_hooks_refreshes_session_start_and_is_idempotent(
        self,
    ) -> None:
        hooks_path = self.root / ".codex" / "hooks.json"
        hooks_path.parent.mkdir()
        third_party_handler = {
            "type": "command",
            "command": "python3 /opt/project/check.py",
        }
        stale_handler = {
            "type": "command",
            "command": (
                'python3 "$PLUGIN_ROOT/skills/codebase-map/scripts/codebase_map.py" '
                "hook session-start"
            ),
        }
        shared_handler = SETUP.project_hook_group("SessionStart", self.shared_hook)["hooks"][0]
        windows_handler = {
            "type": "command",
            "commandWindows": (
                'py -3 "C:\\Users\\Old User\\.codex\\codebase-hook.py" hook session-start'
            ),
        }
        original = {
            "description": "Keep this project configuration",
            "custom": {"keep": True},
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": [third_party_handler]}],
                "SessionStart": [
                    {"matcher": "custom", "hooks": [third_party_handler, stale_handler]},
                    {"hooks": [stale_handler]},
                    {"hooks": [shared_handler, windows_handler]},
                ],
                "Stop": [{"hooks": [third_party_handler]}],
            },
        }
        hooks_path.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")

        first_result = self._setup()
        first_bytes = hooks_path.read_bytes()
        payload = json.loads(first_bytes)

        self.assertTrue(first_result["changed"])
        self.assertEqual(payload["description"], original["description"])
        self.assertEqual(payload["custom"], original["custom"])
        self.assertEqual(payload["hooks"]["PreToolUse"], original["hooks"]["PreToolUse"])
        self.assertEqual(payload["hooks"]["Stop"], original["hooks"]["Stop"])
        self.assertEqual(payload["hooks"]["SessionStart"][0]["hooks"][0], third_party_handler)
        self.assertEqual(payload["hooks"]["SessionStart"][0]["matcher"], "custom")
        self.assertEqual(len(payload["hooks"]["SessionStart"]), 1)
        self.assertEqual(len(self._owned_handlers(payload, "SessionStart")), 1)

        second_result = self._setup()

        self.assertFalse(second_result["changed"])
        self.assertFalse(second_result["script_created"])
        self.assertEqual(hooks_path.read_bytes(), first_bytes)

    def test_existing_hook_changes_only_command_fields(self) -> None:
        hooks_path = self.root / ".codex" / "hooks.json"
        hooks_path.parent.mkdir()
        existing_group = SETUP.project_hook_group(
            "SessionStart",
            self.user_home / ".codex" / "codebase-hook.py",
        )
        existing_group["matcher"] = "startup|resume"
        existing_handler = existing_group["hooks"][0]
        existing_handler["timeout"] = 9
        existing_handler["statusMessage"] = "Keep my status message"
        existing_handler["additionalContextLimit"] = 4200
        unrelated_group = {
            "matcher": "clear",
            "hooks": [
                {"type": "command", "command": "echo unrelated hook"},
            ],
        }
        original = {"hooks": {"SessionStart": [existing_group, unrelated_group]}}
        hooks_path.write_text(json.dumps(original), encoding="utf-8")
        expected = copy.deepcopy(original)
        replacement = SETUP.project_hook_group("SessionStart", self.shared_hook)[
            "hooks"
        ][0]
        for key in ("command", "commandWindows"):
            expected["hooks"]["SessionStart"][0]["hooks"][0][key] = replacement[key]

        self._setup()

        self.assertEqual(json.loads(hooks_path.read_text(encoding="utf-8")), expected)
        self.assertFalse(self._setup()["changed"])

    def test_setup_preserves_existing_codex_script_and_installs_antigravity_alongside(self) -> None:
        self.shared_hook.parent.mkdir()
        content = b"# Locally maintained hook\n"
        self.shared_hook.write_bytes(content)
        before = self.shared_hook.stat().st_mtime_ns

        first_result = self._setup()
        hooks_path = Path(first_result["hooks_file"])
        hooks_before = hooks_path.stat().st_mtime_ns
        second_result = self._setup()

        self.assertFalse(first_result["script_created"])
        self.assertFalse(second_result["script_created"])
        self.assertFalse(second_result["changed"])
        self.assertEqual(self.shared_hook.read_bytes(), content)
        self.assertEqual(self.shared_hook.stat().st_mtime_ns, before)
        self.assertEqual(hooks_path.stat().st_mtime_ns, hooks_before)
        antigravity = first_result["targets"]["antigravity"]
        self.assertTrue(antigravity["script_created"])
        bundled = SETUP.CODEBASE_HOOK_SOURCE.read_bytes()
        self.assertEqual(Path(antigravity["script"]).parent.name, hashlib.sha256(bundled).hexdigest())
        self.assertEqual(Path(antigravity["script"]).read_bytes(), bundled)

    def test_installed_hook_survives_plugin_relocation_and_is_shared_between_projects(
        self,
    ) -> None:
        plugin_directory = self.root / "plugin version 1"
        plugin_directory.mkdir()
        bundled_hook = plugin_directory / "codebase_hook.py"
        bundled_hook.write_bytes(SETUP.CODEBASE_HOOK_SOURCE.read_bytes())
        with mock.patch.object(SETUP, "CODEBASE_HOOK_SOURCE", bundled_hook):
            first_result = self._setup()
            hooks_path = Path(first_result["hooks_file"])
            hooks_before = hooks_path.read_bytes()
            script_before = self.shared_hook.stat().st_mtime_ns
        relocated = plugin_directory.rename(self.root / "plugin version 2")
        second_project = self.root / "second project"
        second_project.mkdir()
        with mock.patch.object(SETUP, "CODEBASE_HOOK_SOURCE", relocated / bundled_hook.name):
            second_result = self._setup(second_project)

        self.assertEqual(first_result["script"], second_result["script"])
        self.assertEqual(
            first_result["targets"]["antigravity"]["script"],
            second_result["targets"]["antigravity"]["script"],
        )
        self.assertFalse(second_result["script_created"])
        self.assertEqual(self.shared_hook.stat().st_mtime_ns, script_before)
        self.assertEqual(hooks_path.read_bytes(), hooks_before)
        payload = json.loads(hooks_before)
        handler = self._owned_handlers(payload, "SessionStart")[0]
        command = handler["commandWindows" if os.name == "nt" else "command"]
        index = self.root / "docs" / ".codebase-map" / "CODEMAP.md"
        index.parent.mkdir(parents=True)
        index.write_text("# Installed project map\n", encoding="utf-8")
        for source in ("startup", "resume", "clear", "compact"):
            with self.subTest(source=source):
                completed = subprocess.run(
                    command,
                    shell=True,
                    check=False,
                    cwd=second_project,
                    input=json.dumps(
                        {
                            "hook_event_name": "SessionStart",
                            "cwd": str(self.root),
                            "source": source,
                        }
                    ),
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                response = json.loads(completed.stdout)["hookSpecificOutput"]
                self.assertEqual(response["hookEventName"], "SessionStart")
                self.assertIn(f'source="{source}"', response["additionalContext"])
                self.assertIn("# Installed project map", response["additionalContext"])

    def test_setup_reports_missing_source_without_creating_project_hooks(self) -> None:
        with (
            mock.patch.object(SETUP, "CODEBASE_HOOK_SOURCE", self.root / "missing.py"),
            self.assertRaises(SETUP.SetupError),
        ):
            self._setup()

        self.assertFalse(self.shared_hook.exists())
        self.assertFalse((self.root / ".codex" / "hooks.json").exists())

    def test_setup_preserves_a_concurrent_shared_hook_installation(self) -> None:
        content = b"# Installed concurrently\n"

        def install_concurrently(source: Path, destination: Path) -> None:
            destination.write_bytes(content if destination == self.shared_hook else source.read_bytes())
            raise FileExistsError(str(destination))

        with mock.patch.object(SETUP.os, "link", side_effect=install_concurrently):
            result = self._setup()

        self.assertFalse(result["script_created"])
        self.assertEqual(self.shared_hook.read_bytes(), content)
        self.assertFalse(result["targets"]["antigravity"]["script_created"])
        self.assertCountEqual(
            self.shared_hook.parent.iterdir(), [self.shared_hook, self.shared_hook.parent / "handlers"]
        )

    def test_setup_cleans_up_failed_shared_hook_installation(self) -> None:
        with (
            mock.patch.object(SETUP.os, "link", side_effect=PermissionError("denied")),
            self.assertRaises(SETUP.SetupError),
        ):
            self._setup()

        self.assertEqual(list(self.shared_hook.parent.iterdir()), [])
        self.assertFalse((self.root / ".codex" / "hooks.json").exists())

    def test_setup_rejects_a_directory_at_the_shared_hook_path(self) -> None:
        self.shared_hook.mkdir(parents=True)

        with self.assertRaises(SETUP.SetupError):
            self._setup()

        self.assertTrue(self.shared_hook.is_dir())
        self.assertFalse((self.root / ".codex" / "hooks.json").exists())

    @unittest.skipIf(os.name == "nt", "symlink creation may require elevated privileges")
    def test_setup_rejects_a_symlink_at_the_shared_hook_path(self) -> None:
        self.shared_hook.parent.mkdir()
        external_hook = self.root / "external-hook.py"
        self.shared_hook.symlink_to(external_hook)

        with self.assertRaises(SETUP.SetupError):
            self._setup()

        self.assertTrue(self.shared_hook.is_symlink())
        self.assertFalse(external_hook.exists())
        self.assertFalse((self.root / ".codex" / "hooks.json").exists())

    def test_setup_rejects_invalid_json_without_overwriting(self) -> None:
        hooks_path = self.root / ".codex" / "hooks.json"
        hooks_path.parent.mkdir()
        invalid_content = b'{"hooks": '
        hooks_path.write_bytes(invalid_content)

        with self.assertRaises(SETUP.SetupError):
            self._setup()

        self.assertEqual(hooks_path.read_bytes(), invalid_content)
        self.assertFalse(self.shared_hook.exists())

    def test_setup_rejects_non_directory_project_root(self) -> None:
        project_file = self.root / "not-a-directory"
        project_file.write_text("not a project directory\n", encoding="utf-8")

        with self.assertRaises(SETUP.SetupError):
            self._setup(project_file)

    def test_setup_rejects_same_layer_inline_hooks(self) -> None:
        codex_directory = self.root / ".codex"
        codex_directory.mkdir()
        (codex_directory / "config.toml").write_text(
            "[[hooks.Stop]]\n",
            encoding="utf-8",
        )

        with self.assertRaises(SETUP.SetupError):
            self._setup()

        self.assertFalse((codex_directory / "hooks.json").exists())

    @unittest.skipIf(os.name == "nt", "symlink creation may require elevated privileges")
    def test_setup_rejects_symlinked_hooks_file(self) -> None:
        external_hooks = self.root / "external-hooks.json"
        external_hooks.write_text('{"hooks": {}}\n', encoding="utf-8")
        codex_directory = self.root / ".codex"
        codex_directory.mkdir()
        (codex_directory / "hooks.json").symlink_to(external_hooks)

        with self.assertRaises(SETUP.SetupError):
            self._setup()

        self.assertEqual(external_hooks.read_text(encoding="utf-8"), '{"hooks": {}}\n')

    def test_plugin_no_longer_bundles_default_hooks(self) -> None:
        plugin_root = SCRIPT_PATH.parents[3]

        self.assertFalse((plugin_root / "hooks" / "hooks.json").exists())
        self.assertFalse((plugin_root / "hooks.json").exists())
        manifests = [
            json.loads((plugin_root / folder / "plugin.json").read_text(encoding="utf-8"))
            for folder in (".codex-plugin", ".antigravity-plugin")
        ]
        for field in ("name", "version"):
            self.assertEqual(manifests[0][field], manifests[1][field])

    def test_generated_antigravity_commands_run_from_another_directory(self) -> None:
        project = self.root / "project's space"
        project.mkdir()
        index = project / "docs" / ".codebase-map" / "CODEMAP.md"
        index.parent.mkdir(parents=True)
        index.write_text("# Real fixture map\n", encoding="utf-8")
        target = self._setup(project)["targets"]["antigravity"]
        path = Path(target["hooks_file"])
        self.assertEqual(path, project / ".agents" / "hooks.json")
        group = json.loads(path.read_bytes())[SETUP.ANTIGRAVITY_GROUP]
        self.assertEqual(set(group), {"SessionStart", "PreInvocation"})
        for event, handlers in group.items():
            self.assertEqual(len(handlers), 1)
            command = handlers[0]["command"]
            for paths in ([str(self.user_home), str(project)], [str(self.user_home)]):
                with self.subTest(event=event, paths=paths):
                    process = subprocess.run(
                        command, shell=True, cwd=self.user_home,
                        input=json.dumps({"workspacePaths": paths, "conversationId": "fixture"}),
                        capture_output=True, text=True, timeout=5,
                    )
                    self.assertEqual(process.returncode, 0, process.stderr)
                    steps = json.loads(process.stdout)["injectSteps"]
                    if str(project) not in paths:
                        self.assertEqual(steps, [])
                        continue
                    self.assertEqual(len(steps), 1)
                    message = steps[0]["systemMessage"]["systemMessage"]
                    self.assertIn("agent-plugins:codebase-map", message)
                    self.assertEqual("# Real fixture map" in message, event == "SessionStart")
                    self.assertEqual(
                        '<CODEBASE_MAP_CHECKPOINT source="startup">' in message, event == "SessionStart"
                    )

    def test_refreshes_antigravity_after_upgrade_and_keeps_custom_handlers(self) -> None:
        first = self._setup()["targets"]["antigravity"]
        path = Path(first["hooks_file"])
        payload = json.loads(path.read_bytes())
        other_group = {
            "Stop": [{"type": "command", "command": "echo other"}],
            "PreToolUse": [{"matcher": "run_command", "hooks": [{"type": "prompt", "prompt": "Review"}]}],
        }
        payload["other"] = other_group
        group = payload[SETUP.ANTIGRAVITY_GROUP]
        group["enabled"] = False
        group["custom"] = 5
        other_hook = {"command": "echo user"}
        for event in SETUP.ANTIGRAVITY_EVENTS:
            managed = group[event][0]
            managed.pop("type")
            managed["timeout"] = 19
            group[event] = [other_hook, managed, managed]
        path.write_text(json.dumps(payload), encoding="utf-8")
        newer = self.root / "updated.py"
        newer.write_bytes(SETUP.CODEBASE_HOOK_SOURCE.read_bytes() + b"\n")
        with mock.patch.object(SETUP, "CODEBASE_HOOK_SOURCE", newer):
            result = self._setup()
            first_mtime = path.stat().st_mtime_ns
            self.assertFalse(self._setup()["changed"])
            self.assertEqual(path.stat().st_mtime_ns, first_mtime)
        target = result["targets"]["antigravity"]
        self.assertTrue(target["changed"])
        self.assertFalse(target["enabled"])
        self.assertFalse(result["targets"]["codex"]["changed"])
        self.assertNotEqual(target["script"], first["script"])
        self.assertTrue(Path(first["script"]).is_file())
        updated = json.loads(path.read_bytes())
        self.assertEqual(updated["other"], other_group)
        group = updated[SETUP.ANTIGRAVITY_GROUP]
        self.assertFalse(group["enabled"])
        self.assertEqual(group["custom"], 5)
        for event in SETUP.ANTIGRAVITY_EVENTS:
            unrelated, managed = group[event]
            self.assertEqual(unrelated, other_hook)
            self.assertEqual(managed["timeout"], 19)
            self.assertIn(target["script"], managed["command"])

    def test_either_target_can_be_added_without_rewriting_the_other(self) -> None:
        targets = self._setup()["targets"]
        for missing, present in (("codex", "antigravity"), ("antigravity", "codex")):
            with self.subTest(missing=missing):
                Path(targets[missing]["hooks_file"]).unlink()
                kept = Path(targets[present]["hooks_file"])
                modified = kept.stat().st_mtime_ns
                result = self._setup()
                self.assertTrue(result["changed"])
                self.assertTrue(result["targets"][missing]["changed"])
                self.assertFalse(result["targets"][present]["changed"])
                self.assertEqual(kept.stat().st_mtime_ns, modified)

    def test_antigravity_only_refreshes_its_own_command_on_either_platform(self) -> None:
        digest = "a" * 64
        script = rf"C:\Users\O'Brien\.codebase-map\handlers\{digest}\codebase-hook.py"
        command = subprocess.list2cmdline(
            ["py", "-3", script, "hook", "session-start", "--project-root", r"C:\My project"]
        )
        matches = SETUP.command_runs_codebase_map_hook
        self.assertTrue(matches(command, "session-start", antigravity=True))
        self.assertFalse(matches(command + " && echo done", "session-start", antigravity=True))
        self.assertFalse(matches("echo " + command, "session-start", antigravity=True))

    def test_invalid_antigravity_config_leaves_both_targets_untouched(self) -> None:
        path = self.root / ".agents" / "hooks.json"
        path.parent.mkdir()
        for data in (
            "{", "[]", json.dumps({SETUP.ANTIGRAVITY_GROUP: {"SessionStart": {}}}),
            json.dumps({"other": "invalid group"}),
            json.dumps({"other": {"SessionStart": [{"hooks": []}]}}),
            json.dumps({"other": {"PreToolUse": "invalid groups"}}),
        ):
            path.write_text(data, encoding="utf-8")
            with self.subTest(data=data), self.assertRaisesRegex(SETUP.SetupError, "hooks.json"):
                self._setup()
            self.assertEqual(path.read_text(encoding="utf-8"), data)
            self.assertFalse((self.root / ".codex").exists())
            self.assertFalse(self.shared_hook.exists())

    def test_retry_completes_an_interrupted_second_write(self) -> None:
        write = SETUP.atomic_write_json

        def fail_second(path: Path, payload: dict) -> None:
            if path.parent.name == ".agents":
                raise PermissionError("simulated write failure")
            write(path, payload)

        with mock.patch.object(SETUP, "atomic_write_json", side_effect=fail_second):
            with self.assertRaisesRegex(SETUP.SetupError, "hooks.json"):
                self._setup()
        result = self._setup()
        self.assertTrue(result["configured"])
        self.assertFalse(result["targets"]["codex"]["changed"])
        self.assertTrue(result["targets"]["antigravity"]["changed"])

    def test_modified_content_addressed_copy_is_preserved_and_reported(self) -> None:
        target = self._setup()["targets"]["antigravity"]
        script = Path(target["script"])
        script.write_bytes(b"# Locally modified\n")
        project = self.root / "another project"
        project.mkdir()
        with self.assertRaisesRegex(SETUP.SetupError, "content digest"):
            self._setup(project)
        self.assertEqual(script.read_bytes(), b"# Locally modified\n")
        self.assertEqual(list(project.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "symlink creation may require elevated privileges")
    def test_rejects_symlinked_antigravity_targets(self) -> None:
        external = self.root / "external"
        external.mkdir()
        config = self.root / ".agents"
        config.symlink_to(external, target_is_directory=True)
        with self.assertRaises(SETUP.SetupError):
            self._setup()
        self.assertFalse((external / "hooks.json").exists())
        config.unlink()
        self.shared_hook.parent.mkdir()
        (self.shared_hook.parent / "handlers").symlink_to(external, target_is_directory=True)
        with self.assertRaises(SETUP.SetupError):
            self._setup()
        self.assertFalse((self.root / ".codex").exists())
        self.assertEqual(list(external.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
