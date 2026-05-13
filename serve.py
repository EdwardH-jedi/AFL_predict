"""
serve.py
---------
Tiny stdlib HTTP server for opening the Quant Dashboard locally without
spinning up FastAPI. Serves `static/quant-dashboard/` on http://localhost:8080
with CORS headers so `fetch("predictions.json")` works from the browser.

Usage:
    python serve.py
    python serve.py --port 9000
    python serve.py --dir static/quant-dashboard
"""

from __future__ import annotations

import argparse
import http.server
import socketserver
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_DIR = REPO_ROOT / "static" / "quant-dashboard"
DEFAULT_PORT = 8080


class _CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler with permissive CORS for local development."""

    def end_headers(self) -> None:  # noqa: D401
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self) -> None:  # CORS preflight
        self.send_response(204)
        self.end_headers()

    # Slightly quieter access log.
    def log_message(self, format: str, *args: Any) -> None:
        print(f"[serve] {self.address_string()} {format % args}")


def _build_handler(directory: Path) -> type[_CORSRequestHandler]:
    class _BoundHandler(_CORSRequestHandler):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, directory=str(directory), **kw)

    return _BoundHandler


def serve(directory: Path, port: int) -> None:
    if not directory.exists():
        raise SystemExit(f"directory not found: {directory}")
    handler = _build_handler(directory)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"[serve] dashboard ready at http://localhost:{port}/")
        print(f"[serve] serving directory {directory}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[serve] stopped.")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--dir", type=Path, default=DEFAULT_DIR,
                   help=f"Directory to serve (default: {DEFAULT_DIR.relative_to(REPO_ROOT)})")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"Port to bind (default: {DEFAULT_PORT})")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    serve(args.dir, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
