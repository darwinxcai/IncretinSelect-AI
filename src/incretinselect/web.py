"""Serve the verified browser application from an installed package."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Sequence

from incretinselect import __version__
from incretinselect.product import model_info

WEB_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.mjs": ("app.mjs", "text/javascript; charset=utf-8"),
    "/model.mjs": ("model.mjs", "text/javascript; charset=utf-8"),
    "/io.mjs": ("io.mjs", "text/javascript; charset=utf-8"),
    "/demo_manifest.json": ("demo_manifest.json", "application/json; charset=utf-8"),
    "/assets/incretin_ridge_v1.json": (
        "../assets/incretin_ridge_v1.json",
        "application/json; charset=utf-8",
    ),
}


def _asset_bytes(relative_path: str) -> bytes:
    package_root = files("incretinselect")
    if relative_path.startswith("../assets/"):
        asset_name = relative_path.removeprefix("../assets/")
        return package_root.joinpath("assets", asset_name).read_bytes()
    return package_root.joinpath("web_assets", relative_path).read_bytes()


def render_page() -> str:
    """Return the exact HTML served by the local installed application."""

    return _asset_bytes("index.html").decode("utf-8")


def verify_web_assets() -> dict[str, str]:
    """Verify that the packaged interface and model manifest agree."""

    for relative_path, _ in WEB_ASSETS.values():
        _asset_bytes(relative_path)
    page = render_page()
    for marker in (
        "IncretinSelect-AI",
        "Candidate screen",
        "Download screened CSV",
        "Nearest-reference model comparison",
    ):
        if marker not in page:
            raise RuntimeError(f"Packaged browser application is missing: {marker}")
    manifest = json.loads(_asset_bytes("demo_manifest.json"))
    info = model_info()
    if manifest.get("software_version") != __version__:
        raise RuntimeError("Packaged browser manifest does not match the software version")
    if manifest.get("artifact_sha256") != info["artifact_sha256"]:
        raise RuntimeError("Packaged browser manifest does not match the model checksum")
    return {
        "software_version": __version__,
        "artifact_sha256": info["artifact_sha256"],
    }


class ProductHandler(BaseHTTPRequestHandler):
    """Serve only the finite, packaged application asset set."""

    server_version = "IncretinSelectLocal/2.0"

    def _send(
        self,
        content: bytes,
        status: HTTPStatus,
        content_type: str,
        *,
        send_body: bool = True,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'",
        )
        self.end_headers()
        if send_body:
            self.wfile.write(content)

    def _serve(self, *, send_body: bool = True) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/healthz":
            body = (json.dumps({"status": "ok", **verify_web_assets()}) + "\n").encode()
            self._send(
                body,
                HTTPStatus.OK,
                "application/json; charset=utf-8",
                send_body=send_body,
            )
            return
        asset = WEB_ASSETS.get(path)
        if asset is None:
            self._send(
                b"Not found\n",
                HTTPStatus.NOT_FOUND,
                "text/plain; charset=utf-8",
                send_body=send_body,
            )
            return
        relative_path, content_type = asset
        self._send(
            _asset_bytes(relative_path),
            HTTPStatus.OK,
            content_type,
            send_body=send_body,
        )

    def do_GET(self) -> None:  # noqa: N802
        self._serve()

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(send_body=False)

    def do_POST(self) -> None:  # noqa: N802
        self._send(
            b"Method not allowed\n",
            HTTPStatus.METHOD_NOT_ALLOWED,
            "text/plain; charset=utf-8",
        )

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="incretin-web",
        description=(
            "Run the verified IncretinSelect browser application on this computer. "
            "Imported sequences and files are processed in the browser."
        ),
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)."
    )
    parser.add_argument("--port", type=int, default=8000, help="TCP port (default: 8000).")
    parser.add_argument("--open", action="store_true", help="Open the app in the default browser.")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Verify packaged browser assets and exit without starting a server.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smoke_test:
        verified = verify_web_assets()
        print(
            f"ok: verified browser application v{verified['software_version']} with "
            f"model {verified['artifact_sha256']}"
        )
        return 0
    if not 0 <= args.port <= 65535:
        raise SystemExit("port must be between 0 and 65535")
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit(
            "The local app permits only --host 127.0.0.1 or localhost; "
            "it has no authentication and must not be exposed to a network."
        )
    verify_web_assets()
    try:
        server = ThreadingHTTPServer((args.host, args.port), ProductHandler)
    except OSError as exc:
        suggested_port = 8001 if args.port != 8001 else 8002
        print(
            f"error: could not start the local app on {args.host}:{args.port}: {exc}. "
            f"The port may already be in use; try --port {suggested_port}.",
            file=sys.stderr,
        )
        return 2
    host, port = server.server_address[:2]
    url_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else str(host)
    url = f"http://{url_host}:{port}/"
    print(f"IncretinSelect-AI is running at {url}")
    print("Press Ctrl+C to stop. Sequences stay in the local browser.")
    if args.open:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping IncretinSelect-AI.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
