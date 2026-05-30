"""OfficeLego web UI — local or public (with auth token)."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from functools import wraps
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

from main import _get_app_root
from web_backend import OfficeLegoWebBackend
from web_config import WebSettings, load_web_settings

STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"
CAPTURES_DIR = _get_app_root() / "captures"
DEFAULT_PORT = 5757

# WSGI entry for: waitress-serve --listen=0.0.0.0:5757 web_app:application
_application_backend: Optional[OfficeLegoWebBackend] = None
_application_settings: Optional[WebSettings] = None


def _get_token_from_request() -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.args.get("token", "").strip()


def create_app(
    backend: OfficeLegoWebBackend,
    settings: Optional[WebSettings] = None,
) -> Flask:
    settings = settings or load_web_settings()
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")

    def require_auth(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if settings.auth_token:
                if _get_token_from_request() != settings.auth_token:
                    return jsonify({"error": "Unauthorized", "login": "/login.html"}), 401
            return f(*args, **kwargs)

        return wrapped

    @app.get("/login.html")
    def login_page():
        return send_from_directory(STATIC_DIR, "login.html")

    @app.get("/api/meta")
    def api_meta():
        import platform

        return jsonify(
            {
                "name": "OfficeLego",
                "auth_required": settings.auth_required,
                "public_mode": settings.public_mode,
                "base_url": settings.base_url or None,
                "platform": sys.platform,
                "platform_detail": platform.platform(),
                "local_agent_required": True,
                "hint_zh": (
                    "录制与回放在本机执行；公网地址只是远程控制这台电脑上的 OfficeLego。"
                ),
            }
        )

    @app.get("/")
    @require_auth
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/api/status")
    @require_auth
    def api_status():
        return jsonify(backend.snapshot())

    @app.get("/api/permissions")
    @require_auth
    def api_permissions():
        return jsonify(backend.permissions())

    @app.post("/api/permissions/prompt")
    @require_auth
    def api_permissions_prompt():
        return jsonify(backend.prompt_permissions())

    @app.get("/api/flows")
    @require_auth
    def api_flows():
        return jsonify({"flows": backend.list_flows()})

    @app.get("/api/flows/<name>")
    @require_auth
    def api_flow_get(name: str):
        try:
            return jsonify(backend.load_flow(name))
        except FileNotFoundError:
            return jsonify({"error": "Flow not found"}), 404

    @app.post("/api/flows")
    @require_auth
    def api_flow_save():
        body = request.get_json(silent=True) or {}
        name = str(body.get("name", "")).strip()
        try:
            return jsonify(backend.save_flow(name))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.delete("/api/flows/<name>")
    @require_auth
    def api_flow_delete(name: str):
        if backend.delete_flow(name):
            return jsonify({"ok": True})
        return jsonify({"error": "Flow not found"}), 404

    @app.get("/api/modules")
    @require_auth
    def api_modules():
        return jsonify({"modules": backend.list_modules()})

    @app.put("/api/steps")
    @require_auth
    def api_steps_put():
        body = request.get_json(silent=True) or {}
        steps = body.get("steps")
        if not isinstance(steps, list):
            return jsonify({"error": "steps must be a list"}), 400
        backend.set_steps(steps)
        return jsonify(backend.snapshot())

    @app.post("/api/steps/type")
    @require_auth
    def api_steps_type():
        body = request.get_json(silent=True) or {}
        text = str(body.get("text", ""))
        index = body.get("index")
        if index is not None:
            index = int(index)
        backend.insert_type_step(text, index=index)
        return jsonify(backend.snapshot())

    @app.delete("/api/steps/<int:index>")
    @require_auth
    def api_steps_delete(index: int):
        backend.delete_step(index)
        return jsonify(backend.snapshot())

    @app.post("/api/options")
    @require_auth
    def api_options():
        body = request.get_json(silent=True) or {}
        backend.set_options(
            auto_correct=body.get("auto_correct"),
            playback_speed=body.get("playback_speed"),
            wait_load=body.get("wait_load"),
        )
        return jsonify(backend.snapshot())

    @app.post("/api/record/start")
    @require_auth
    def api_record_start():
        body = request.get_json(silent=True) or {}
        clear = body.get("clear", True)
        try:
            backend.start_recording(clear=bool(clear))
            return jsonify(backend.snapshot())
        except (PermissionError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/record/stop")
    @require_auth
    def api_record_stop():
        result = backend.stop_recording()
        snap = backend.snapshot()
        snap["fix_messages"] = result.get("fix_messages", [])
        return jsonify(snap)

    @app.post("/api/playback/start")
    @require_auth
    def api_playback_start():
        body = request.get_json(silent=True) or {}
        flow_name = body.get("flow_name")
        try:
            backend.start_playback(flow_name=flow_name)
            return jsonify(backend.snapshot())
        except (PermissionError, RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/playback/stop")
    @require_auth
    def api_playback_stop():
        backend.stop_playback()
        return jsonify(backend.snapshot())

    @app.get("/api/captures/<path:rel_path>")
    @require_auth
    def api_capture_file(rel_path: str):
        path = backend.capture_file_path(rel_path)
        if not path:
            return jsonify({"error": "Not found"}), 404
        return send_from_directory(path.parent, path.name)

    @app.get("/api/gaps")
    @require_auth
    def api_gaps():
        return jsonify(backend.get_gaps())

    @app.get("/api/steps/<int:index>")
    @require_auth
    def api_step_detail(index: int):
        try:
            return jsonify(backend.get_step_detail(index))
        except IndexError:
            return jsonify({"error": "Step not found"}), 404

    @app.put("/api/steps/<int:index>")
    @require_auth
    def api_steps_update(index: int):
        body = request.get_json(silent=True) or {}
        try:
            backend.update_step(index, body)
            return jsonify(backend.snapshot())
        except IndexError:
            return jsonify({"error": "Step not found"}), 404

    @app.post("/api/steps/move")
    @require_auth
    def api_step_move():
        body = request.get_json(silent=True) or {}
        try:
            backend.move_step(int(body["from"]), int(body["to"]))
            return jsonify(backend.snapshot())
        except (IndexError, KeyError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/steps/delete")
    @require_auth
    def api_steps_delete_batch():
        body = request.get_json(silent=True) or {}
        indices = body.get("indices") or []
        backend.delete_steps([int(i) for i in indices])
        return jsonify(backend.snapshot())

    @app.post("/api/steps/insert-module")
    @require_auth
    def api_insert_module():
        body = request.get_json(silent=True) or {}
        try:
            backend.insert_module(
                str(body.get("name", "")),
                int(body.get("at_index", 0)),
            )
            return jsonify(backend.snapshot())
        except (FileNotFoundError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/steps/insert-loop")
    @require_auth
    def api_insert_loop():
        body = request.get_json(silent=True) or {}
        try:
            backend.insert_loop(
                int(body.get("count", 10)),
                source=str(body.get("source", "selection")),
                module_name=str(body.get("module_name", "")),
                indices=body.get("indices"),
                remove_selected=bool(body.get("remove_selected", False)),
            )
            return jsonify(backend.snapshot())
        except (FileNotFoundError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/modules/save")
    @require_auth
    def api_save_module():
        body = request.get_json(silent=True) or {}
        try:
            result = backend.save_as_module(
                str(body.get("name", "")),
                [int(i) for i in body.get("indices") or []],
                expand_modules=bool(body.get("expand_modules", True)),
            )
            return jsonify({**backend.snapshot(), "module": result})
        except (ValueError, FileNotFoundError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/modules/<name>/steps")
    @require_auth
    def api_module_steps(name: str):
        try:
            steps = backend.load_module_steps(name)
            return jsonify({"name": name, "steps": steps})
        except FileNotFoundError:
            return jsonify({"error": "Module not found"}), 404

    @app.put("/api/modules/<name>")
    @require_auth
    def api_module_update(name: str):
        body = request.get_json(silent=True) or {}
        steps = body.get("steps")
        if not isinstance(steps, list):
            return jsonify({"error": "steps required"}), 400
        try:
            backend.save_module_file(name, steps)
            return jsonify({"ok": True})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/record/pause")
    @require_auth
    def api_record_pause():
        backend.pause_recording()
        return jsonify(backend.snapshot())

    @app.post("/api/record/resume")
    @require_auth
    def api_record_resume():
        backend.resume_recording()
        return jsonify(backend.snapshot())

    @app.post("/api/record/loop/wps")
    @require_auth
    def api_loop_wps():
        body = request.get_json(silent=True) or {}
        try:
            backend.loop_pick_wps(int(body.get("rows", 10)))
            return jsonify(backend.snapshot())
        except (RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/record/loop/pick/start")
    @require_auth
    def api_loop_pick_start():
        try:
            return jsonify(backend.start_range_pick())
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/record/loop/pick/status")
    @require_auth
    def api_loop_pick_status():
        return jsonify(backend.range_pick_status())

    @app.post("/api/record/loop/pick/confirm")
    @require_auth
    def api_loop_pick_confirm():
        body = request.get_json(silent=True) or {}
        try:
            if body.get("cancel"):
                return jsonify(backend.cancel_range_pick())
            status = backend.range_pick_status()
            rows = body.get("rows")
            if rows is None and status.get("rows"):
                rows = status["rows"]
            return jsonify(
                backend.confirm_range_pick(int(rows) if rows is not None else None)
            )
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/record/loop/pick/cancel")
    @require_auth
    def api_loop_pick_cancel():
        return jsonify(backend.cancel_range_pick())

    @app.post("/api/record/loop/done")
    @require_auth
    def api_loop_body_done():
        result = backend.loop_body_done()
        snap = backend.snapshot()
        snap["loop_warnings"] = result.get("warnings", [])
        return jsonify(snap)

    return app


def build_application(
    flows_dir: Path,
    modules_dir: Path,
    settings: Optional[WebSettings] = None,
) -> Flask:
    global _application_backend, _application_settings
    settings = settings or load_web_settings()
    _application_settings = settings
    _application_backend = OfficeLegoWebBackend(flows_dir, modules_dir, CAPTURES_DIR)
    return create_app(_application_backend, settings)


# waitress / gunicorn entry point
def _lazy_application() -> Flask:
    from main import FLOWS_DIR, MODULES_DIR, ensure_flows_dir

    ensure_flows_dir()
    return build_application(FLOWS_DIR, MODULES_DIR)


try:
    application = _lazy_application()
except Exception:
    application = None  # type: ignore[misc, assignment]


def run_web_app(
    flows_dir: Path,
    modules_dir: Path,
    *,
    settings: Optional[WebSettings] = None,
    open_browser: bool = True,
    use_waitress: bool = False,
) -> None:
    try:
        import flask  # noqa: F401
    except ImportError:
        print("Install Flask first: pip install flask", file=sys.stderr)
        raise SystemExit(1)

    settings = settings or load_web_settings()
    app = build_application(flows_dir, modules_dir, settings)

    scheme = "https" if settings.base_url.startswith("https") else "http"
    host_label = settings.base_url or f"{scheme}://{settings.host}:{settings.port}"
    if settings.host == "0.0.0.0":
        connect_host = "127.0.0.1"
    else:
        connect_host = settings.host
    local_url = f"http://{connect_host}:{settings.port}/"

    print(f"OfficeLego web UI: {local_url}")
    if settings.public_mode:
        print("Public mode: listening on all interfaces.")
        if settings.auth_token:
            print(f"Access token (share with visitors): {settings.auth_token}")
        print("See DEPLOY.md — use Cloudflare Tunnel for HTTPS on the internet.")
    print("Recording/playback run on THIS machine — grant Accessibility permissions.")

    if open_browser and settings.host in ("127.0.0.1", "localhost"):
        webbrowser.open(local_url)

    if use_waitress or settings.public_mode:
        try:
            from waitress import serve

            serve(app, host=settings.host, port=settings.port, threads=8)
            return
        except ImportError:
            if use_waitress:
                print("Install waitress: pip install waitress", file=sys.stderr)
                raise SystemExit(1)

    app.run(host=settings.host, port=settings.port, threaded=True, use_reloader=False)


def main() -> None:
    from main import FLOWS_DIR, MODULES_DIR, ensure_flows_dir

    parser = argparse.ArgumentParser(description="OfficeLego web UI")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--host", type=str, default=None)
    parser.add_argument("--public", action="store_true", help="Listen on 0.0.0.0")
    parser.add_argument("--token", type=str, default=None, help="API access token")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--waitress", action="store_true", help="Use waitress WSGI server")
    args = parser.parse_args()

    ensure_flows_dir()
    settings = load_web_settings(
        host=args.host,
        port=args.port,
        auth_token=args.token,
        public_mode=args.public if args.public else None,
    )
    run_web_app(
        FLOWS_DIR,
        MODULES_DIR,
        settings=settings,
        open_browser=not args.no_browser,
        use_waitress=args.waitress,
    )


if __name__ == "__main__":
    main()
