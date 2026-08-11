from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit
import webbrowser

from ai_resource_radar.dashboard_state import AiRadarDashboard
from ai_resource_radar.interfaces.assets import resolve_dashboard_asset
from ai_resource_radar.interfaces.http import (
    ApiResponse,
    is_radar_api_path,
    radar_post_body_limit,
    route_radar_get,
    route_radar_post,
)
from ai_resource_radar.paths import default_database_path
from ai_resource_radar.store import UnsupportedSchemaError


_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


class RadarServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    radar: AiRadarDashboard


class RadarHandler(BaseHTTPRequestHandler):
    server_version = "AIResourceRadar/0.7.1"
    sys_version = ""
    server: RadarServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def _security_headers(self, *, api: bool = False) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'",
        )
        self.send_header("Cache-Control", "no-store" if api else "no-cache")

    def _host_allowed(self) -> bool:
        try:
            hostname = urlsplit(f"//{self.headers.get('Host', '')}").hostname
        except ValueError:
            return False
        return hostname in _ALLOWED_HOSTS

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            return urlsplit(origin).hostname in _ALLOWED_HOSTS
        except ValueError:
            return False

    def _trusted(self) -> bool:
        if self._host_allowed() and self._origin_allowed():
            return True
        self._json(403, {"error": "local_request_required"})
        return False

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers(api=True)
        self.end_headers()
        self.wfile.write(body)

    def _send_api_response(self, response: ApiResponse) -> None:
        if response.file_path is None:
            self._json(response.status, response.payload)
            return
        try:
            body = response.file_path.read_bytes()
        except OSError:
            self._json(404, {"error": "daily_poster_not_found"})
            return
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type or "application/octet-stream")
        if response.disposition:
            self.send_header("Content-Disposition", response.disposition)
        self.send_header("Content-Length", str(len(body)))
        self._security_headers(api=True)
        self.end_headers()
        self.wfile.write(body)

    def _schema_failure(self, error: UnsupportedSchemaError) -> None:
        self._json(
            503,
            {
                "error": "ai_radar_schema_unsupported",
                "database_schema_version": error.database_version,
                "runtime_supported_schema_version": error.supported_version,
            },
        )

    def do_GET(self) -> None:
        try:
            self._do_GET()
        except UnsupportedSchemaError as exc:
            self._schema_failure(exc)

    def _do_GET(self) -> None:
        if not self._trusted():
            return
        request_url = urlsplit(self.path)
        response = route_radar_get(
            self.server.radar, request_url.path, request_url.query
        )
        if response is not None:
            self._send_api_response(response)
            return
        asset = resolve_dashboard_asset(request_url.path)
        if asset is None:
            self._json(404, {"error": "not_found"})
            return
        file_path, content_type = asset
        try:
            body = file_path.read_bytes()
        except OSError:
            self._json(500, {"error": "dashboard_asset_unavailable"})
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        try:
            self._do_POST()
        except UnsupportedSchemaError as exc:
            self._schema_failure(exc)

    def _do_POST(self) -> None:
        if not self._trusted():
            return
        path = urlsplit(self.path).path
        if not is_radar_api_path(path):
            self._json(404, {"error": "not_found"})
            return
        body_limit = radar_post_body_limit(path)
        if body_limit is None:
            self._json(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 <= length <= body_limit:
            self._json(413, {"error": "request_too_large"})
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "invalid_json"})
            return
        response = route_radar_post(self.server.radar, path, payload)
        assert response is not None
        self._send_api_response(response)


def create_server(
    *,
    port: int = 18766,
    database: Path | None = None,
    poster_root: Path | None = None,
) -> RadarServer:
    server = RadarServer(("127.0.0.1", port), RadarHandler)
    server.radar = AiRadarDashboard(
        database or default_database_path(),
        poster_root=poster_root,
        project_root=Path.cwd(),
    )
    return server


def serve(
    *,
    port: int = 18766,
    database: Path | None = None,
    poster_root: Path | None = None,
    open_browser: bool = False,
) -> int:
    server = create_server(
        port=port,
        database=database,
        poster_root=poster_root,
    )
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"AI 资源雷达已启动：{url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
