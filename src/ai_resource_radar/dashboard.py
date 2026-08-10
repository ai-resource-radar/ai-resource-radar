from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
import webbrowser

from ai_resource_radar.dashboard_state import AiRadarDashboard
from ai_resource_radar.paths import default_database_path
from ai_resource_radar.store import UnsupportedSchemaError


_ASSET_ROOT = Path(__file__).with_name("web")
_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/ai-resources.html": ("index.html", "text/html; charset=utf-8"),
    "/ai-resources.css": ("ai-resources.css", "text/css; charset=utf-8"),
    "/ai-resources.js": ("ai-resources.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


class RadarServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    radar: AiRadarDashboard


class RadarHandler(BaseHTTPRequestHandler):
    server_version = "AIResourceRadar/0.3"
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

    def _image(self, path: Path) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self._json(404, {"error": "daily_poster_not_found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/webp")
        self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
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
        path = request_url.path
        query = parse_qs(request_url.query)
        if path.startswith("/api/"):
            schema_error = self.server.radar.schema_error()
            if schema_error is not None:
                self._json(503, schema_error)
                return
        if path == "/api/ai-resources/summary":
            self._json(200, self.server.radar.summary())
            return
        if path == "/api/ai-tips/summary":
            self._json(200, self.server.radar.tips_summary())
            return
        if path == "/api/ai-tips":
            try:
                tips = self.server.radar.tips(
                    status=query.get("status", [""])[0] or None,
                    category=query.get("category", [""])[0] or None,
                    risk=query.get("risk", [""])[0] or None,
                    source=query.get("source", [""])[0] or None,
                    scope=query.get("scope", [""])[0] or None,
                    query=query.get("q", [""])[0] or None,
                    limit=int(query.get("limit", ["100"])[0]),
                    offset=int(query.get("offset", ["0"])[0]),
                )
            except (TypeError, ValueError):
                self._json(400, {"error": "invalid_ai_tip_filter"})
                return
            self._json(200, {"schema_version": "1.0", "count": len(tips), "tips": tips})
            return
        if path == "/api/ai-tips/applications":
            try:
                applications = self.server.radar.tip_applications(
                    limit=int(query.get("limit", ["100"])[0])
                )
            except (TypeError, ValueError):
                self._json(400, {"error": "invalid_ai_tip_application_filter"})
                return
            self._json(200, {"schema_version": "1.0", "applications": applications})
            return
        tip_parts = path.strip("/").split("/")
        if len(tip_parts) == 3 and tip_parts[:2] == ["api", "ai-tips"]:
            tip = self.server.radar.tip(tip_parts[2])
            if tip is None:
                self._json(404, {"error": "tip_not_found"})
            else:
                self._json(200, tip)
            return
        if path == "/api/ai-resources":
            mainland_value = query.get("mainland", [""])[0]
            mainland = (
                tuple(item for item in mainland_value.split(",") if item)
                if mainland_value
                else None
            )
            try:
                resources = self.server.radar.offers(
                    kind=query.get("kind", [""])[0] or None,
                    verified_only=query.get("verified", ["false"])[0] == "true",
                    no_card=query.get("no_card", ["false"])[0] == "true",
                    free_image_generation=(
                        query.get("free_image_generation", ["false"])[0] == "true"
                    ),
                    mainland=mainland,
                    query=query.get("q", [""])[0] or None,
                    limit=int(query.get("limit", ["100"])[0]),
                    offset=int(query.get("offset", ["0"])[0]),
                )
            except (TypeError, ValueError):
                self._json(400, {"error": "invalid_ai_resource_filter"})
                return
            self._json(
                200,
                {"schema_version": "2.0", "count": len(resources), "resources": resources},
            )
            return
        if path == "/api/ai-resources/changes":
            try:
                changes = self.server.radar.changes(
                    days=int(query.get("days", ["30"])[0]),
                    limit=int(query.get("limit", ["100"])[0]),
                )
            except (TypeError, ValueError):
                self._json(400, {"error": "invalid_ai_change_filter"})
                return
            self._json(
                200,
                {"schema_version": "2.0", "count": len(changes), "changes": changes},
            )
            return
        if path == "/api/ai-prices/token":
            try:
                payload = self.server.radar.token_prices(
                    query=query.get("q", [""])[0] or None,
                    provider=query.get("provider", [""])[0] or None,
                    sort=query.get("sort", ["typical"])[0],
                    direction=query.get("direction", ["asc"])[0],
                    min_context=_optional_int(query, "min_context"),
                    max_input=_optional_float(query, "max_input"),
                    max_output=_optional_float(query, "max_output"),
                    max_typical=_optional_float(query, "max_typical"),
                    verification=query.get("verification", ["all"])[0],
                    cache=query.get("cache", ["any"])[0],
                    limit=int(query.get("limit", ["100"])[0]),
                    offset=int(query.get("offset", ["0"])[0]),
                )
            except (TypeError, ValueError):
                self._json(400, {"error": "invalid_token_price_filter"})
                return
            self._json(200, payload)
            return
        if path == "/api/ai-prices/gpu":
            try:
                payload = self.server.radar.gpu_prices(
                    query=query.get("q", [""])[0] or None,
                    provider=query.get("provider", [""])[0] or None,
                    gpu_model=query.get("gpu", [""])[0] or None,
                    sort=query.get("sort", ["hourly"])[0],
                    direction=query.get("direction", ["asc"])[0],
                    min_vram=_optional_float(query, "min_vram"),
                    max_hourly=_optional_float(query, "max_hourly"),
                    billing_mode=query.get("billing", [""])[0] or None,
                    market_tier=query.get("tier", [""])[0] or None,
                    price_mode=query.get("price_mode", ["all"])[0],
                    hours=float(query.get("hours", ["10"])[0]),
                    limit=int(query.get("limit", ["100"])[0]),
                    offset=int(query.get("offset", ["0"])[0]),
                )
            except (TypeError, ValueError):
                self._json(400, {"error": "invalid_gpu_price_filter"})
                return
            self._json(200, payload)
            return
        if path == "/api/ai-resources/refresh":
            self._json(200, self.server.radar.refresh_status())
            return
        if path == "/api/ai-resources/notifications/pending":
            self._json(
                200,
                {"notifications": self.server.radar.pending_notifications(limit=5)},
            )
            return
        if path == "/api/ai-daily/latest":
            self._json(
                200,
                {"schema_version": "1.0", "report": self.server.radar.poster_latest()},
            )
            return
        if path == "/api/ai-daily":
            try:
                reports = self.server.radar.poster_reports(
                    days=int(query.get("days", ["90"])[0])
                )
            except (TypeError, ValueError):
                self._json(400, {"error": "invalid_daily_report_filter"})
                return
            self._json(
                200,
                {"schema_version": "1.0", "count": len(reports), "reports": reports},
            )
            return
        if path == "/api/ai-daily/status":
            self._json(200, self.server.radar.poster_status())
            return
        parts = path.strip("/").split("/")
        if (
            len(parts) == 4
            and parts[:2] == ["api", "ai-daily"]
            and parts[3] == "image"
        ):
            image = self.server.radar.poster_image(parts[2])
            if image is None:
                self._json(404, {"error": "daily_poster_not_found"})
            else:
                self._image(image)
            return
        asset = _ASSETS.get(path)
        if asset is None:
            self._json(404, {"error": "not_found"})
            return
        filename, content_type = asset
        try:
            body = (_ASSET_ROOT / filename).read_bytes()
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
        if path.startswith("/api/"):
            schema_error = self.server.radar.schema_error()
            if schema_error is not None:
                self._json(503, schema_error)
                return
        if (
            path not in {
                "/api/ai-resources/refresh",
                "/api/ai-daily/generate",
                "/api/ai-tips/import",
                "/api/ai-tips/refresh",
            }
            and not path.startswith("/api/ai-resources/notifications/")
            and not path.startswith("/api/ai-tips/")
        ):
            self._json(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        max_length = 16384 if path.startswith("/api/ai-tips") else 4096
        if not 0 <= length <= max_length:
            self._json(413, {"error": "request_too_large"})
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "invalid_json"})
            return
        if path == "/api/ai-resources/refresh":
            force = payload.get("force", True) if isinstance(payload, dict) else True
            if not isinstance(force, bool):
                self._json(400, {"error": "invalid_ai_refresh_request"})
                return
            state = self.server.radar.start_refresh(force=force)
            if state is None:
                self._json(409, {"error": "ai_radar_refresh_already_running"})
            else:
                self._json(202, state)
            return
        if path == "/api/ai-daily/generate":
            force = payload.get("force", False) if isinstance(payload, dict) else False
            if not isinstance(force, bool):
                self._json(400, {"error": "invalid_daily_generate_request"})
                return
            state = self.server.radar.start_poster(force=force)
            if state is None:
                self._json(409, {"error": "daily_poster_already_running"})
            else:
                self._json(202, state)
            return
        if path == "/api/ai-tips/import":
            if not isinstance(payload, dict):
                self._json(400, {"error": "invalid_ai_tip_import"})
                return
            try:
                tip = self.server.radar.import_tip(payload)
            except (TypeError, ValueError):
                self._json(400, {"error": "invalid_ai_tip_import"})
                return
            self._json(201, tip)
            return
        if path == "/api/ai-tips/refresh":
            force = payload.get("force", False) if isinstance(payload, dict) else False
            if not isinstance(force, bool):
                self._json(400, {"error": "invalid_ai_tip_refresh"})
                return
            report = self.server.radar.refresh_tips(force=force)
            self._json(200, report)
            return
        tip_parts = path.strip("/").split("/")
        if (
            len(tip_parts) == 4
            and tip_parts[:2] == ["api", "ai-tips"]
            and tip_parts[3] == "review"
        ):
            if not isinstance(payload, dict):
                self._json(400, {"error": "invalid_ai_tip_review"})
                return
            try:
                tip = self.server.radar.review_tip(tip_parts[2], payload)
            except ValueError as exc:
                if str(exc) == "tip_not_found":
                    self._json(404, {"error": "tip_not_found"})
                else:
                    self._json(400, {"error": str(exc)})
                return
            self._json(200, tip)
            return
        if (
            len(tip_parts) == 5
            and tip_parts[:3] == ["api", "ai-tips", "applications"]
            and tip_parts[4] == "rollback"
        ):
            try:
                application = self.server.radar.rollback_tip(int(tip_parts[3]))
            except (TypeError, ValueError) as exc:
                code = str(exc) or "invalid_tip_application_id"
                self._json(400 if "not_found" not in code else 404, {"error": code})
                return
            self._json(200, application)
            return
        parts = path.strip("/").split("/")
        if (
            len(parts) == 5
            and parts[:3] == ["api", "ai-resources", "notifications"]
            and parts[4] in {"delivered", "read"}
        ):
            try:
                notification_id = int(parts[3])
            except ValueError:
                self._json(400, {"error": "invalid_notification_id"})
                return
            if not self.server.radar.mark_notification(
                notification_id, status=parts[4]
            ):
                self._json(404, {"error": "notification_not_found"})
            else:
                self._json(200, {"status": parts[4]})
            return
        self._json(404, {"error": "not_found"})


def _optional_float(query: dict[str, list[str]], key: str) -> float | None:
    value = query.get(key, [""])[0]
    return float(value) if value else None


def _optional_int(query: dict[str, list[str]], key: str) -> int | None:
    value = query.get(key, [""])[0]
    return int(value) if value else None


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
