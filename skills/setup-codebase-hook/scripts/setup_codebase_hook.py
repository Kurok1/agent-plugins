#!/usr/bin/env python3
"""
@author: Kurok1 <im.kurokyhanc@gmail.com>
@since: 1.2.0
"""

from __future__ import annotations

import argparse
import copy
import hashlib
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
ANTIGRAVITY_GROUP = "agent-plugins-codebase-map"
ANTIGRAVITY_EVENTS = {"SessionStart": "session-start", "PreInvocation": "pre-invocation"}
VERSIONED_HOOK_RE = re.compile(r"/\.codebase-map/handlers/[0-9a-f]{64}/codebase-hook\.py$")


class SetupError(RuntimeError):
    """Raised when project hooks cannot be updated safely."""


def existing_hook_copy(script_path: Path, expected: bytes | None) -> bool:
    if script_path.is_symlink():
        raise SetupError(f"Refusing to use a symlinked shared hook: {script_path}")
    if not script_path.exists():
        return False
    if not script_path.is_file():
        raise SetupError(f"Shared hook path is not a regular file: {script_path}")
    if expected is not None and script_path.read_bytes() != expected:
        raise SetupError(f"Installed hook does not match its content digest: {script_path}")
    return True


def install_hook_copy(script_path: Path, content: bytes, *, versioned: bool = False) -> bool:
    directory = Path.home()
    for component in script_path.parent.relative_to(directory).parts:
        directory /= component
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise SetupError(f"Expected a regular shared hook directory: {directory}")

    expected = content if versioned else None
    try:
        if existing_hook_copy(script_path, expected):
            return False
        directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{script_path.name}.", dir=directory
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
                if existing_hook_copy(script_path, expected):
                    return False
                raise
        finally:
            temporary_path.unlink(missing_ok=True)
    except OSError as error:
        raise SetupError(
            f"Cannot install the shared codebase hook: {script_path}"
        ) from error
    return True


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
    return payload


def command_runs_codebase_map_hook(
    command: Any, hook_event: str, *, antigravity: bool = False
) -> bool:
    if not isinstance(command, str):
        return False
    normalized = command.replace("\\", "/")
    try:
        if normalized.startswith("py -3 "):
            # The Windows launcher uses double quotes. An apostrophe is part of the path.
            arguments = [arg.strip('"') for arg in shlex.split(normalized, posix=False)]
        else:
            arguments = shlex.split(normalized)
    except ValueError:
        return False
    if antigravity:
        if arguments[:2] == ["py", "-3"]:
            arguments = ["python3", *arguments[2:]]
        return (
            len(arguments) == 6
            and arguments[0] == "python3"
            and VERSIONED_HOOK_RE.search(arguments[1]) is not None
            and arguments[2:5] == ["hook", hook_event, "--project-root"]
        )
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


def validate_antigravity_handlers(handlers: Any, location: str) -> None:
    if not isinstance(handlers, list):
        raise SetupError(f"Expected an array of Antigravity handlers at {location}")
    for handler in handlers:
        if not isinstance(handler, dict):
            raise SetupError(f"Expected a hook handler object at {location}")
        kind = handler.get("type")
        if kind in (None, ""):
            kind = "command"
        if kind not in ("command", "prompt"):
            raise SetupError(f"Unsupported Antigravity handler type at {location}: {kind!r}")
        value = handler.get(kind)
        if not isinstance(value, str) or not value.strip():
            raise SetupError(f"Expected a non-empty {kind} at {location}")
        timeout = handler.get("timeout")
        if timeout is not None and (type(timeout) is not int or not -(2**31) <= timeout < 2**31):
            raise SetupError(f"Expected a 32-bit integer timeout at {location}")


def validate_antigravity_hooks(payload: dict[str, Any], path: Path) -> None:
    # Antigravity skips the whole file when another named group cannot be loaded.
    for name, group in payload.items():
        if group is None:
            continue
        if not isinstance(group, dict) or not isinstance(group.get("enabled"), (bool, type(None))):
            raise SetupError(f"Invalid Antigravity hook group {name}: {path}")
        for event, entries in group.items():
            if entries is None:
                continue
            location = f"{path} ({name}.{event})"
            if event in (*ANTIGRAVITY_EVENTS, "PostInvocation", "Stop"):
                validate_antigravity_handlers(entries, location)
            elif event in ("PreToolUse", "PostToolUse"):
                if not isinstance(entries, list):
                    raise SetupError(f"Expected an array of matcher groups at {location}")
                for entry in entries:
                    if not isinstance(entry, dict) or not isinstance(
                        entry.get("matcher"), (str, type(None))
                    ):
                        raise SetupError(f"Invalid matcher group at {location}")
                    if entry.get("hooks") is not None:
                        validate_antigravity_handlers(entry["hooks"], location)


def merge_antigravity_hooks(
    payload: dict[str, Any], script_path: Path, project_root: Path, hooks_path: Path
) -> dict[str, Any]:
    validate_antigravity_hooks(payload, hooks_path)
    updated = copy.deepcopy(payload)
    if updated.get(ANTIGRAVITY_GROUP) is None:
        updated[ANTIGRAVITY_GROUP] = {}
    group = updated[ANTIGRAVITY_GROUP]
    for event, hook_event in ANTIGRAVITY_EVENTS.items():
        args = [str(script_path), "hook", hook_event, "--project-root", str(project_root)]
        if os.name == "nt":
            command = subprocess.list2cmdline(["py", "-3", *args])
        else:
            command = shlex.join(["python3", *args])
        retained = []
        found = False
        for handler in group.get(event) or []:
            if handler.get("type") in (None, "", "command") and command_runs_codebase_map_hook(
                handler.get("command"), hook_event, antigravity=True
            ):
                if found:
                    continue
                handler["command"] = command
                found = True
            retained.append(handler)
        if not found:
            retained.append({"type": "command", "command": command, "timeout": 3})
        group[event] = retained
    return updated


def project_hooks_target(config_directory: Path) -> Path:
    hooks_path = config_directory / "hooks.json"
    if config_directory.is_symlink():
        raise SetupError(f"Refusing to write through a symlinked config: {config_directory}")
    if config_directory.exists() and not config_directory.is_dir():
        raise SetupError(f"Project config path is not a directory: {config_directory}")
    if hooks_path.is_symlink():
        raise SetupError(f"Refusing to overwrite a symlinked hooks file: {hooks_path}")
    if hooks_path.exists() and not hooks_path.is_file():
        raise SetupError(f"Project hooks path is not a regular file: {hooks_path}")
    return hooks_path


def check_inline_codex_hooks(config_path: Path) -> None:
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
                f"this layer before creating {config_path.with_name('hooks.json')}."
            )


def write_project_hooks(
    path: Path, existing: dict[str, Any], updated: dict[str, Any]
) -> bool:
    try:
        current = load_project_hooks(project_hooks_target(path.parent))
        if current == updated:
            return False
        if current != existing:
            raise SetupError(f"Project hooks changed during setup: {path}. Run setup again.")
        atomic_write_json(path, updated)
    except OSError as error:
        raise SetupError(f"Cannot write project hooks: {path} ({error}). Run setup again.") from error
    return True


def setup_project_hooks(raw_project_root: str | Path) -> dict[str, Any]:
    project_root = resolve_project_root(raw_project_root)
    codex_path = project_hooks_target(project_root / ".codex")
    antigravity_path = project_hooks_target(project_root / ".agents")
    check_inline_codex_hooks(codex_path.with_name("config.toml"))
    codex_existing = load_project_hooks(codex_path)
    antigravity_existing = load_project_hooks(antigravity_path)

    try:
        content = CODEBASE_HOOK_SOURCE.read_bytes()
    except OSError as error:
        raise SetupError(f"Cannot read the bundled codebase hook: {CODEBASE_HOOK_SOURCE}") from error
    shared = Path.home() / ".codebase-map"
    codex_script = shared / "codebase-hook.py"
    digest = hashlib.sha256(content).hexdigest()
    antigravity_script = shared / "handlers" / digest / "codebase-hook.py"
    codex_updated = merge_project_hooks(codex_existing, codex_script, codex_path)
    antigravity_updated = merge_antigravity_hooks(
        antigravity_existing, antigravity_script, project_root, antigravity_path
    )

    codex_created = install_hook_copy(codex_script, content)
    antigravity_created = install_hook_copy(antigravity_script, content, versioned=True)
    codex_changed = write_project_hooks(codex_path, codex_existing, codex_updated)
    try:
        antigravity_changed = write_project_hooks(
            antigravity_path, antigravity_existing, antigravity_updated
        )
    except SetupError as error:
        raise SetupError(f"{error} Codex configuration is ready at {codex_path}.") from error
    codex = {
        "hooks_file": str(codex_path),
        "script": str(codex_script),
        "script_created": codex_created,
        "events": list(PROJECT_HOOK_SPECS),
        "changed": codex_changed,
    }
    antigravity = {
        "hooks_file": str(antigravity_path),
        "script": str(antigravity_script),
        "script_created": antigravity_created,
        "events": list(ANTIGRAVITY_EVENTS),
        "enabled": antigravity_updated[ANTIGRAVITY_GROUP].get("enabled") is not False,
        "changed": antigravity_changed,
    }
    return {
        **codex,
        "configured": True,
        "changed": codex_changed or antigravity_changed,
        "project_root": str(project_root),
        "targets": {"codex": codex, "antigravity": antigravity},
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
