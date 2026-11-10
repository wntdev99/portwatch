"""PortWatch 의 GTK4 + libadwaita 화면 (Linux).

데이터 수집과 실제 동작은 portwatch.core 가 담당하고, 이 파일은 화면만 그린다.
"""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Gio, GLib, Gdk, GObject  # noqa: E402

import json
import os
import threading

from .core import actions
from .core.platform import run as run_cmd
from .core import config as config_mod
from .core.collect import collect, can_kill, RISKY_PORTS
from .core.probe import url_for

APP_ID = "dev.local.PortWatch"
REFRESH_SEC = 5
KILL_GRACE_SEC = 3


def load_config():
    return config_mod.load()


def save_config(cfg):
    config_mod.save(cfg)


# ---------------------------------------------------------------- 스타일

CSS = b"""
.port-pill {
  font-family: monospace;
  font-weight: 800;
  font-size: 1.05em;
  min-width: 58px;
  padding: 6px 2px;
  border-radius: 9px;
  background: alpha(currentColor, 0.10);
}
.port-http   { color: #3584e4; }
.port-https  { color: #2ec27e; }
.port-tcp    { color: #9a9996; }
.badge-http  { color: #3584e4; }
.badge-https { color: #2ec27e; }
.badge {
  font-size: 0.76em;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  background: alpha(currentColor, 0.14);
}
.badge-public { color: #e5a50a; }
.badge-docker { color: #3584e4; }
.row-sub { font-family: monospace; font-size: 0.84em; opacity: 0.72; }
.star-on { color: @warning_color; }
"""


# ---------------------------------------------------------------- 창

class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="PortWatch")
        self.set_default_size(960, 720)

        self.cfg = load_config()
        self.pinned = set(self.cfg.get("pinned", []))
        self.show_system = self.cfg.get("show_system", False)
        self.auto = self.cfg.get("auto_refresh", True)
        self.check_health = self.cfg.get("check_health", False)
        self.notify = self.cfg.get("notify_changes", True)
        # 즐겨찾기한 포트를 다시 띄우기 위해 명령과 작업 디렉터리를 기억한다.
        self.commands = self.cfg.get("commands", {})
        self.known = None
        self.rows = []
        self.query = ""
        self.signature = None
        self.timer = None

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toasts.set_child(root)

        # --- 헤더바
        header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle(title="PortWatch", subtitle="로컬 LISTEN 포트")
        header.set_title_widget(self.title_widget)

        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="새로고침 (Ctrl+R)")
        refresh.connect("clicked", lambda *_: self.reload())
        header.pack_start(refresh)

        self.search_btn = Gtk.ToggleButton(icon_name="system-search-symbolic",
                                           tooltip_text="검색 (Ctrl+F)")
        header.pack_end(self.search_btn)

        menu = Gio.Menu()
        tools = Gio.Menu()
        tools.append("포트 비우기…", "win.free-port")
        tools.append("외부 노출 점검…", "win.exposure")
        menu.append_section("도구", tools)
        view = Gio.Menu()
        view.append("시스템·관리 포트 표시", "win.show-system")
        view.append("자동 갱신 (5초)", "win.auto-refresh")
        view.append("HTTP 상태 점검", "win.check-health")
        view.append("포트 변화 알리기", "win.notify-changes")
        menu.append_section("보기", view)
        other = Gio.Menu()
        other.append("키보드 단축키", "win.shortcuts")
        other.append("PortWatch 정보", "win.about")
        menu.append_section(None, other)
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                  tooltip_text="메뉴")
        header.pack_end(menu_btn)
        root.append(header)

        # --- 검색 바
        self.search_entry = Gtk.SearchEntry(placeholder_text="포트, 이름, 명령줄로 검색")
        self.search_entry.connect("search-changed", self.on_search)
        self.search_bar = Gtk.SearchBar(child=self.search_entry)
        self.search_bar.set_key_capture_widget(self)
        self.search_btn.bind_property(
            "active", self.search_bar, "search-mode-enabled",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        root.append(self.search_bar)

        # --- 본문
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               vexpand=True)
        self.page = Adw.PreferencesPage()
        scroller = Gtk.ScrolledWindow(child=self.page, vexpand=True)
        self.stack.add_named(scroller, "list")

        self.empty = Adw.StatusPage(icon_name="system-search-symbolic",
                                    title="결과 없음",
                                    description="검색어와 일치하는 포트가 없습니다.")
        self.stack.add_named(self.empty, "empty")

        self.loading = Adw.StatusPage(title="포트를 살펴보는 중…")
        spinner = Gtk.Spinner(spinning=True, width_request=36, height_request=36)
        self.loading.set_child(spinner)
        self.stack.add_named(self.loading, "loading")
        self.stack.set_visible_child_name("loading")
        root.append(self.stack)

        # --- 액션과 단축키
        self.add_toggle_action("show-system", self.show_system, self.on_show_system)
        self.add_toggle_action("auto-refresh", self.auto, self.on_auto)
        self.add_toggle_action("check-health", self.check_health, self.on_check_health)
        self.add_toggle_action("notify-changes", self.notify, self.on_notify)
        self.add_simple_action("free-port", self.on_free_port)
        self.add_simple_action("exposure", self.on_exposure)
        self.add_simple_action("shortcuts", self.on_shortcuts)
        self.add_simple_action("about", self.on_about)

        app.set_accels_for_action("win.refresh", ["<Control>r"])
        self.add_simple_action("refresh", lambda *_: self.reload())
        app.set_accels_for_action("win.find", ["<Control>f"])
        self.add_simple_action("find", lambda *_: self.search_btn.set_active(True))

        self.reload()
        self.sync_timer()

    # ---------- 액션 도우미
    def add_simple_action(self, name, callback):
        act = Gio.SimpleAction.new(name, None)
        act.connect("activate", callback)
        self.add_action(act)

    def add_toggle_action(self, name, state, callback):
        act = Gio.SimpleAction.new_stateful(name, None, GLib.Variant.new_boolean(state))
        act.connect("change-state", callback)
        self.add_action(act)

    # ---------- 갱신 주기
    def sync_timer(self):
        if self.auto and self.timer is None:
            self.timer = GLib.timeout_add_seconds(REFRESH_SEC, self.on_tick)
        elif not self.auto and self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None

    def on_tick(self):
        self.reload()
        return True

    def on_auto(self, action, value):
        action.set_state(value)
        self.auto = value.get_boolean()
        self.cfg["auto_refresh"] = self.auto
        save_config(self.cfg)
        self.sync_timer()

    def on_show_system(self, action, value):
        action.set_state(value)
        self.show_system = value.get_boolean()
        self.cfg["show_system"] = self.show_system
        save_config(self.cfg)
        self.render()

    def on_check_health(self, action, value):
        action.set_state(value)
        self.check_health = value.get_boolean()
        self.cfg["check_health"] = self.check_health
        save_config(self.cfg)
        self.force_reload()

    def on_notify(self, action, value):
        action.set_state(value)
        self.notify = value.get_boolean()
        self.cfg["notify_changes"] = self.notify
        save_config(self.cfg)

    def on_search(self, entry):
        self.query = entry.get_text().strip().lower()
        self.render()

    # ---------- 데이터
    def reload(self):
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        rows = collect(self.check_health)
        GLib.idle_add(self._apply, rows)

    def _apply(self, rows):
        self.detect_changes(rows)
        self.rows = rows
        self.render()
        return False

    def detect_changes(self, rows):
        """갱신 사이에 열리거나 닫힌 포트를 찾아 알린다."""
        current = {r["port"]: r for r in rows}
        if self.known is None:          # 첫 수집은 기준점일 뿐이므로 알리지 않는다
            self.known = current
            return
        opened = [p for p in current if p not in self.known]
        closed = [p for p in self.known if p not in current]
        self.known = current
        if not self.notify or not (opened or closed):
            return

        parts = []
        if opened:
            names = ", ".join(str(p) for p in sorted(opened)[:3])
            more = f" 외 {len(opened) - 3}개" if len(opened) > 3 else ""
            parts.append(f"{names}{more} 열림")
        if closed:
            names = ", ".join(str(p) for p in sorted(closed)[:3])
            more = f" 외 {len(closed) - 3}개" if len(closed) > 3 else ""
            parts.append(f"{names}{more} 닫힘")
        text = " · ".join(parts)
        self.toast(f"포트 {text}")
        if not self.is_active():
            note = Gio.Notification.new("PortWatch")
            note.set_body(f"포트 {text}")
            self.get_application().send_notification("portwatch-change", note)

    # ---------- 화면 구성
    def visible_rows(self):
        out = []
        for row in self.rows:
            if row["section"] == "system" and not self.show_system:
                continue
            if self.query:
                haystack = " ".join([
                    str(row["port"]), row["title"], row["name"], row["cmdline"],
                    row["cwd"], row["addrs"],
                ]).lower()
                if self.query not in haystack:
                    continue
            out.append(row)
        return out

    def render(self):
        rows = self.visible_rows()
        signature = json.dumps(
            [[[r["port"], r["pid"], r["kind"], r["section"], r["title"],
               r.get("health"), r["port"] in self.pinned] for r in rows],
             [p for p, _ in self.offline_favourites(rows)]], sort_keys=True)
        counts = (len([r for r in self.rows if r["section"] == "mine"]),
                  len([r for r in self.rows if r["section"] == "docker"]),
                  len(self.rows))
        self.title_widget.set_subtitle(
            f"내 서버 {counts[0]} · Docker {counts[1]} · 전체 {counts[2]}")

        if signature == self.signature:
            return
        self.signature = signature

        child = self.page.get_first_child()
        while child is not None:
            self.page.remove(child) if isinstance(child, Adw.PreferencesGroup) else None
            child = self.page.get_first_child() if isinstance(child, Adw.PreferencesGroup) else None
        # PreferencesPage는 내부 컨테이너를 쓰므로 안전하게 새로 만든다.
        new_page = Adw.PreferencesPage()
        scroller = self.stack.get_child_by_name("list")
        scroller.set_child(new_page)
        self.page = new_page

        if not rows:
            self.stack.set_visible_child_name("empty")
            self.empty.set_title("표시할 포트가 없습니다" if not self.query else "결과 없음")
            self.empty.set_description(
                "검색어와 일치하는 포트가 없습니다." if self.query else
                "메뉴에서 '시스템·관리 포트 표시'를 켜 보세요.")
            return
        self.stack.set_visible_child_name("list")

        sections = [
            ("pinned", "즐겨찾기", "자주 여는 포트입니다."),
            ("mine", "내 서버", "직접 띄운 프로세스입니다."),
            ("docker", "Docker 컨테이너", "컨테이너 안에서 도는 서비스입니다."),
            ("system", "시스템·관리 도구", "OS와 IT 관리 도구가 쓰는 포트입니다."),
        ]
        buckets = {key: [] for key, _, _ in sections}
        for row in rows:
            bucket = "pinned" if row["port"] in self.pinned else row["section"]
            buckets[bucket].append(row)

        for key, title, subtitle in sections:
            items = buckets[key]
            if not items:
                continue
            group = Adw.PreferencesGroup(title=f"{title}  ({len(items)})",
                                         description=subtitle)
            for row in items:
                group.add(self.build_row(row))
            self.page.add(group)

        offline = self.offline_favourites(rows)
        if offline:
            group = Adw.PreferencesGroup(
                title=f"꺼진 즐겨찾기  ({len(offline)})",
                description="즐겨찾기에 넣어 둔 포트인데 지금은 떠 있지 않습니다.")
            for port, saved in offline:
                group.add(self.build_offline_row(port, saved))
            self.page.add(group)

    def build_row(self, row):
        web = row["kind"] in ("http", "https")
        action_row = Adw.ActionRow(
            title=GLib.markup_escape_text(row["title"]),
            subtitle=GLib.markup_escape_text(self.subtitle_for(row)),
            activatable=web,
        )
        action_row.set_subtitle_lines(2)
        if web:
            action_row.connect("activated", lambda *_: self.open_row(row))
            action_row.set_tooltip_text(f"클릭하면 {url_for(row)} 를 엽니다")
        else:
            action_row.set_tooltip_text("웹 서버가 아니므로 브라우저로 열 수 없습니다")

        pill = Gtk.Label(label=str(row["port"]), valign=Gtk.Align.CENTER)
        pill.add_css_class("port-pill")
        pill.add_css_class({"http": "port-http", "https": "port-https"}.get(row["kind"], "port-tcp"))
        action_row.add_prefix(pill)

        badges = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        health = row.get("health")
        if health:
            code, ms = health
            css = "badge-https" if code < 400 else "badge-public"
            chip = self.badge(f"{code} · {ms}ms", css)
            chip.set_tooltip_text("GET / 에 대한 응답 코드와 왕복 시간입니다")
            badges.append(chip)
        elif row["kind"] != "tcp":
            badges.append(self.badge(row["kind"].upper(), f"badge-{row['kind']}"))
        if row["docker"]:
            badges.append(self.badge("Docker", "badge-docker"))
        if row["public"]:
            badge = self.badge("외부 공개", "badge-public")
            badge.set_tooltip_text(f"{row['addrs']} 에 바인딩되어 같은 네트워크의 다른 장비에서 접근됩니다")
            badges.append(badge)
        action_row.add_suffix(badges)

        star = Gtk.Button(icon_name="starred-symbolic" if row["port"] in self.pinned
                          else "non-starred-symbolic",
                          valign=Gtk.Align.CENTER, has_frame=False,
                          tooltip_text="즐겨찾기")
        if row["port"] in self.pinned:
            star.add_css_class("star-on")
        star.connect("clicked", lambda *_: self.toggle_pin(row))
        action_row.add_suffix(star)

        if web:
            open_btn = Gtk.Button(icon_name="web-browser-symbolic",
                                  valign=Gtk.Align.CENTER, has_frame=False,
                                  tooltip_text="브라우저로 열기")
            open_btn.connect("clicked", lambda *_: self.open_row(row))
            action_row.add_suffix(open_btn)

        menu = Gio.Menu()
        if web:
            menu.append("브라우저로 열기", f"win.open-{row['port']}")
            menu.append("URL 복사", f"win.copy-url-{row['port']}")
        menu.append("명령줄 복사", f"win.copy-cmd-{row['port']}")
        if row["cwd"]:
            menu.append("작업 디렉터리 열기", f"win.open-dir-{row['port']}")
            menu.append("터미널에서 열기", f"win.open-term-{row['port']}")

        # 프로세스를 멈추는 항목은 되돌릴 수 없으므로 별도 구역에 둔다.
        stop = Gio.Menu()
        if row["docker"] and row.get("container"):
            stop.append("컨테이너 중지 명령 복사", f"win.docker-stop-{row['port']}")
        elif self.can_kill(row):
            stop.append("프로세스 종료", f"win.kill-{row['port']}")
        if stop.get_n_items():
            menu.append_section(None, stop)

        self.register_row_actions(row, web)
        more = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu,
                              valign=Gtk.Align.CENTER, has_frame=False,
                              tooltip_text="더 보기")
        action_row.add_suffix(more)
        return action_row

    def register_row_actions(self, row, web):
        port = row["port"]
        defs = [
            (f"copy-cmd-{port}", lambda *_: self.copy(row["cmdline"] or "-", "명령줄을 복사했습니다")),
            # 포트로 최신 행을 다시 찾는다. 등록 시점의 PID를 그대로 쓰면
            # 그 사이에 다른 프로세스가 포트를 넘겨받았을 때 엉뚱한 쪽을 죽이게 된다.
            (f"kill-{port}", lambda *_: self.confirm_kill(port)),
            (f"docker-stop-{port}", lambda *_: self.copy_docker_stop(port)),
        ]
        if web:
            defs += [
                (f"open-{port}", lambda *_: self.open_row(row)),
                (f"copy-url-{port}", lambda *_: self.copy(url_for(row), "URL을 복사했습니다")),
            ]
        if row["cwd"]:
            defs.append((f"open-dir-{port}", lambda *_: self.open_path(row["cwd"])))
            defs.append((f"open-term-{port}", lambda *_: self.open_terminal(row["cwd"])))
        for name, callback in defs:
            if self.lookup_action(name) is None:
                self.add_simple_action(name, callback)

    @staticmethod
    def badge(text, css):
        label = Gtk.Label(label=text, valign=Gtk.Align.CENTER)
        label.add_css_class("badge")
        if css != "badge":
            label.add_css_class(css)
        return label

    @staticmethod
    def subtitle_for(row):
        bits = []
        if row["restricted"]:
            bits.append("root 소유 · 프로세스 정보 없음")
        else:
            if row["cmdline"]:
                bits.append(row["cmdline"][:150])
            if row["uptime"]:
                bits.append(f"가동 {row['uptime']}")
        bits.append(row["addrs"])
        return "   ·   ".join(bits)

    # ---------- 꺼진 즐겨찾기 다시 띄우기
    def offline_favourites(self, rows):
        """즐겨찾기에 있지만 지금은 LISTEN 하지 않는 포트와 기억해 둔 실행 방법."""
        if self.query or os.environ.get("PORTWATCH_DEMO"):
            return []
        live = {r["port"] for r in rows}
        out = []
        for port in sorted(self.pinned):
            saved = self.commands.get(str(port))
            if port not in live and saved:
                out.append((port, saved))
        return out

    def build_offline_row(self, port, saved):
        row = Adw.ActionRow(
            title=GLib.markup_escape_text(saved["title"]),
            subtitle=GLib.markup_escape_text(
                f"{saved['cmdline'][:120]}   ·   {saved['cwd']}"))
        row.set_subtitle_lines(2)

        pill = Gtk.Label(label=str(port), valign=Gtk.Align.CENTER)
        pill.add_css_class("port-pill")
        pill.add_css_class("port-tcp")
        row.add_prefix(pill)
        row.add_suffix(self.badge("꺼짐", "badge"))

        start = Gtk.Button(icon_name="media-playback-start-symbolic",
                           valign=Gtk.Align.CENTER, has_frame=False,
                           tooltip_text="기억해 둔 명령으로 다시 실행")
        start.connect("clicked", lambda *_: self.confirm_restart(port, saved))
        row.add_suffix(start)

        forget = Gtk.Button(icon_name="user-trash-symbolic",
                            valign=Gtk.Align.CENTER, has_frame=False,
                            tooltip_text="기억해 둔 명령 지우기")
        forget.connect("clicked", lambda *_: self.forget_command(port))
        row.add_suffix(forget)
        return row

    def confirm_restart(self, port, saved):
        dialog = Adw.MessageDialog(
            transient_for=self, modal=True,
            heading=f"{saved['title']} 을(를) 다시 띄울까요?",
            body=f"{saved['cmdline']}\n\n작업 디렉터리: {saved['cwd']}\n\n"
                 f"터미널에서 직접 실행할 때와 환경 변수가 다를 수 있습니다.")
        dialog.add_response("cancel", "취소")
        dialog.add_response("run", "실행")
        dialog.set_response_appearance("run", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("run")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda d, r: r == "run" and self.restart(port, saved))
        dialog.present()

    def restart(self, port, saved):
        ok, message = actions.restart(saved)
        self.toast(message)
        if ok:
            GLib.timeout_add_seconds(2, self.force_reload)

    def forget_command(self, port):
        self.commands.pop(str(port), None)
        self.cfg["commands"] = self.commands
        save_config(self.cfg)
        self.toast("기억해 둔 실행 명령을 지웠습니다")
        self.force_reload()

    # ---------- 도구: 포트 비우기 · 외부 노출 점검
    def on_free_port(self, *_):
        """'Address already in use' 를 푸는 화면. 포트를 입력하면 주인을 찾아 준다."""
        entry = Gtk.Entry(placeholder_text="예: 8080", activates_default=True,
                          input_purpose=Gtk.InputPurpose.DIGITS, margin_top=8)
        dialog = Adw.MessageDialog(
            transient_for=self, modal=True,
            heading="포트 비우기",
            body="쓰려는 포트 번호를 입력하면 그 포트를 쥐고 있는 프로세스를 찾습니다.")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "취소")
        dialog.add_response("find", "찾기")
        dialog.set_response_appearance("find", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("find")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda d, r: r == "find" and self.find_owner(entry.get_text()))
        dialog.present()
        entry.grab_focus()

    def find_owner(self, text):
        try:
            port = int(text.strip())
        except ValueError:
            self.toast("포트 번호를 숫자로 입력해 주세요")
            return
        row = self.row_by_port(port)
        if row is None:
            self.toast(f"{port} 번은 비어 있습니다 — 바로 쓰실 수 있습니다")
            return
        if self.can_kill(row):
            self.confirm_kill(port)
            return

        if row["docker"] and row.get("container"):
            advice = f"Docker 컨테이너 {row['container']} 가 쓰고 있습니다.\n" \
                     f"docker stop {row['container']} 로 내릴 수 있습니다."
        elif row["restricted"]:
            advice = "다른 사용자(root)가 쓰고 있어 이 앱에서는 종료할 수 없습니다.\n" \
                     f"터미널에서 sudo ss -ltnp 'sport = :{port}' 로 확인해 보세요."
        else:
            advice = "이 프로세스는 종료 대상이 아닙니다."
        dialog = Adw.MessageDialog(
            transient_for=self, modal=True,
            heading=f"{port} 번은 {row['title']} 이(가) 쓰고 있습니다", body=advice)
        dialog.add_response("ok", "알겠습니다")
        dialog.present()

    def on_exposure(self, *_):
        """0.0.0.0 에 열린 포트를 모아 보여주고 위험한 조합을 짚는다."""
        public = [r for r in self.rows if r["public"]]
        if not public:
            dialog = Adw.MessageDialog(
                transient_for=self, modal=True, heading="외부에 열린 포트가 없습니다",
                body="모든 포트가 127.0.0.1 에만 묶여 있습니다.")
            dialog.add_response("ok", "닫기")
            dialog.present()
            return

        risky, normal = [], []
        for row in sorted(public, key=lambda r: r["port"]):
            label = f"{row['port']}  {row['title']}  ({row['addrs']})"
            service = RISKY_PORTS.get(row["port"])
            (risky if service else normal).append(
                f"{label}  ← {service}" if service else label)

        body = ""
        if risky:
            body += ("아래 포트는 인증 없이 열려 있으면 특히 위험합니다.\n\n"
                     + "\n".join(risky) + "\n\n")
        if normal:
            body += "그 밖에 외부에서 접근 가능한 포트입니다.\n\n" + "\n".join(normal)
        body += ("\n\n같은 네트워크의 다른 장비에서 접근할 수 있습니다. "
                 "개발용이라면 127.0.0.1 에만 묶는 편이 안전합니다.")

        dialog = Adw.MessageDialog(
            transient_for=self, modal=True,
            heading=f"외부에 열린 포트 {len(public)}개", body=body)
        dialog.add_response("copy", "목록 복사")
        dialog.add_response("ok", "닫기")
        dialog.set_default_response("ok")
        dialog.connect("response", lambda d, r: r == "copy" and self.copy(
            "\n".join(risky + normal), "노출 포트 목록을 복사했습니다"))
        dialog.present()

    # ---------- 프로세스 종료
    can_kill = staticmethod(can_kill)

    def row_by_port(self, port):
        for row in self.rows:
            if row["port"] == port:
                return row
        return None

    def copy_docker_stop(self, port):
        row = self.row_by_port(port)
        if not row or not row.get("container"):
            self.toast("컨테이너 이름을 찾지 못했습니다")
            return
        self.copy(f"docker stop {row['container']}",
                  f"docker stop {row['container']} 를 복사했습니다")

    def confirm_kill(self, port):
        row = self.row_by_port(port)
        if row is None:
            self.toast("이미 사라진 포트입니다")
            self.reload()
            return
        if not self.can_kill(row):
            self.toast("이 프로세스는 종료할 수 없습니다")
            return

        body = f"PID {row['pid']} · 포트 {row['port']}"
        if row["cmdline"]:
            body += f"\n{row['cmdline'][:160]}"
        if row["uptime"]:
            body += f"\n가동 {row['uptime']}"
        body += "\n\n저장하지 않은 작업이 있다면 사라질 수 있습니다."

        dialog = Adw.MessageDialog(
            transient_for=self, modal=True,
            heading=f"{row['title']} 을(를) 종료할까요?", body=body)
        dialog.add_response("cancel", "취소")
        dialog.add_response("kill", "종료")
        dialog.set_response_appearance("kill", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self.on_kill_response, row)
        dialog.present()

    def on_kill_response(self, dialog, response, row):
        if response != "kill":
            return
        self.send_signal(row, "term", "종료 신호를 보냈습니다")

    def send_signal(self, row, sig, message):
        pid, title = row["pid"], row["title"]
        if os.environ.get("PORTWATCH_DEMO"):
            self.toast(f"데모 모드입니다 — 실제라면 {title} (PID {pid}) 에 "
                       f"{'강제 종료' if sig == 'kill' else '종료'} 신호를 보냅니다")
            return
        ok, detail = (actions.force_kill(pid) if sig == "kill" else actions.terminate(pid))
        if not ok:
            self.toast(f"{title}: {detail}")
            self.force_reload()
            return
        self.toast(f"{title} 에 {message}")
        if sig == "term":
            GLib.timeout_add_seconds(KILL_GRACE_SEC, self.after_grace, row)
        else:
            GLib.timeout_add_seconds(1, self.force_reload)

    def after_grace(self, row):
        """SIGTERM을 보내고 기다린 뒤에도 살아 있으면 강제 종료를 묻는다."""
        pid, title = row["pid"], row["title"]
        if not actions.is_alive(pid):
            self.toast(f"{title} 이(가) 종료되었습니다")
            self.force_reload()
            return False

        dialog = Adw.MessageDialog(
            transient_for=self, modal=True,
            heading="아직 종료되지 않았습니다",
            body=f"{title} (PID {pid}) 이(가) {KILL_GRACE_SEC}초가 지나도록 "
                 f"종료 신호에 응답하지 않습니다.\n\n"
                 f"강제로 종료하면(SIGKILL) 프로세스는 정리할 기회를 갖지 못합니다.")
        dialog.add_response("wait", "더 기다리기")
        dialog.add_response("force", "강제 종료")
        dialog.set_response_appearance("force", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("wait")
        dialog.set_close_response("wait")
        dialog.connect(
            "response",
            lambda d, r: r == "force" and self.send_signal(
                row, "kill", "강제 종료 신호를 보냈습니다"))
        dialog.present()
        return False

    def force_reload(self):
        self.signature = None
        self.reload()
        return False

    # ---------- 동작
    def open_row(self, row):
        # 데모 데이터의 포트는 실제로 존재하지 않으므로 브라우저를 띄우지 않는다.
        if not os.environ.get("PORTWATCH_DEMO"):
            actions.open_url(url_for(row))
        self.toast(f"{row['title']} 을(를) 브라우저에서 열었습니다 — {url_for(row)}")

    def open_terminal(self, path):
        if not actions.open_terminal(path):
            self.toast("터미널을 열지 못했습니다")

    def open_path(self, path):
        if not actions.open_dir(path):
            self.toast("작업 디렉터리가 더 이상 없습니다")

    def copy(self, text, message):
        self.get_clipboard().set(text)
        self.toast(message)

    def toggle_pin(self, row):
        port = row["port"]
        self.pinned.symmetric_difference_update({port})
        self.cfg["pinned"] = sorted(self.pinned)
        if port in self.pinned and row["cmdline"] and row["cwd"] and not row["docker"]:
            # 나중에 다시 띄울 수 있도록 실행 방법을 함께 적어 둔다.
            self.commands[str(port)] = {
                "title": row["title"], "cmdline": row["cmdline"], "cwd": row["cwd"]}
            self.cfg["commands"] = self.commands
        save_config(self.cfg)
        self.signature = None
        self.render()

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=2))

    def on_shortcuts(self, *_):
        dialog = Adw.MessageDialog(
            transient_for=self, heading="키보드 단축키",
            body="Ctrl + R        새로고침\n"
                 "Ctrl + F        검색\n"
                 "Esc             검색 닫기\n"
                 "Enter           선택한 서버를 브라우저로 열기\n"
                 "Ctrl + W        창 닫기")
        dialog.add_response("ok", "닫기")
        dialog.present()

    def on_about(self, *_):
        about = Adw.AboutWindow(
            transient_for=self, application_name="PortWatch",
            application_icon="network-server", version="2.0",
            comments="로컬에서 LISTEN 중인 TCP 포트를 모아 보여주고, "
                     "웹 서버는 클릭 한 번으로 브라우저에서 엽니다.",
            developer_name="로컬 도구")
        about.present()


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.set_accels_for_action("window.close", ["<Control>w"])

    def do_startup(self):
        Adw.Application.do_startup(self)
        scheme = os.environ.get("PORTWATCH_COLOR_SCHEME") or run_cmd(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"]).strip()
        manager = Adw.StyleManager.get_default()
        if "prefer-dark" in scheme:
            manager.set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        elif "prefer-light" in scheme:
            manager.set_color_scheme(Adw.ColorScheme.PREFER_LIGHT)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        win = self.props.active_window or Window(self)
        win.present()


def main():
    return App().run(None)


if __name__ == "__main__":
    raise SystemExit(main())
