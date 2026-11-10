"""로컬 전용 웹 UI. 브라우저가 화면이 되므로 macOS 와 Windows 에서도 그대로 돈다.

안전장치:
  - 127.0.0.1 에만 바인딩한다.
  - 실행할 때마다 토큰을 만들고 모든 API 호출에 요구한다.
  - Origin 과 Host 헤더를 검사해 다른 사이트가 이 API 를 부르지 못하게 한다.
"""
import json
import os
import posixpath
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..core import actions
from ..core import config as config_mod
from ..core import platform as plat
from ..core.collect import collect, CURRENT_USER, RISKY_PORTS

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
TOKEN = secrets.token_urlsafe(24)

_state_lock = threading.Lock()
_cache = {"rows": [], "known": None}


def _rows(check_health):
    with _state_lock:
        rows = collect(check_health)
        previous = _cache["known"]
        current = {r["port"]: r["title"] for r in rows}
        changes = {"opened": [], "closed": []}
        if previous is not None:
            changes["opened"] = sorted(p for p in current if p not in previous)
            changes["closed"] = sorted(p for p in previous if p not in current)
        _cache["known"] = current
        _cache["rows"] = rows
        return rows, changes


def _row_by_port(port):
    for row in _cache["rows"]:
        if row["port"] == port:
            return row
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "PortWatch"

    def log_message(self, *_):
        pass                                   # 콘솔을 조용하게 둔다

    # ---------- 공통
    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "[::1]", "::1"):
            return False                       # DNS 리바인딩 차단
        origin = self.headers.get("Origin")
        if origin and not origin.startswith(("http://127.0.0.1:", "http://localhost:")):
            return False                       # 다른 사이트에서 온 호출 차단
        token = self.headers.get("X-PortWatch-Token") or ""
        return secrets.compare_digest(token, TOKEN)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    # ---------- GET
    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            if not self._authorised():
                self._json({"error": "unauthorised"}, 403)
                return
            if path == "/api/state":
                health = "health=1" in self.path
                rows, changes = _rows(health)
                self._json({"rows": rows, "changes": changes,
                            "config": config_mod.load(),
                            "user": CURRENT_USER,
                            "platform": ("windows" if plat.IS_WINDOWS
                                         else "mac" if plat.IS_MAC else "linux")})
                return
            if path == "/api/exposure":
                public = [r for r in _cache["rows"] if r["public"]]
                self._json({"rows": [
                    {**r, "risky": RISKY_PORTS.get(r["port"])} for r in public]})
                return
            self._json({"error": "not found"}, 404)
            return

        if path == "/":
            path = "/index.html"
        safe = posixpath.normpath(path).lstrip("/")
        full = os.path.join(STATIC, safe)
        if not os.path.abspath(full).startswith(STATIC) or not os.path.isfile(full):
            self.send_error(404)
            return
        ctype = {"html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8",
                 "css": "text/css; charset=utf-8"}.get(safe.rsplit(".", 1)[-1],
                                                       "application/octet-stream")
        data = open(full, "rb").read()
        if safe == "index.html":
            data = data.replace(b"__TOKEN__", TOKEN.encode())
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---------- POST
    def do_POST(self):
        if not self._authorised():
            self._json({"error": "unauthorised"}, 403)
            return
        path = self.path.split("?")[0]
        body = self._body()
        port = body.get("port")
        row = _row_by_port(port) if port is not None else None

        if path == "/api/config":
            cfg = config_mod.load()
            cfg.update(body.get("config") or {})
            config_mod.save(cfg)
            self._json({"ok": True, "config": cfg})
            return

        if path == "/api/kill":
            if row is None:
                self._json({"ok": False, "message": "이미 사라진 포트입니다"})
                return
            if not row["can_kill"]:
                self._json({"ok": False, "message": "이 프로세스는 종료할 수 없습니다"})
                return
            ok, message = actions.terminate(row["pid"])
            self._json({"ok": ok, "message": message, "pid": row["pid"]})
            return

        if path == "/api/alive":
            self._json({"alive": actions.is_alive(body.get("pid", 0))})
            return

        if path == "/api/force-kill":
            ok, message = actions.force_kill(body.get("pid", 0))
            self._json({"ok": ok, "message": message})
            return

        if path == "/api/restart":
            cfg = config_mod.load()
            saved = (cfg.get("commands") or {}).get(str(port))
            if not saved:
                self._json({"ok": False, "message": "기억해 둔 실행 명령이 없습니다"})
                return
            ok, message = actions.restart(saved)
            self._json({"ok": ok, "message": message})
            return

        if path in ("/api/open-dir", "/api/open-terminal"):
            if row is None or not row["cwd"]:
                self._json({"ok": False, "message": "작업 디렉터리를 알 수 없습니다"})
                return
            fn = actions.open_dir if path.endswith("dir") else actions.open_terminal
            ok = fn(row["cwd"])
            self._json({"ok": ok,
                        "message": "열었습니다" if ok else "열지 못했습니다"})
            return

        self._json({"error": "not found"}, 404)


def serve(port=7878, open_browser=True):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{httpd.server_port}/?t={TOKEN}"
    print(f"PortWatch 웹 UI: {url}")
    print("종료하려면 Ctrl+C 를 누르세요.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        httpd.server_close()
