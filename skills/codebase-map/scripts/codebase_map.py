#!/usr/bin/env python3
"""
@author: Kurok1 <im.kurokyhanc@gmail.com>
@since: 0.1.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, TextIO
from urllib.parse import unquote


RUNTIME_SCHEMA_VERSION = 2
MAP_RELATIVE_PATH = Path("docs") / ".codebase-map"
MAX_CAPTURED_PATHS = 500
MAX_SESSION_PATHS = 200
MAX_RESPONSE_CHARACTERS = 1_000_000
MAX_START_CONTEXT_CHARACTERS = 10_000
OPERATION_PRIORITY = {"observed": 1, "modified": 2, "created": 3, "deleted": 4}

PROJECT_MARKERS = (
    ".git",
    ".codex",
    ".codex-plugin",
    "pyproject.toml",
    "package.json",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "go.mod",
    "Cargo.toml",
    "composer.json",
)
EXCLUDED_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "target",
    "vendor",
}

PATH_KEY_RE = re.compile(r"(?:^|_)(?:file|path|paths|filename|files)(?:$|_)", re.I)
PATCH_PATH_RE = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+)$", re.M)
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
COORDINATE_RE = re.compile(
    r"\[[^\]]+\]\(([^)]+)\)\s*(?:→|->)\s*`([^`]+)`"
)
ABSOLUTE_PATH_RE = re.compile(r"(?<![\w.])/(?:[^\s<>|:'\"]+/)*[^\s<>|:'\"]+")
RELATIVE_PATH_RE = re.compile(
    r"(?<![\w.-])(?:\.{1,2}/)?(?:[\w@+.-]+/)+[\w@+.-]+(?:\.[A-Za-z0-9_-]+)?"
)
LINE_SUFFIX_RE = re.compile(r"^(.*?):\d+(?::\d+)?(?:[:\s].*)?$")
CONTROL_COMMAND_RE = re.compile(
    r"\bcodebase_map\.py\b[^\n]*(?:\bhook\b|\back\b|\bpending\b|\bstatus\b|\bvalidate\b)"
)
SYMBOL_TOKEN_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


class MapError(RuntimeError):
    """Raised when hook evidence or a Markdown map cannot be handled safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def stable_hash(value: str, length: int = 20) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def safe_component(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.") or "unknown"
    return f"{slug[:80]}-{stable_hash(value, 8)}"


def atomic_write_json(path: Path, payload: Any) -> None:
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


def resolve_project_root(raw_cwd: str | Path) -> Path:
    cwd = Path(raw_cwd).expanduser().resolve()
    if cwd.is_file():
        cwd = cwd.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=1,
        )
        root = Path(result.stdout.strip()).resolve()
        if root == cwd or root in cwd.parents:
            return root
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    for candidate in (cwd, *cwd.parents):
        if any((candidate / marker).exists() for marker in PROJECT_MARKERS):
            return candidate
    return cwd


def map_root(project_root: Path) -> Path:
    return project_root / MAP_RELATIVE_PATH


def runtime_root(override: str | Path | None = None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    plugin_data = os.environ.get("PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        return Path(plugin_data).expanduser().resolve() / "codebase-map" / "runtime"
    return Path(tempfile.gettempdir()).resolve() / "codex-codebase-map-runtime"


def runtime_project_dir(project_root: Path, override: str | Path | None = None) -> Path:
    return runtime_root(override) / stable_hash(str(project_root.resolve()))


def runtime_session_dir(
    project_root: Path,
    session_id: str,
    override: str | Path | None = None,
) -> Path:
    return runtime_project_dir(project_root, override) / safe_component(session_id)


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_excluded(relative_path: Path) -> bool:
    if relative_path == Path("."):
        return True
    if relative_path.parts[:2] == ("docs", ".codebase-map"):
        return True
    return bool(set(relative_path.parts) & EXCLUDED_PARTS)


def clean_candidate(raw_value: str) -> str:
    value = raw_value.strip().strip("`'\"<>{}[](),;")
    if value.startswith("file://"):
        value = value[7:]
    suffix_match = LINE_SUFFIX_RE.match(value)
    if suffix_match:
        value = suffix_match.group(1)
    return value.strip().strip("`'\"<>{}[](),;")


def normalize_path(
    raw_value: str,
    project_root: Path,
    cwd: Path,
    *,
    allow_missing: bool = False,
) -> str | None:
    value = clean_candidate(raw_value)
    if not value or "\n" in value or "\x00" in value:
        return None
    if value.startswith(("http://", "https://", "mailto:", "codex://")):
        return None

    raw_path = Path(value).expanduser()
    candidates = [raw_path] if raw_path.is_absolute() else [cwd / raw_path, project_root / raw_path]
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            continue
        if not is_within(resolved, project_root):
            continue
        if not allow_missing and not resolved.exists():
            continue
        relative = resolved.relative_to(project_root)
        if is_excluded(relative):
            continue
        return relative.as_posix()
    return None


def iter_string_values(value: Any, key: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        for child_key, child_value in value.items():
            yield from iter_string_values(child_value, str(child_key))
    elif isinstance(value, list):
        for child_value in value:
            yield from iter_string_values(child_value, key)


def string_path_candidates(value: str, *, shell_tokens: bool = False) -> Iterator[str]:
    for match in MARKDOWN_LINK_RE.finditer(value):
        yield match.group(1)
    for match in ABSOLUTE_PATH_RE.finditer(value):
        yield match.group(0)
    for match in RELATIVE_PATH_RE.finditer(value):
        yield match.group(0)

    for line in value.splitlines()[:5000]:
        stripped = line.strip()
        if not stripped or len(stripped) > 1000:
            continue
        yield stripped
        if ":" in stripped:
            yield stripped.split(":", 1)[0]

    if shell_tokens:
        try:
            for token in shlex.split(value, posix=os.name != "nt"):
                if token and not token.startswith("-"):
                    yield token
        except ValueError:
            return


def operation_from_tool(tool_name: str, tool_input: Any) -> str:
    lowered = tool_name.lower()
    if "delete" in lowered:
        return "deleted"
    if any(word in lowered for word in ("apply_patch", "edit", "write", "create")):
        return "modified"
    command_text = "\n".join(value for _, value in iter_string_values(tool_input))
    if re.search(r"(?:^|[;&|]\s*)(?:rm|unlink)\s", command_text):
        return "deleted"
    if re.search(r"(?:^|[;&|]\s*)(?:cp|mv|touch|mkdir|install)\s", command_text):
        return "modified"
    if re.search(r"\bsed\s+[^\n]*\s-i(?:\s|$)", command_text):
        return "modified"
    return "observed"


def add_path_operation(path_operations: dict[str, str], path: str | None, operation: str) -> None:
    if path is None or len(path_operations) >= MAX_CAPTURED_PATHS:
        return
    current = path_operations.get(path)
    if current is None or OPERATION_PRIORITY[operation] > OPERATION_PRIORITY[current]:
        path_operations[path] = operation


def is_control_tool_call(tool_name: str, tool_input: Any) -> bool:
    if tool_name.lower() != "bash":
        return False
    command_text = "\n".join(value for _, value in iter_string_values(tool_input))
    return bool(CONTROL_COMMAND_RE.search(command_text))


def extract_path_operations(payload: dict[str, Any], project_root: Path) -> dict[str, str]:
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    if is_control_tool_call(tool_name, tool_input):
        return {}

    cwd = Path(payload.get("cwd") or project_root).expanduser().resolve()
    if not is_within(cwd, project_root):
        cwd = project_root
    tool_response = payload.get("tool_response")
    default_operation = operation_from_tool(tool_name, tool_input)
    path_operations: dict[str, str] = {}

    for _, text in iter_string_values(tool_input):
        for action, raw_path in PATCH_PATH_RE.findall(text):
            operation = {"Add": "created", "Update": "modified", "Delete": "deleted"}[action]
            add_path_operation(
                path_operations,
                normalize_path(raw_path, project_root, cwd, allow_missing=True),
                operation,
            )

    for key, text in iter_string_values(tool_input):
        if PATH_KEY_RE.search(key):
            add_path_operation(
                path_operations,
                normalize_path(
                    text,
                    project_root,
                    cwd,
                    allow_missing=default_operation == "deleted",
                ),
                default_operation,
            )
        for candidate in string_path_candidates(text, shell_tokens=tool_name.lower() == "bash"):
            add_path_operation(
                path_operations,
                normalize_path(
                    candidate,
                    project_root,
                    cwd,
                    allow_missing=default_operation == "deleted",
                ),
                default_operation,
            )

    remaining = MAX_RESPONSE_CHARACTERS
    for key, text in iter_string_values(tool_response):
        if remaining <= 0:
            break
        bounded = text[:remaining]
        remaining -= len(bounded)
        if PATH_KEY_RE.search(key):
            add_path_operation(
                path_operations,
                normalize_path(bounded, project_root, cwd),
                "observed",
            )
        for candidate in string_path_candidates(bounded):
            add_path_operation(
                path_operations,
                normalize_path(candidate, project_root, cwd),
                "observed",
            )
    return path_operations


def record_post_tool_use(payload: dict[str, Any]) -> dict[str, Any]:
    project_root = resolve_project_root(payload.get("cwd") or Path.cwd())
    path_operations = extract_path_operations(payload, project_root)
    if not path_operations:
        return {"recorded": 0}

    session_id = str(payload.get("session_id") or "unknown")
    tool_use_id = str(payload.get("tool_use_id") or uuid.uuid4())
    event = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "turn_id": payload.get("turn_id"),
        "recorded_at": utc_now(),
        "project_root": str(project_root),
        "tool_name": str(payload.get("tool_name") or "unknown"),
        "paths": [
            {"path": path, "operation": operation}
            for path, operation in sorted(path_operations.items())
        ],
    }
    event_path = (
        runtime_session_dir(project_root, session_id)
        / "events"
        / f"{safe_component(tool_use_id)}.json"
    )
    atomic_write_json(event_path, event)
    return {"recorded": len(path_operations), "event": str(event_path)}


def load_event_files(session_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    events: list[tuple[Path, dict[str, Any]]] = []
    for event_path in sorted((session_dir / "events").glob("*.json")):
        try:
            payload = json.loads(event_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            events.append((event_path, payload))
    return events


def aggregate_events(events: Iterable[tuple[Path, dict[str, Any]]]) -> list[dict[str, str]]:
    path_operations: dict[str, str] = {}
    for _, event in events:
        paths = event.get("paths")
        if not isinstance(paths, list):
            continue
        for item in paths:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            operation = item.get("operation")
            if isinstance(path, str) and operation in OPERATION_PRIORITY:
                add_path_operation(path_operations, path, operation)
    ordered = sorted(
        path_operations.items(),
        key=lambda item: (-OPERATION_PRIORITY[item[1]], item[0]),
    )[:MAX_SESSION_PATHS]
    return [{"path": path, "operation": operation} for path, operation in ordered]


def ensure_pending(payload: dict[str, Any]) -> Path | None:
    project_root = resolve_project_root(payload.get("cwd") or Path.cwd())
    session_id = str(payload.get("session_id") or "unknown")
    session_dir = runtime_session_dir(project_root, session_id)
    events = load_event_files(session_dir)
    paths = aggregate_events(events)
    if not paths:
        return None

    pending_path = session_dir / "pending.json"
    pending = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "purpose": "Ephemeral evidence for a Markdown codebase-map update decision",
        "created_at": utc_now(),
        "session_id": session_id,
        "turn_id": payload.get("turn_id"),
        "model": payload.get("model"),
        "project_root": str(project_root),
        "map_root": str(map_root(project_root)),
        "skill_dir": str(Path(__file__).resolve().parent.parent),
        "event_count": len(events),
        "paths": paths,
        "constraints": [
            "Decide UPDATE or NO_UPDATE from durable navigation value.",
            "Inspect only these paths and narrowly required adjacent source.",
            "Keep durable knowledge as Markdown under docs/.codebase-map.",
            "Validate Markdown before acknowledging this evidence.",
        ],
    }
    atomic_write_json(pending_path, pending)
    return pending_path


def unacknowledged_pending(project_root: Path) -> list[Path]:
    project_dir = runtime_project_dir(project_root)
    if not project_dir.exists():
        return []
    pending = [path for path in project_dir.glob("*/pending.json") if path.is_file()]
    pending.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return pending


def parse_link_destination(raw_destination: str) -> str:
    destination = raw_destination.strip()
    if destination.startswith("<") and ">" in destination:
        destination = destination[1 : destination.index(">")]
    elif re.search(r"\s+[\"']", destination):
        destination = re.split(r"\s+[\"']", destination, maxsplit=1)[0]
    return unquote(destination.strip())


def resolve_local_link(
    document: Path,
    raw_destination: str,
    project_root: Path,
) -> tuple[Path | None, str | None]:
    destination = parse_link_destination(raw_destination)
    if not destination or destination.startswith("#"):
        return None, None
    if destination.startswith(("http://", "https://", "mailto:", "data:", "codex://")):
        return None, None
    without_anchor = destination.split("#", 1)[0].split("?", 1)[0]
    if not without_anchor:
        return None, None
    raw_path = Path(without_anchor)
    if raw_path.is_absolute():
        return None, "absolute local links are not portable"
    try:
        resolved = (document.parent / raw_path).resolve(strict=False)
    except OSError as error:
        return None, f"cannot resolve link: {error}"
    if not is_within(resolved, project_root):
        return None, "link escapes the project root"
    return resolved, None


def symbol_leaf(symbol: str) -> str | None:
    tokens = SYMBOL_TOKEN_RE.findall(symbol)
    return tokens[-1] if tokens else None


def validate_map(project_root: Path) -> dict[str, Any]:
    target = map_root(project_root)
    errors: list[str] = []
    warnings: list[str] = []
    checked_links = 0
    checked_coordinates = 0

    if not target.exists():
        errors.append(f"Map directory does not exist: {target}")
        return {
            "valid": False,
            "project_root": str(project_root),
            "map_root": str(target),
            "documents": 0,
            "checked_links": 0,
            "checked_coordinates": 0,
            "errors": errors,
            "warnings": warnings,
        }

    all_files = sorted(path for path in target.rglob("*") if path.is_file())
    for path in all_files:
        if path.suffix.lower() != ".md":
            errors.append(
                f"Durable map artifact must be Markdown: {path.relative_to(project_root).as_posix()}"
            )

    markdown_files = [path for path in all_files if path.suffix.lower() == ".md"]
    index_path = target / "CODEMAP.md"
    if not index_path.is_file():
        errors.append(f"Missing map index: {index_path.relative_to(project_root).as_posix()}")

    markdown_set = {path.resolve() for path in markdown_files}
    markdown_edges: dict[Path, set[Path]] = {path.resolve(): set() for path in markdown_files}

    for document in markdown_files:
        try:
            content = document.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            errors.append(f"Cannot read {document.relative_to(project_root)}: {error}")
            continue
        document_label = document.relative_to(project_root).as_posix()

        if document == index_path and len(content) > MAX_START_CONTEXT_CHARACTERS:
            warnings.append(
                f"{document_label} exceeds the {MAX_START_CONTEXT_CHARACTERS}-character SessionStart budget"
            )

        for match in MARKDOWN_LINK_RE.finditer(content):
            raw_destination = match.group(1)
            resolved, link_error = resolve_local_link(document, raw_destination, project_root)
            if link_error:
                errors.append(f"{document_label}: {link_error}: {raw_destination}")
                continue
            if resolved is None:
                continue
            checked_links += 1
            if not resolved.exists():
                errors.append(f"{document_label}: missing link target: {raw_destination}")
                continue
            resolved_document = resolved.resolve()
            if resolved_document in markdown_set and is_within(resolved_document, target.resolve()):
                markdown_edges[document.resolve()].add(resolved_document)

        for match in COORDINATE_RE.finditer(content):
            raw_destination, symbol = match.groups()
            resolved, link_error = resolve_local_link(document, raw_destination, project_root)
            if link_error or resolved is None or not resolved.is_file():
                continue
            if is_within(resolved.resolve(), target.resolve()):
                continue
            checked_coordinates += 1
            leaf = symbol_leaf(symbol)
            if leaf is None:
                warnings.append(f"{document_label}: cannot parse symbol coordinate: {symbol}")
                continue
            try:
                source = resolved.read_text(encoding="utf-8", errors="ignore")
            except OSError as error:
                warnings.append(f"{document_label}: cannot inspect {raw_destination}: {error}")
                continue
            if leaf not in source:
                warnings.append(
                    f"{document_label}: symbol token `{leaf}` was not found in {raw_destination}"
                )

    if index_path.is_file():
        reachable: set[Path] = set()
        queue: deque[Path] = deque([index_path.resolve()])
        while queue:
            current = queue.popleft()
            if current in reachable:
                continue
            reachable.add(current)
            queue.extend(markdown_edges.get(current, set()) - reachable)
        for document in sorted(markdown_set - reachable):
            errors.append(
                "Map document is unreachable from CODEMAP.md: "
                f"{document.relative_to(project_root).as_posix()}"
            )

    return {
        "valid": not errors,
        "project_root": str(project_root),
        "map_root": str(target),
        "documents": len(markdown_files),
        "checked_links": checked_links,
        "checked_coordinates": checked_coordinates,
        "errors": errors,
        "warnings": warnings,
    }


def build_start_context(project_root: Path) -> str:
    index_path = map_root(project_root) / "CODEMAP.md"
    pending = unacknowledged_pending(project_root)
    sections: list[str] = []

    if index_path.is_file():
        try:
            content = index_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            content = ""
        if content:
            truncated = len(content) > MAX_START_CONTEXT_CHARACTERS
            bounded = content[:MAX_START_CONTEXT_CHARACTERS]
            sections.extend(
                [
                    "A Markdown codebase map is available at docs/.codebase-map/CODEMAP.md.",
                    "Use it as a locator before broad repository search, follow only relevant links, "
                    "and verify paths and symbols against current source.",
                    "<CODEMAP>",
                    bounded,
                    "</CODEMAP>",
                ]
            )
            if truncated:
                sections.append("CODEMAP.md was truncated in hook context; read the file for the remainder.")

    if pending:
        sections.append(
            "Unacknowledged codebase-map evidence exists. Use $codebase-map to decide UPDATE or "
            f"NO_UPDATE. Most recent evidence: {pending[0]}"
        )
    return "\n".join(sections)


def launch_optional_delegate(pending_path: Path) -> dict[str, Any] | None:
    raw_command = os.environ.get("CODEBASE_MAP_DELEGATE_ARGV")
    if not raw_command:
        return None
    try:
        command = json.loads(raw_command)
    except json.JSONDecodeError as error:
        raise MapError("CODEBASE_MAP_DELEGATE_ARGV must be a JSON array") from error
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        raise MapError("CODEBASE_MAP_DELEGATE_ARGV must be a non-empty JSON string array")

    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    replacements = {
        "{pending}": str(pending_path),
        "{project_root}": str(pending["project_root"]),
        "{map_root}": str(pending["map_root"]),
        "{skill_dir}": str(pending["skill_dir"]),
        "{session_id}": str(pending["session_id"]),
    }
    argv: list[str] = []
    for argument in command:
        for placeholder, replacement in replacements.items():
            argument = argument.replace(placeholder, replacement)
        argv.append(argument)

    log_path = pending_path.with_suffix(".delegate.log")
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    with log_path.open("ab") as log_handle:
        process = subprocess.Popen(
            argv,
            cwd=pending["project_root"],
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
            creationflags=creation_flags,
            close_fds=True,
        )
    return {"pid": process.pid, "pending": str(pending_path), "log": str(log_path)}


def read_hook_payload(stdin: TextIO) -> dict[str, Any]:
    try:
        payload = json.load(stdin)
    except json.JSONDecodeError as error:
        raise MapError("Hook stdin must contain one JSON object") from error
    if not isinstance(payload, dict):
        raise MapError("Hook stdin must contain one JSON object")
    return payload


def handle_hook(event: str) -> int:
    payload = read_hook_payload(sys.stdin)
    expected_event = {
        "post-tool-use": "PostToolUse",
        "session-end": "SessionEnd",
        "session-start": "SessionStart",
        "stop": "Stop",
    }[event]
    actual_event = payload.get("hook_event_name")
    if actual_event and actual_event != expected_event:
        raise MapError(f"Expected {expected_event} hook input, received {actual_event}")

    if event == "post-tool-use":
        record_post_tool_use(payload)
        return 0

    if event == "session-start":
        project_root = resolve_project_root(payload.get("cwd") or Path.cwd())
        context = build_start_context(project_root)
        if context:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "SessionStart",
                            "additionalContext": context,
                        }
                    },
                    ensure_ascii=False,
                )
            )
        return 0

    pending_path = ensure_pending(payload)
    if event == "session-end":
        if pending_path:
            try:
                launch_optional_delegate(pending_path)
            except (MapError, OSError, KeyError, json.JSONDecodeError) as error:
                atomic_write_json(
                    pending_path.with_suffix(".delegate-error.json"),
                    {"recorded_at": utc_now(), "error": str(error)},
                )
        return 0

    if payload.get("stop_hook_active") or pending_path is None:
        print("{}")
        return 0

    project_root = resolve_project_root(payload.get("cwd") or Path.cwd())
    reason = (
        "Before finishing this turn, use $codebase-map to decide UPDATE or NO_UPDATE from the "
        "captured project evidence. Keep durable knowledge as linked Markdown under "
        "docs/.codebase-map; do not create a JSON or SQL graph. Inspect only the evidence and "
        "narrowly required adjacent source. If updating, patch the affected Markdown, validate it, "
        "then acknowledge the evidence. If nothing adds durable navigation value, acknowledge it "
        "as no-update without touching the map.\n\n"
        f"Project root: {project_root}\n"
        f"Pending evidence: {pending_path}\n"
        f"Skill directory: {Path(__file__).resolve().parent.parent}"
    )
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


def acknowledge_pending(args: argparse.Namespace) -> dict[str, Any]:
    pending_path = Path(args.pending).expanduser().resolve()
    try:
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MapError(f"Cannot read pending evidence: {pending_path}") from error
    if not isinstance(pending, dict) or pending.get("schema_version") != RUNTIME_SCHEMA_VERSION:
        raise MapError(f"Unsupported pending evidence: {pending_path}")

    session_dir = pending_path.parent
    archive = session_dir / "processed" / safe_component(f"{utc_now()}-{uuid.uuid4().hex[:8]}")
    archive.mkdir(parents=True, exist_ok=False)
    events_dir = session_dir / "events"
    if events_dir.exists():
        events_dir.replace(archive / "events")
    pending_path.replace(archive / "pending.json")
    acknowledgement = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "acknowledged_at": utc_now(),
        "outcome": args.outcome,
        "note": args.note,
        "project_root": pending.get("project_root"),
        "session_id": pending.get("session_id"),
        "event_count": pending.get("event_count"),
        "paths": pending.get("paths"),
    }
    acknowledgement_path = archive / "ack.json"
    atomic_write_json(acknowledgement_path, acknowledgement)
    return {
        "acknowledged": True,
        "outcome": args.outcome,
        "archive": str(archive),
        "acknowledgement": str(acknowledgement_path),
    }


def pending_status(args: argparse.Namespace) -> dict[str, Any]:
    if args.pending:
        pending_path = Path(args.pending).expanduser().resolve()
        try:
            payload = json.loads(pending_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise MapError(f"Cannot read pending evidence: {pending_path}") from error
        return {"exists": True, "pending": str(pending_path), "evidence": payload}

    project_root = resolve_project_root(args.project_root)
    pending = unacknowledged_pending(project_root)
    return {
        "exists": bool(pending),
        "project_root": str(project_root),
        "runtime_root": str(runtime_root()),
        "pending": [str(path) for path in pending],
    }


def status(args: argparse.Namespace) -> dict[str, Any]:
    project_root = resolve_project_root(args.project_root)
    target = map_root(project_root)
    documents = list(target.rglob("*.md")) if target.exists() else []
    non_markdown = [
        path for path in target.rglob("*") if path.is_file() and path.suffix.lower() != ".md"
    ] if target.exists() else []
    pending = unacknowledged_pending(project_root)
    return {
        "project_root": str(project_root),
        "map_root": str(target),
        "map_exists": (target / "CODEMAP.md").is_file(),
        "markdown_documents": len(documents),
        "non_markdown_artifacts": [
            path.relative_to(project_root).as_posix() for path in sorted(non_markdown)
        ],
        "runtime_root": str(runtime_root()),
        "unacknowledged_pending": [str(path) for path in pending],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture ephemeral Codex evidence and validate the Markdown knowledge map at "
            "docs/.codebase-map."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    hook_parser = subparsers.add_parser("hook", help="Handle a Codex lifecycle hook on stdin")
    hook_parser.add_argument(
        "event",
        choices=("session-start", "post-tool-use", "stop", "session-end"),
    )

    validate_parser = subparsers.add_parser("validate", help="Validate a Markdown codebase map")
    validate_parser.add_argument("--project-root", default=".")

    ack_parser = subparsers.add_parser("ack", help="Acknowledge pending hook evidence")
    ack_parser.add_argument("--pending", required=True)
    ack_parser.add_argument("--outcome", required=True, choices=("updated", "no-update"))
    ack_parser.add_argument("--note")

    pending_parser = subparsers.add_parser("pending", help="Show pending hook evidence")
    pending_parser.add_argument("--project-root", default=".")
    pending_parser.add_argument("--pending")

    status_parser = subparsers.add_parser("status", help="Show map and hook-evidence status")
    status_parser.add_argument("--project-root", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "hook":
            return handle_hook(args.event)
        if args.command == "validate":
            project_root = resolve_project_root(args.project_root)
            result = validate_map(project_root)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result["valid"] else 1
        if args.command == "ack":
            result = acknowledge_pending(args)
        elif args.command == "pending":
            result = pending_status(args)
        else:
            result = status(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except MapError as error:
        print(f"codebase-map: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
