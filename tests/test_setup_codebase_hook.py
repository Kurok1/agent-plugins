"""
@author: Kurok1 <im.kurokyhanc@gmail.com>
@since: 1.2.0
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


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
            self.assertIn(str(SETUP.CODEBASE_MAP_SCRIPT.resolve()), handlers[0]["command"])
            self.assertNotIn("PLUGIN_ROOT", handlers[0]["command"])
            self.assertIn(
                str(SETUP.CODEBASE_MAP_SCRIPT.resolve()),
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
        original = {
            "description": "Keep this project configuration",
            "custom": {"keep": True},
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": [third_party_handler]}],
                "SessionStart": [
                    {"matcher": "custom", "hooks": [third_party_handler, stale_handler]},
                    {"hooks": [stale_handler]},
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
        self.assertEqual(payload["hooks"]["SessionStart"][0]["hooks"], [third_party_handler])
        self.assertEqual(len(self._owned_handlers(payload, "SessionStart")), 1)

        second_result = self._setup()

        self.assertFalse(second_result["changed"])
        self.assertEqual(hooks_path.read_bytes(), first_bytes)

    def test_setup_rejects_invalid_json_without_overwriting(self) -> None:
        hooks_path = self.root / ".codex" / "hooks.json"
        hooks_path.parent.mkdir()
        invalid_content = b'{"hooks": '
        hooks_path.write_bytes(invalid_content)

        with self.assertRaises(SETUP.SetupError):
            self._setup()

        self.assertEqual(hooks_path.read_bytes(), invalid_content)

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


if __name__ == "__main__":
    unittest.main()
