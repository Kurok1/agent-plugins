#!/usr/bin/env python3
"""
@author: Kurok1 <im.kurokyhanc@gmail.com>
@since: 1.0.2
"""

from __future__ import annotations

import argparse
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit


class LessonRequestHandler(SimpleHTTPRequestHandler):
    """Serve one lesson directory without cache or directory listings."""

    def __init__(
        self,
        *args: object,
        directory: str,
        landing_path: str,
        **kwargs: object,
    ) -> None:
        self._landing_path = landing_path
        super().__init__(*args, directory=directory, **kwargs)

    def _redirect_to_landing_page(self) -> bool:
        if urlsplit(self.path).path != "/" or self._landing_path == "/":
            return False

        self.send_response(HTTPStatus.TEMPORARY_REDIRECT)
        self.send_header("Location", self._landing_path)
        self.end_headers()
        return True

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._redirect_to_landing_page():
            super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._redirect_to_landing_page():
            super().do_HEAD()

    def list_directory(self, path: str) -> None:
        del path
        self.send_error(HTTPStatus.NOT_FOUND, "Directory listing is disabled")
        return None

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()


def parse_port(value: str) -> int:
    port = int(value)
    if not 0 <= port <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 0 and 65535")
    return port


def resolve_target(target: Path) -> tuple[Path, str]:
    resolved = target.expanduser().resolve(strict=True)
    if resolved.is_dir():
        index = resolved / "index.html"
        if not index.is_file():
            raise ValueError(f"lesson directory has no index.html: {resolved}")
        return resolved, "/"

    if resolved.suffix.lower() not in {".html", ".htm"}:
        raise ValueError(f"lesson target is not an HTML file: {resolved}")
    return resolved.parent, f"/{quote(resolved.name)}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve a Teach Me HTML lesson from a local HTTP server."
    )
    parser.add_argument(
        "target",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="lesson directory containing index.html, or a single HTML file",
    )
    parser.add_argument(
        "--bind",
        default="127.0.0.1",
        help="address to bind (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=parse_port,
        default=0,
        help="port to use; 0 selects an available port (default: 0)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        directory, landing_path = resolve_target(args.target)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    handler = partial(
        LessonRequestHandler,
        directory=str(directory),
        landing_path=landing_path,
    )

    try:
        server = ThreadingHTTPServer((args.bind, args.port), handler)
    except OSError as error:
        parser.error(f"could not start server: {error}")

    display_host = "127.0.0.1" if args.bind in {"", "0.0.0.0"} else args.bind
    url = f"http://{display_host}:{server.server_port}{landing_path}"
    print(f"Serving {directory} at {url}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
