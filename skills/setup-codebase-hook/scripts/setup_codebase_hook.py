#!/usr/bin/env python3
"""
@author: Kurok1 <im.kurokyhanc@gmail.com>
@since: 1.2.0
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


INLINE_HOOKS_HEADER_RE = re.compile(r"^\s*\[\[?\s*hooks(?:\s*[.\]])", re.M)
CODEBASE_HOOK_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "codebase-map"
    / "scripts"
    / "codebase_hook.py"
)
PROJECT_HOOK_SPECS: dict[str, dict[str, Any]] = {
    "SessionStart": {
        "hook_event": "session-start",
        "matcher": "startup|resume|clear|compact",
        "timeout": 3,
        "statusMessage": "Loading codebase-map checkpoints",
        "additionalContextLimit": 3500,
    },
}


class SetupError(RuntimeError):
    """Raised when project hooks cannot be updated safely."""


def install_shared_hook() -> tuple[Path, bool]:
    script_path = Path.home() / ".codebase-map" / "codebase-hook.py"
    shared_directory = script_path.parent
    if shared_directory.is_symlink():
        raise SetupError(
            f"Refusing to install through a symlinked hook directory: {shared_directory}"
        )
    if shared_directory.exists() and not shared_directory.is_dir():
        raise SetupError(f"Shared hook directory is not a directory: {shared_directory}")
    if script_path.is_symlink():
        raise SetupError(f"Refusing to use a symlinked shared hook: {script_path}")
    if script_path.exists():
        if not script_path.is_file():
            raise SetupError(f"Shared hook path is not a regular file: {script_path}")
        return script_path, False

    try:
        content = CODEBASE_HOOK_SOURCE.read_bytes()
    except OSError as error:
        raise SetupError(
            f"Cannot read the bundled codebase hook: {CODEBASE_HOOK_SOURCE}"
        ) from error

    try:
        shared_directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{script_path.name}.", dir=shared_directory
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            # Publish a complete file without replacing a concurrent installation.
            try:
                os.link(temporary_path, script_path)
            except FileExistsError:
                if script_path.is_symlink() or not script_path.is_file():
                    raise SetupError(
                        f"Shared hook path is not a regular file: {script_path}"
                    )
                return script_path, False
        finally:
            temporary_path.unlink(missing_ok=True)
    except OSError as error:
        raise SetupError(
            f"Cannot install the shared codebase hook: {script_path}"
        ) from error
    return script_path, True


def resolve_project_root(raw_project_root: str | Path) -> Path:
    project_root = Path(raw_project_root).expanduser().resolve()
    if not project_root.is_dir():
        raise SetupError(f"Project root must be an existing directory: {project_root}")
    return project_root


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def validate_hooks_object(hooks: Any, hooks_path: Path) -> None:
    if not isinstance(hooks, dict):
        raise SetupError(f"Hook configuration must contain an object at `hooks`: {hooks_path}")
    for event_name, matcher_groups in hooks.items():
        if not isinstance(matcher_groups, list):
            raise SetupError(f"Hook event `{event_name}` must contain a list: {hooks_path}")
        for index, matcher_group in enumerate(matcher_groups):
            if not isinstance(matcher_group, dict):
                raise SetupError(
                    f"Hook event `{event_name}` group {index} must be an object: {hooks_path}"
                )
            handlers = matcher_group.get("hooks")
            if not isinstance(handlers, list):
                raise SetupError(
                    f"Hook event `{event_name}` group {index} must contain a `hooks` list: "
                    f"{hooks_path}"
                )
            if not all(isinstance(handler, dict) for handler in handlers):
                raise SetupError(
                    f"Hook event `{event_name}` group {index} contains a non-object handler: "
                    f"{hooks_path}"
                )


def load_project_hooks(hooks_path: Path) -> dict[str, Any]:
    if not hooks_path.exists():
        return {}
    try:
        payload = json.loads(hooks_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SetupError(
            f"Cannot read project hooks without overwriting them: {hooks_path}"
        ) from error
    if not isinstance(payload, dict):
        raise SetupError(f"Project hooks must contain one JSON object: {hooks_path}")
    validate_hooks_object(payload.get("hooks", {}), hooks_path)
    return payload


def command_runs_codebase_map_hook(command: Any, hook_event: str) -> bool:
    if not isinstance(command, str):
        return False
    try:
        arguments = shlex.split(command.replace("\\", "/"))
    except ValueError:
        return False
    script_suffixes = (
        "/skills/codebase-map/scripts/codebase_map.py",
        "/.codex/codebase-hook.py",
        "/.codebase-map/codebase-hook.py",
    )
    return any(
        ("/" + argument).endswith(script_suffixes)
        and arguments[index + 1 : index + 3] == ["hook", hook_event]
        for index, argument in enumerate(arguments)
    )


def is_codebase_map_handler(handler: dict[str, Any], hook_event: str) -> bool:
    if handler.get("type") != "command":
        return False
    return command_runs_codebase_map_hook(
        handler.get("command"), hook_event
    ) or command_runs_codebase_map_hook(handler.get("commandWindows"), hook_event)


def project_hook_group(event_name: str, script_path: Path) -> dict[str, Any]:
    spec = PROJECT_HOOK_SPECS[event_name]
    hook_event = str(spec["hook_event"])
    handler: dict[str, Any] = {
        "type": "command",
        "command": f"python3 {shlex.quote(str(script_path))} hook {hook_event}",
        "commandWindows": subprocess.list2cmdline(
            ["py", "-3", str(script_path), "hook", hook_event]
        ),
        "timeout": spec["timeout"],
    }
    for optional_key in ("statusMessage", "additionalContextLimit"):
        if optional_key in spec:
            handler[optional_key] = spec[optional_key]

    group: dict[str, Any] = {}
    if "matcher" in spec:
        group["matcher"] = spec["matcher"]
    group["hooks"] = [handler]
    return group


def merge_project_hooks(
    payload: dict[str, Any],
    script_path: Path,
    hooks_path: Path,
) -> dict[str, Any]:
    updated = copy.deepcopy(payload)
    hooks = updated.setdefault("hooks", {})
    validate_hooks_object(hooks, hooks_path)

    for event_name, spec in PROJECT_HOOK_SPECS.items():
        hook_event = str(spec["hook_event"])
        matcher_groups = hooks.setdefault(event_name, [])
        replacement_group = project_hook_group(event_name, script_path)
        replacement_handler = replacement_group["hooks"][0]
        found_handler = False
        retained_groups: list[dict[str, Any]] = []
        for matcher_group in matcher_groups:
            retained_handlers: list[dict[str, Any]] = []
            for handler in matcher_group["hooks"]:
                if not is_codebase_map_handler(handler, hook_event):
                    retained_handlers.append(handler)
                elif not found_handler:
                    for key in ("command", "commandWindows"):
                        handler[key] = replacement_handler[key]
                    retained_handlers.append(handler)
                    found_handler = True
            if retained_handlers or not matcher_group["hooks"]:
                matcher_group["hooks"] = retained_handlers
                retained_groups.append(matcher_group)
        if not found_handler:
            retained_groups.append(replacement_group)
        hooks[event_name] = retained_groups
    return updated


def project_hooks_target(project_root: Path) -> Path:
    codex_directory = project_root / ".codex"
    hooks_path = codex_directory / "hooks.json"
    config_path = codex_directory / "config.toml"

    if codex_directory.is_symlink():
        raise SetupError(f"Refusing to write through a symlinked config: {codex_directory}")
    if codex_directory.exists() and not codex_directory.is_dir():
        raise SetupError(f"Project config path is not a directory: {codex_directory}")
    if hooks_path.is_symlink():
        raise SetupError(f"Refusing to overwrite a symlinked hooks file: {hooks_path}")
    if hooks_path.exists() and not hooks_path.is_file():
        raise SetupError(f"Project hooks path is not a regular file: {hooks_path}")
    if config_path.is_symlink():
        raise SetupError(f"Refusing to inspect a symlinked project config: {config_path}")
    if config_path.exists():
        try:
            config_text = config_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise SetupError(f"Cannot inspect project config for inline hooks: {config_path}") from error
        if INLINE_HOOKS_HEADER_RE.search(config_text):
            raise SetupError(
                "Project config already defines inline hooks. Keep one hook representation in "
                f"this layer before creating {hooks_path}."
            )
    return hooks_path


def setup_project_hooks(raw_project_root: str | Path) -> dict[str, Any]:
    project_root = resolve_project_root(raw_project_root)
    hooks_path = project_hooks_target(project_root)
    existing = load_project_hooks(hooks_path)
    script_path, script_created = install_shared_hook()
    updated = merge_project_hooks(existing, script_path, hooks_path)
    changed = updated != existing
    if changed:
        try:
            atomic_write_json(hooks_path, updated)
        except OSError as error:
            raise SetupError(f"Cannot write project hooks: {hooks_path}") from error
    return {
        "configured": True,
        "changed": changed,
        "project_root": str(project_root),
        "hooks_file": str(hooks_path),
        "script": str(script_path),
        "script_created": script_created,
        "events": list(PROJECT_HOOK_SPECS),
        "maintenance_mode": "session-context-checkpoints",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install or refresh project-local codebase-map lifecycle hooks."
    )
    parser.add_argument("--project-root", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = setup_project_hooks(args.project_root)
    except SetupError as error:
        print(f"setup-codebase-hook: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
