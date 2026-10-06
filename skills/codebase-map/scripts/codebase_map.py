#!/usr/bin/env python3
"""
@author: Kurok1 <im.kurokyhanc@gmail.com>
@since: 0.1.0
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from codebase_hook import (
    MAX_START_CONTEXT_CHARACTERS,
    MapError,
    handle_hook,
    is_within,
    map_root,
    resolve_project_root,
)


MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
COORDINATE_RE = re.compile(
    r"\[[^\]]+\]\(([^)]+)\)\s*(?:→|->)\s*`([^`]+)`"
)
SYMBOL_TOKEN_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


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
            "supporting_files": 0,
            "checked_links": 0,
            "checked_coordinates": 0,
            "errors": errors,
            "warnings": warnings,
        }

    all_files = sorted(path for path in target.rglob("*") if path.is_file())
    markdown_files = [path for path in all_files if path.suffix.lower() == ".md"]
    supporting_files = [
        path for path in all_files if path.suffix.lower() != ".md"
    ]
    index_path = target / "CODEMAP.md"
    if not index_path.is_file():
        errors.append(f"Missing map index: {index_path.relative_to(project_root).as_posix()}")

    markdown_set = {path.resolve() for path in markdown_files}
    markdown_edges: dict[Path, set[Path]] = {
        path.resolve(): set() for path in markdown_files
    }

    for document in markdown_files:
        try:
            content = document.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            errors.append(f"Cannot read {document.relative_to(project_root)}: {error}")
            continue
        document_label = document.relative_to(project_root).as_posix()

        if document == index_path and len(content) > MAX_START_CONTEXT_CHARACTERS:
            warnings.append(
                f"{document_label} exceeds the "
                f"{MAX_START_CONTEXT_CHARACTERS}-character SessionStart budget"
            )

        for match in MARKDOWN_LINK_RE.finditer(content):
            raw_destination = match.group(1)
            resolved, link_error = resolve_local_link(
                document,
                raw_destination,
                project_root,
            )
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
            if resolved_document in markdown_set and is_within(
                resolved_document,
                target.resolve(),
            ):
                markdown_edges[document.resolve()].add(resolved_document)

        for match in COORDINATE_RE.finditer(content):
            raw_destination, symbol = match.groups()
            resolved, link_error = resolve_local_link(
                document,
                raw_destination,
                project_root,
            )
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
                    f"{document_label}: symbol token `{leaf}` was not found in "
                    f"{raw_destination}"
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
        "supporting_files": len(supporting_files),
        "checked_links": checked_links,
        "checked_coordinates": checked_coordinates,
        "errors": errors,
        "warnings": warnings,
    }


def status(args: argparse.Namespace) -> dict[str, Any]:
    project_root = resolve_project_root(args.project_root)
    target = map_root(project_root)
    files = (
        sorted(path for path in target.rglob("*") if path.is_file())
        if target.exists()
        else []
    )
    documents = [path for path in files if path.suffix.lower() == ".md"]
    supporting_files = [path for path in files if path.suffix.lower() != ".md"]
    return {
        "project_root": str(project_root),
        "map_root": str(target),
        "map_exists": (target / "CODEMAP.md").is_file(),
        "markdown_documents": len(documents),
        "supporting_files": [
            path.relative_to(project_root).as_posix()
            for path in supporting_files
        ],
        "maintenance_mode": "session-context-checkpoints",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inject context-driven codebase-map checkpoints and validate the Markdown "
            "knowledge map at docs/.codebase-map."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    hook_parser = subparsers.add_parser("hook", help="Handle a Codex lifecycle hook on stdin")
    hook_parser.add_argument("event", choices=("session-start",))

    validate_parser = subparsers.add_parser("validate", help="Validate a Markdown codebase map")
    validate_parser.add_argument("--project-root", default=".")

    status_parser = subparsers.add_parser("status", help="Show codebase-map status")
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
        result = status(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except MapError as error:
        print(f"codebase-map: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
