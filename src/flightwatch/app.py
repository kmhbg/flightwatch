"""`flightwatch app`: the desktop app for Windows and macOS (also runs on Linux).

One long-running process instead of systemd units:
- the web server (web.py) in a thread, shown in a native window (pywebview: WebView2 / WKWebView);
- an icon in the system tray / menu bar (pystray) with the default trip's price, Open, Search now, Quit;
- a scheduler that starts `flightwatch run` at general.search_times and catches up once after sleep;
- notifications for new alerts (Linux: the search process sends them itself with notify-send).
Closing the window hides it; the app keeps watching from the tray until Quit.
"""
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from importlib.resources import files

import httpx

from . import config, i18n, system
from .i18n import money, t
from .runner import read_status

PORT = int(os.environ.get("FLIGHTWATCH_PORT", 8765))
URL = f"http://127.0.0.1:{PORT}/"
SCHEDULE = config.STATE_DIR / "schedule.json"
NOTIFIED = config.STATE_DIR / "notified.json"
CATCH_UP = timedelta(hours=12)  # a slot missed while asleep/off is run once if it is at most this old


def icon_path():
    return str(files("flightwatch").joinpath("assets", "icon.png"))


# --- scheduler -------------------------------------------------------------------------------

def _slots(times, now):
    """Scheduled datetimes for yesterday and today, oldest first."""
    out = []
    for d in (now.date() - timedelta(days=1), now.date()):
        for x in times:
            h, m = (int(p) for p in str(x).split(":"))
            out.append(datetime.combine(d, datetime.min.time()).replace(hour=h, minute=m))
    return sorted(out)


def due_slot(times, now, last_done):
    """The slot to run now, or None. `last_done` is the last slot already handled (datetime or None)."""
    past = [s for s in _slots(times, now) if s <= now]
    if not past:
        return None
    latest = past[-1]
    if last_done and last_done >= latest:
        return None
    return latest if now - latest <= CATCH_UP else None


def _load_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def scheduler_tick(now=None):
    """Start a full search when a search time has passed. Called every 30 s; returns True if started."""
    now = now or datetime.now()
    times = config.load()["general"]["search_times"]
    state = _load_json(SCHEDULE, {})
    last = datetime.fromisoformat(state["last_slot"]) if state.get("last_slot") else None
    if last is None:  # first start: don't search right away, wait for the next slot
        past = [s for s in _slots(times, now) if s <= now]
        _save_json(SCHEDULE, {"last_slot": (past[-1] if past else now).isoformat()})
        return False
    slot = due_slot(times, now, last)
    if slot is None:
        newest = [s for s in _slots(times, now) if s <= now]
        if newest and newest[-1] > last:  # too old to catch up: just mark it handled
            _save_json(SCHEDULE, {"last_slot": newest[-1].isoformat()})
        return False
    _save_json(SCHEDULE, {"last_slot": slot.isoformat()})
    if config.load()["watch"]:
        system.spawn_bg("run")
        return True
    return False


# --- notifications ---------------------------------------------------------------------------

def make_notifier(tray):
    """send(title, body, on_click) for this OS: desktop-notifier (Windows toast, macOS Notification Center),
    else the tray balloon (Windows) or osascript (macOS, no click action)."""
    def fallback(title, body):
        import subprocess
        if system.MACOS:
            script = f"display notification {json.dumps(body)} with title {json.dumps(title)}"
            subprocess.run(["osascript", "-e", script], check=False)
        elif tray is not None and getattr(tray, "HAS_NOTIFICATION", False):
            tray.notify(body, title)

    try:
        from desktop_notifier import DesktopNotifierSync, Icon
        notifier = DesktopNotifierSync(app_name="Flightwatch", app_icon=Icon(path=icon_path()))
    except Exception:
        return lambda title, body, on_click: fallback(title, body)

    def send(title, body, on_click):
        try:
            notifier.send(title, body, on_clicked=on_click)
        except Exception:
            fallback(title, body)
    return send


def new_alerts(status, seen):
    """Unread alerts not shown yet: [(key, title, text)]."""
    out = []
    for w in status.get("watches", []):
        a = w.get("alert")
        if a and a.get("unread"):
            key = f"{w['id']}|{a.get('time')}"
            if key not in seen:
                out.append((key, t("notify.title", dest=w.get("destination_name", w["name"])), a["text"]))
    return out


# --- the app ---------------------------------------------------------------------------------

class App:
    def __init__(self, background=False, headless=False):
        self.background = background
        self.headless = headless
        self.window = None
        self.tray = None
        self.stopping = threading.Event()
        self.notify = None
        self.preparing_browser = False

    # server ------------------------------------------------------------------------------
    def start_server(self):
        from . import web
        web.UI["app"] = True
        web.HOOKS["show"] = self.show
        threading.Thread(target=web.serve, args=(PORT,), daemon=True, name="web").start()
        for _ in range(50):
            try:
                httpx.get(URL + "api/ui", timeout=1)
                return
            except Exception:
                time.sleep(0.1)

    # window ------------------------------------------------------------------------------
    def show(self):
        if self.window is not None:
            self.window.show()
            self.window.restore()
        else:
            system.open_url(URL)

    def _on_closing(self):
        if self.stopping.is_set():
            return True
        self.window.hide()  # keep running in the tray
        return False

    # tray --------------------------------------------------------------------------------
    def _prepare_browser(self):
        """A Mac without Chrome/Edge needs Playwright's Chromium: fetch it now, not in the first search."""
        self.preparing_browser = True
        try:
            system.browser_launch_args()
        except Exception as e:
            print(f"browser: {e}", file=sys.stderr)
        finally:
            self.preparing_browser = False

    def _status_text(self):
        if self.preparing_browser:
            return t("tray.browser")
        st = read_status()
        if st.get("running"):
            return t("tray.searching")
        ws = st.get("watches", [])
        w = next((x for x in ws if x["id"] == st.get("selected")), None) or (ws[0] if ws else None)
        h = w and w.get("headline")
        return f"{w['name']}: {money(h['total'])}" if h else t("tray.no_data")

    def _build_tray(self):
        try:
            import pystray
            from PIL import Image
        except Exception:
            return None
        item = pystray.MenuItem
        menu = pystray.Menu(
            item(lambda _: self._status_text(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            item(lambda _: t("tray.open"), lambda: self.show(), default=True),
            item(lambda _: t("tray.search"), lambda: system.spawn_bg("run")),
            pystray.Menu.SEPARATOR,
            item(lambda _: t("tray.quit"), lambda: self.quit()),
        )
        return pystray.Icon("flightwatch", Image.open(icon_path()), "Flightwatch", menu)

    def quit(self):
        self.stopping.set()
        if self.tray is not None:
            self.tray.stop()
        if self.window is not None:
            self.window.destroy()

    # background loops --------------------------------------------------------------------
    def loop(self):
        """Scheduler, alerts and tray refresh; runs until Quit."""
        seen = set(_load_json(NOTIFIED, []))
        use_scheduler = not system.has_systemd()  # on systemd the timer runs the searches
        use_alerts = not system.LINUX  # Linux: the search process notifies itself
        while not self.stopping.wait(10):
            try:
                if use_scheduler:
                    scheduler_tick()
                st = read_status()
                if use_alerts and config.load()["general"]["notify"]:
                    for key, title, body in new_alerts(st, seen):
                        self.notify(title, body, self.show)
                        seen.add(key)
                    _save_json(NOTIFIED, sorted(seen)[-200:])
                if self.tray is not None:
                    self.tray.title = "Flightwatch – " + self._status_text()
                    self.tray.update_menu()
            except Exception as e:  # never let a bad status file stop the app
                print(f"app loop: {e}", file=sys.stderr)

    # run ---------------------------------------------------------------------------------
    def run(self):
        if _already_running():
            return 0
        _first_run_autostart()
        self.start_server()
        self.tray = None if self.headless else self._build_tray()
        self.notify = make_notifier(self.tray)
        threading.Thread(target=self.loop, daemon=True, name="loop").start()
        if not self.headless:
            threading.Thread(target=self._prepare_browser, daemon=True, name="browser").start()

        webview = None
        if not self.headless:
            try:
                import webview
            except Exception:
                webview = None
        if webview is None:
            return self._run_in_browser(tray_running=False)

        self.window = webview.create_window("Flightwatch", URL, width=1320, height=880, min_size=(760, 520),
                                            hidden=self.background, background_color="#111c18")
        self.window.events.closing += self._on_closing
        tray_running = False
        if self.tray is not None:
            if system.MACOS:
                self.tray.run_detached()  # shares the Cocoa main loop that pywebview starts
            else:
                threading.Thread(target=self.tray.run, daemon=True, name="tray").start()
            tray_running = True
        try:
            webview.start(private_mode=False, storage_path=str(config.STATE_DIR / "webview"), icon=icon_path())
        except Exception as e:  # no GUI engine (e.g. Linux without GTK/Qt bindings): use the browser
            print(f"window: {e}", file=sys.stderr)
            self.window = None
            return self._run_in_browser(tray_running)
        self.stopping.set()
        if self.tray is not None:
            self.tray.stop()
        return 0

    def _run_in_browser(self, tray_running):
        """No native window: the app opens in the default browser; tray and scheduler work as usual."""
        if not self.background and not self.headless:
            system.open_url(URL)
        if self.tray is not None and not tray_running:
            self.tray.run()  # blocks until Quit
        else:
            while not self.stopping.wait(1):
                pass
        return 0


def _first_run_autostart():
    """Login start is on by default (general.autostart); register it once, later the settings decide.
    The Windows installer already asked (its "autostart" task), so there the setting follows the registry."""
    from . import autostart
    marker = config.STATE_DIR / "autostart-done"
    if autostart.supported() and not marker.exists():
        try:
            if system.WINDOWS and system.FROZEN:
                doc = config.load_doc()
                doc["general"]["autostart"] = autostart.enabled()
                config.save_doc(doc)
            else:
                autostart.apply(bool(config.load()["general"]["autostart"]))
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
        except Exception as e:
            print(f"autostart: {e}", file=sys.stderr)


def _already_running():
    """Another app instance owns the port: ask it to show its window and stop here."""
    try:
        ui = httpx.get(URL + "api/ui", timeout=1).json()
    except Exception:
        return False
    if ui.get("app"):
        try:
            httpx.post(URL + "api/show", headers={"x-flightwatch": "1"}, json={}, timeout=2)
        except Exception:
            pass
        return True
    return False  # a plain `flightwatch serve` (e.g. the Linux web service) – not ours


def main(background=False, headless=False):
    i18n.reset()
    return App(background, headless).run()
