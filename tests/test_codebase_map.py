"""
@author: Kurok1 <im.kurokyhanc@gmail.com>
@since: 0.1.0
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
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
SPEC.loader.exec_module(CODEBASE_MAP)


class CodebaseMapSubmoduleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name).resolve()
        self.plugin_data = self.root / "plugin-data"
        self.session_id = "session-with-submodules"

        self._init_repository(self.root)
        (self.root / "README.md").write_text("workspace\n", encoding="utf-8")
        self.frontend = self._create_nested_repository("frontend", "src/app.ts")
        self.backend = self._create_nested_repository("backend", "src/api.py")
        (self.root / ".gitmodules").write_text(
            """[submodule \"frontend\"]
\tpath = frontend
\turl = ../frontend.git
[submodule \"backend\"]
\tpath = backend
\turl = ../backend.git
""",
            encoding="utf-8",
        )
        for module_root in (self.frontend, self.backend):
            index = module_root / "docs" / ".codebase-map" / "CODEMAP.md"
            index.parent.mkdir(parents=True)
            index.write_text(f"# {module_root.name}\n", encoding="utf-8")

        self.environment = mock.patch.dict(
            os.environ,
            {"PLUGIN_DATA": str(self.plugin_data)},
            clear=False,
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
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

    def _post_tool_payload(self, patch_paths: list[str], tool_use_id: str) -> dict[str, object]:
        patch = "\n".join(f"*** Update File: {path}" for path in patch_paths)
        return {
            "hook_event_name": "PostToolUse",
            "cwd": str(self.root),
            "session_id": self.session_id,
            "tool_use_id": tool_use_id,
            "turn_id": "turn-1",
            "tool_name": "apply_patch",
            "tool_input": {"patch": patch},
            "tool_response": {},
        }

    def _record_workspace_evidence(self) -> dict[str, object]:
        return CODEBASE_MAP.record_post_tool_use(
            self._post_tool_payload(
                ["README.md", "frontend/src/app.ts", "backend/src/api.py"],
                "tool-across-worktrees",
            )
        )

    def test_post_tool_use_partitions_paths_by_owning_git_root(self) -> None:
        result = self._record_workspace_evidence()

        self.assertEqual(result["recorded"], 3)
        self.assertEqual(len(result["events"]), 3)
        events = {
            Path(json.loads(Path(path).read_text(encoding="utf-8"))["project_root"]):
            json.loads(Path(path).read_text(encoding="utf-8"))
            for path in result["events"]
        }
        self.assertEqual(
            {item["path"] for item in events[self.root]["paths"]},
            {"README.md"},
        )
        self.assertEqual(
            {item["path"] for item in events[self.frontend]["paths"]},
            {"src/app.ts"},
        )
        self.assertEqual(
            {item["path"] for item in events[self.backend]["paths"]},
            {"src/api.py"},
        )

    def test_git_file_marker_is_treated_as_a_submodule_root(self) -> None:
        submodule_root = self.root / "file-marker-submodule"
        source = submodule_root / "src" / "entry.ts"
        source.parent.mkdir(parents=True)
        source.write_text("// submodule\n", encoding="utf-8")
        (submodule_root / ".git").write_text(
            "gitdir: ../.git/modules/file-marker-submodule\n",
            encoding="utf-8",
        )

        owner = CODEBASE_MAP.resolve_evidence_project_root(
            self.root,
            "file-marker-submodule/src/entry.ts",
        )

        self.assertEqual(owner, submodule_root)

    def test_stop_creates_one_pending_file_per_git_root(self) -> None:
        self._record_workspace_evidence()

        pending_paths = CODEBASE_MAP.ensure_pending(
            {"cwd": str(self.root), "session_id": self.session_id, "turn_id": "turn-1"}
        )

        self.assertEqual(len(pending_paths), 3)
        pending_by_root = {
            Path(payload["project_root"]): payload
            for payload in (
                json.loads(path.read_text(encoding="utf-8")) for path in pending_paths
            )
        }
        self.assertEqual(
            {item["path"] for item in pending_by_root[self.root]["paths"]},
            {"README.md"},
        )
        self.assertEqual(
            {item["path"] for item in pending_by_root[self.frontend]["paths"]},
            {"src/app.ts"},
        )
        self.assertEqual(
            {item["path"] for item in pending_by_root[self.backend]["paths"]},
            {"src/api.py"},
        )

    def test_submodule_map_edits_do_not_recapture_hook_evidence(self) -> None:
        result = CODEBASE_MAP.record_post_tool_use(
            self._post_tool_payload(
                ["frontend/docs/.codebase-map/CODEMAP.md"],
                "tool-updating-map",
            )
        )

        self.assertEqual(result, {"recorded": 0})

    def test_deleted_submodule_path_keeps_submodule_ownership(self) -> None:
        deleted_path = self.frontend / "src" / "app.ts"
        deleted_path.unlink()
        payload = self._post_tool_payload([], "tool-deleting-submodule-file")
        payload["tool_input"] = {
            "patch": "*** Delete File: frontend/src/app.ts",
        }

        result = CODEBASE_MAP.record_post_tool_use(payload)

        self.assertEqual(result["recorded"], 1)
        self.assertEqual(len(result["events"]), 1)
        event = json.loads(Path(result["events"][0]).read_text(encoding="utf-8"))
        self.assertEqual(Path(event["project_root"]), self.frontend)
        self.assertEqual(event["paths"], [{"path": "src/app.ts", "operation": "deleted"}])

    def test_session_start_lists_available_submodule_maps(self) -> None:
        context = CODEBASE_MAP.build_start_context(self.root)

        self.assertIn("frontend/docs/.codebase-map/CODEMAP.md", context)
        self.assertIn("backend/docs/.codebase-map/CODEMAP.md", context)

    def test_session_end_delegates_every_pending_worktree(self) -> None:
        self._record_workspace_evidence()
        hook_payload = {
            "hook_event_name": "SessionEnd",
            "cwd": str(self.root),
            "session_id": self.session_id,
            "turn_id": "turn-1",
        }

        with (
            mock.patch.object(CODEBASE_MAP.sys, "stdin", io.StringIO(json.dumps(hook_payload))),
            mock.patch.object(CODEBASE_MAP, "launch_optional_delegate") as launch_delegate,
            redirect_stdout(io.StringIO()),
        ):
            result = CODEBASE_MAP.handle_hook("session-end")

        self.assertEqual(result, 0)
        self.assertEqual(launch_delegate.call_count, 3)

    def test_stop_prompt_includes_every_pending_worktree(self) -> None:
        self._record_workspace_evidence()
        hook_payload = {
            "hook_event_name": "Stop",
            "cwd": str(self.root),
            "session_id": self.session_id,
            "turn_id": "turn-1",
            "stop_hook_active": False,
        }
        output = io.StringIO()

        with (
            mock.patch.object(CODEBASE_MAP.sys, "stdin", io.StringIO(json.dumps(hook_payload))),
            redirect_stdout(output),
        ):
            result = CODEBASE_MAP.handle_hook("stop")

        response = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(response["decision"], "block")
        self.assertIn(str(self.root), response["reason"])
        self.assertIn(str(self.frontend), response["reason"])
        self.assertIn(str(self.backend), response["reason"])


if __name__ == "__main__":
    unittest.main()
