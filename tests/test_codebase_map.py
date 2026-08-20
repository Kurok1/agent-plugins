"""
@author: Kurok1 <im.kurokyhanc@gmail.com>
@since: 0.1.0
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
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

    @staticmethod
    def _iso_timestamp(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00",
            "Z",
        )

    def _acknowledge_session(
        self,
        project_root: Path,
        session_id: str,
        acknowledged_at: datetime,
    ) -> Path:
        session_dir = CODEBASE_MAP.runtime_session_dir(project_root, session_id)
        events_dir = session_dir / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        CODEBASE_MAP.atomic_write_json(events_dir / "event.json", {})
        pending_path = session_dir / "pending.json"
        CODEBASE_MAP.atomic_write_json(
            pending_path,
            {
                "schema_version": CODEBASE_MAP.RUNTIME_SCHEMA_VERSION,
                "session_id": session_id,
                "project_root": str(project_root),
                "event_count": 1,
                "paths": [],
            },
        )
        result = CODEBASE_MAP.acknowledge_pending(
            argparse.Namespace(
                pending=str(pending_path),
                outcome="no-update",
                note="test acknowledgement",
            )
        )
        acknowledgement_path = Path(result["acknowledgement"])
        acknowledgement = json.loads(acknowledgement_path.read_text(encoding="utf-8"))
        acknowledgement["acknowledged_at"] = self._iso_timestamp(acknowledged_at)
        CODEBASE_MAP.atomic_write_json(acknowledgement_path, acknowledgement)
        return Path(result["archive"])

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

    def test_cleanup_expired_acknowledged_sessions_preserves_live_evidence(self) -> None:
        now = datetime(2026, 8, 20, 1, 0, tzinfo=timezone.utc)
        expired = now - timedelta(days=8)
        cutoff = now - timedelta(days=CODEBASE_MAP.RUNTIME_EVIDENCE_RETENTION_DAYS)
        recent = now - timedelta(days=6)

        expired_archive = self._acknowledge_session(self.root, "expired", expired)
        boundary_archive = self._acknowledge_session(self.frontend, "boundary", cutoff)
        recent_archive = self._acknowledge_session(self.backend, "recent", recent)
        current_archive = self._acknowledge_session(self.root, self.session_id, expired)

        pending_archive = self._acknowledge_session(
            self.frontend,
            "new-pending-after-ack",
            expired,
        )
        CODEBASE_MAP.atomic_write_json(
            pending_archive.parent.parent / "pending.json",
            {"new": "evidence"},
        )
        events_archive = self._acknowledge_session(
            self.backend,
            "new-events-after-ack",
            expired,
        )
        CODEBASE_MAP.atomic_write_json(
            events_archive.parent.parent / "events" / "new.json",
            {"new": "evidence"},
        )
        invalid_archive = self._acknowledge_session(
            self.backend,
            "invalid-ack",
            expired,
        )
        invalid_ack_path = invalid_archive / "ack.json"
        invalid_ack = json.loads(invalid_ack_path.read_text(encoding="utf-8"))
        invalid_ack["project_root"] = str(self.root)
        CODEBASE_MAP.atomic_write_json(invalid_ack_path, invalid_ack)
        invalid_utf8_archive = self._acknowledge_session(
            self.frontend,
            "invalid-utf8-ack",
            expired,
        )
        (invalid_utf8_archive / "ack.json").write_bytes(b"\xff\xfe")
        overflowing_time_archive = self._acknowledge_session(
            self.root,
            "overflowing-time-ack",
            expired,
        )
        overflowing_ack_path = overflowing_time_archive / "ack.json"
        overflowing_ack = json.loads(
            overflowing_ack_path.read_text(encoding="utf-8")
        )
        overflowing_ack["acknowledged_at"] = "9999-12-31T23:59:59-23:59"
        CODEBASE_MAP.atomic_write_json(overflowing_ack_path, overflowing_ack)

        delegate_log = expired_archive.parent.parent / "pending.delegate.log"
        delegate_log.write_text("finished\n", encoding="utf-8")
        os.utime(delegate_log, (expired.timestamp(), expired.timestamp()))

        result = CODEBASE_MAP.cleanup_runtime_evidence(self.session_id, now=now)

        self.assertEqual(result["removed_archives"], 1)
        self.assertEqual(result["errors"], 0)
        self.assertFalse(expired_archive.exists())
        self.assertTrue(delegate_log.exists())
        for retained_archive in (
            boundary_archive,
            recent_archive,
            current_archive,
            pending_archive,
            events_archive,
            invalid_archive,
            invalid_utf8_archive,
            overflowing_time_archive,
        ):
            self.assertTrue(retained_archive.exists())

    def test_cleanup_bounds_archive_inspection_and_removal(self) -> None:
        now = datetime(2026, 8, 20, 1, 0, tzinfo=timezone.utc)
        for index in range(4):
            self._acknowledge_session(
                self.root,
                f"expired-{index}",
                now - timedelta(days=8 + index),
            )

        with mock.patch.object(
            CODEBASE_MAP,
            "valid_acknowledgement_time",
            wraps=CODEBASE_MAP.valid_acknowledgement_time,
        ) as validate_acknowledgement:
            result = CODEBASE_MAP.cleanup_runtime_evidence(
                self.session_id,
                now=now,
                max_archives=1,
                max_inspected_archives=2,
            )

        self.assertEqual(result["scanned_archives"], 2)
        self.assertEqual(validate_acknowledgement.call_count, 2)
        self.assertEqual(result["removed_archives"], 1)

    def test_cleanup_bounds_directory_entry_inspection(self) -> None:
        target_runtime_root = CODEBASE_MAP.runtime_root()
        target_runtime_root.mkdir(parents=True, exist_ok=True)
        for index in range(5):
            (target_runtime_root / f"project-{index}").mkdir()

        result = CODEBASE_MAP.cleanup_runtime_evidence(
            self.session_id,
            now=datetime(2026, 8, 20, 1, 0, tzinfo=timezone.utc),
            max_inspected_entries=3,
        )

        self.assertEqual(result["scanned_entries"], 3)
        self.assertEqual(result["removed_archives"], 0)

    def test_cleanup_rechecks_liveness_before_removal(self) -> None:
        now = datetime(2026, 8, 20, 1, 0, tzinfo=timezone.utc)
        archive = self._acknowledge_session(
            self.root,
            "becomes-live",
            now - timedelta(days=8),
        )
        session_dir = archive.parent.parent
        real_liveness_check = CODEBASE_MAP.session_has_live_evidence
        target_checks = 0

        def become_live_before_removal(candidate_session: Path) -> bool:
            nonlocal target_checks
            if candidate_session == session_dir:
                target_checks += 1
                if target_checks == 2:
                    CODEBASE_MAP.atomic_write_json(
                        session_dir / "pending.json",
                        {"new": "evidence"},
                    )
            return real_liveness_check(candidate_session)

        with mock.patch.object(
            CODEBASE_MAP,
            "session_has_live_evidence",
            side_effect=become_live_before_removal,
        ):
            result = CODEBASE_MAP.cleanup_runtime_evidence(self.session_id, now=now)

        self.assertEqual(target_checks, 2)
        self.assertEqual(result["removed_archives"], 0)
        self.assertTrue(archive.exists())
        self.assertTrue((session_dir / "pending.json").is_file())

    @unittest.skipIf(os.name == "nt", "symlink creation may require elevated privileges")
    def test_cleanup_does_not_follow_runtime_symlinks(self) -> None:
        now = datetime(2026, 8, 20, 1, 0, tzinfo=timezone.utc)
        expired = now - timedelta(days=8)
        target_runtime_root = CODEBASE_MAP.runtime_root()
        target_runtime_root.mkdir(parents=True, exist_ok=True)

        external_project = self.root / "external-project"
        external_project.mkdir()
        project_sentinel = external_project / "sentinel.txt"
        project_sentinel.write_text("keep\n", encoding="utf-8")
        (target_runtime_root / "project-link").symlink_to(
            external_project,
            target_is_directory=True,
        )

        project_directory = CODEBASE_MAP.runtime_project_dir(self.root)
        project_directory.mkdir(parents=True, exist_ok=True)
        external_session = self.root / "external-session"
        external_session.mkdir()
        session_sentinel = external_session / "sentinel.txt"
        session_sentinel.write_text("keep\n", encoding="utf-8")
        (project_directory / "session-link").symlink_to(
            external_session,
            target_is_directory=True,
        )

        archive_session = CODEBASE_MAP.runtime_session_dir(self.root, "archive-link")
        archive_processed = archive_session / "processed"
        archive_processed.mkdir(parents=True)
        external_archive = self.root / "external-archive"
        external_archive.mkdir()
        archive_sentinel = external_archive / "sentinel.txt"
        archive_sentinel.write_text("keep\n", encoding="utf-8")
        (archive_processed / "archive-link").symlink_to(
            external_archive,
            target_is_directory=True,
        )

        ack_session_id = "ack-link"
        ack_session = CODEBASE_MAP.runtime_session_dir(self.root, ack_session_id)
        ack_archive = ack_session / "processed" / "archive"
        ack_archive.mkdir(parents=True)
        external_ack = self.root / "external-ack.json"
        CODEBASE_MAP.atomic_write_json(
            external_ack,
            {
                "schema_version": CODEBASE_MAP.RUNTIME_SCHEMA_VERSION,
                "acknowledged_at": self._iso_timestamp(expired),
                "project_root": str(self.root),
                "session_id": ack_session_id,
            },
        )
        (ack_archive / "ack.json").symlink_to(external_ack)

        result = CODEBASE_MAP.cleanup_runtime_evidence(self.session_id, now=now)

        self.assertEqual(result["removed_archives"], 0)
        for sentinel in (project_sentinel, session_sentinel, archive_sentinel, external_ack):
            self.assertTrue(sentinel.exists())
        self.assertTrue((target_runtime_root / "project-link").is_symlink())
        self.assertTrue((project_directory / "session-link").is_symlink())
        self.assertTrue((archive_processed / "archive-link").is_symlink())
        self.assertTrue((ack_archive / "ack.json").is_symlink())

    def test_cleanup_continues_after_archive_removal_error(self) -> None:
        now = datetime(2026, 8, 20, 1, 0, tzinfo=timezone.utc)
        first_archive = self._acknowledge_session(
            self.root,
            "first-expired",
            now - timedelta(days=9),
        )
        second_archive = self._acknowledge_session(
            self.frontend,
            "second-expired",
            now - timedelta(days=8),
        )
        real_rmtree = CODEBASE_MAP.shutil.rmtree

        def flaky_rmtree(path: Path) -> None:
            if Path(path) == first_archive:
                raise OSError("simulated cleanup race")
            real_rmtree(path)

        with mock.patch.object(CODEBASE_MAP.shutil, "rmtree", side_effect=flaky_rmtree):
            result = CODEBASE_MAP.cleanup_runtime_evidence(self.session_id, now=now)

        self.assertEqual(result["removed_archives"], 1)
        self.assertEqual(result["errors"], 1)
        self.assertTrue(first_archive.exists())
        self.assertFalse(second_archive.exists())

    def test_session_end_delegates_every_pending_worktree_before_cleanup(self) -> None:
        self._record_workspace_evidence()
        hook_payload = {
            "hook_event_name": "SessionEnd",
            "cwd": str(self.root),
            "session_id": self.session_id,
            "turn_id": "turn-1",
        }
        timeline: list[tuple[str, object]] = []
        launched_pending: list[Path] = []

        def launch_delegate(pending_path: Path) -> None:
            self.assertTrue(pending_path.is_file())
            launched_pending.append(pending_path)
            timeline.append(("delegate", pending_path))

        def cleanup(session_id: str) -> dict[str, int]:
            self.assertEqual(len(launched_pending), 3)
            self.assertTrue(all(path.is_file() for path in launched_pending))
            timeline.append(("cleanup", session_id))
            return {}

        with (
            mock.patch.object(CODEBASE_MAP.sys, "stdin", io.StringIO(json.dumps(hook_payload))),
            mock.patch.object(
                CODEBASE_MAP,
                "launch_optional_delegate",
                side_effect=launch_delegate,
            ),
            mock.patch.object(
                CODEBASE_MAP,
                "cleanup_runtime_evidence",
                side_effect=cleanup,
            ) as cleanup_evidence,
            redirect_stdout(io.StringIO()),
        ):
            result = CODEBASE_MAP.handle_hook("session-end")

        self.assertEqual(result, 0)
        self.assertEqual([entry[0] for entry in timeline], ["delegate"] * 3 + ["cleanup"])
        cleanup_evidence.assert_called_once_with(self.session_id)
        pending_roots = {
            Path(json.loads(path.read_text(encoding="utf-8"))["project_root"])
            for path in launched_pending
        }
        self.assertEqual(pending_roots, {self.root, self.frontend, self.backend})

    def test_session_end_runs_cleanup_without_current_pending_evidence(self) -> None:
        hook_payload = {
            "hook_event_name": "SessionEnd",
            "cwd": str(self.root),
            "session_id": "session-without-evidence",
            "turn_id": "turn-1",
        }

        with (
            mock.patch.object(CODEBASE_MAP.sys, "stdin", io.StringIO(json.dumps(hook_payload))),
            mock.patch.object(CODEBASE_MAP, "launch_optional_delegate") as launch_delegate,
            mock.patch.object(CODEBASE_MAP, "cleanup_runtime_evidence") as cleanup_evidence,
            redirect_stdout(io.StringIO()),
        ):
            result = CODEBASE_MAP.handle_hook("session-end")

        self.assertEqual(result, 0)
        launch_delegate.assert_not_called()
        cleanup_evidence.assert_called_once_with("session-without-evidence")

    def test_session_end_ignores_cleanup_filesystem_errors(self) -> None:
        hook_payload = {
            "hook_event_name": "SessionEnd",
            "cwd": str(self.root),
            "session_id": "session-without-evidence",
            "turn_id": "turn-1",
        }

        with (
            mock.patch.object(CODEBASE_MAP.sys, "stdin", io.StringIO(json.dumps(hook_payload))),
            mock.patch.object(
                CODEBASE_MAP,
                "cleanup_runtime_evidence",
                side_effect=OSError("simulated cleanup failure"),
            ),
            redirect_stdout(io.StringIO()),
        ):
            result = CODEBASE_MAP.handle_hook("session-end")

        self.assertEqual(result, 0)

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
