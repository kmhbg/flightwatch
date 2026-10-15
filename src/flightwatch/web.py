"""Local web app (http://127.0.0.1:8765): an Omarchy app window from the bar widget on Linux, the app
window of `flightwatch app` on Windows/macOS.

Read-only views come from status.json; actions start searches as detached processes (transient systemd
user units where available) so the server never blocks. Bound to localhost only; state-changing requests
need the X-Flightwatch header, which a cross-site form cannot send.
"""
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlparse

from . import autostart, config, fx, i18n, places, store, system
from .runner import read_status, write_status

STATIC = files("flightwatch").joinpath("webapp")
UI = {"seq": 0, "nav": "", "app": False}  # navigation requests from the bar panel (fw.sh app …), polled by the page
HOOKS = {"show": None}  # set by `flightwatch app`: bring its window forward
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/png"}


def _bg(*args):
    """Run a flightwatch command detached (survives the server; one search at a time via the run lock)."""
    system.spawn_bg(*args)


def _cli(*args):
    r = system.run_cli(*args)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else "fel")
    return r.stdout


class Handler(BaseHTTPRequestHandler):
    server_version = "flightwatch"

    def log_message(self, fmt, *args):  # quiet; journald gets errors only
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)).encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/api/status":
                return self._send(200, read_status())
            if u.path == "/api/suggest":
                return self._send(200, places.suggest(q.get("q", ""), q.get("kind", "to")))
            if u.path == "/api/ui":
                return self._send(200, UI)
            if u.path == "/api/i18n":
                cur, rate = fx.current()
                cat = i18n.catalog()
                return self._send(200, {"lang": i18n.lang(), "locale": cat.get("_locale", "en-GB"), "s": cat,
                                        "currency": cur, "rate": rate,
                                        "times": config.load()["general"]["search_times"]})
            if u.path == "/api/settings":
                return self._send(200, _settings())
            if u.path == "/api/update":
                from . import update
                return self._send(200, update.check())
            if u.path == "/api/theme":
                import tomllib
                from pathlib import Path
                f = Path.home() / ".local/state/omarchy/current/theme/colors.toml"
                return self._send(200, tomllib.loads(f.read_text()) if system.LINUX and f.exists() else {})
            if u.path == "/api/history":
                db = store.connect()
                rows = db.execute("SELECT ts, best_total FROM runs WHERE watch=? AND best_total IS NOT NULL ORDER BY id",
                                  (q.get("watch", ""),)).fetchall()
                return self._send(200, [{"ts": t, "total": v} for t, v in rows])
            name = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            f = files("flightwatch").joinpath("assets", "icon.png") if name in ("icon.png", "favicon.ico") \
                else STATIC.joinpath(name)
            if "/" in name or not f.is_file():
                return self._send(404, {"error": "not found"})
            return self._send(200, f.read_bytes(), TYPES.get("." + name.rsplit(".", 1)[-1], "application/octet-stream"))
        except Exception as e:
            return self._send(500, {"error": str(e)})

    def do_POST(self):
        if self.headers.get("x-flightwatch") != "1":
            return self._send(403, {"error": "forbidden"})
        u = urlparse(self.path)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            if u.path == "/api/show":
                if HOOKS["show"]:
                    HOOKS["show"]()
                return self._send(200, {"ok": True})
            if u.path == "/api/ui":
                UI["seq"] += 1
                UI["nav"] = str(body.get("nav", ""))
                return self._send(200, UI)
            if u.path == "/api/search":
                args = ["run"] + (["--watch", body["watch"]] if body.get("watch") else []) + \
                       (["--quick", "--origin", body["origin"]] if body.get("origin") else [])
                _mark_running()
                _bg(*args)
                return self._send(200, {"ok": True})
            if u.path == "/api/compare":
                out = _cli("origin", "toggle", body["code"], "--watch", body["watch"])
                if body["code"] in out.split("jämför", 1)[-1]:
                    _mark_running()
                    _bg("run", "--quick", "--watch", body["watch"], "--origin", body["code"])
                return self._send(200, {"ok": True})
            if u.path == "/api/settings":
                _save_settings(body)
                return self._send(200, _settings())
            if u.path == "/api/new":
                args = ["new", "--to", body["to"], "--airport", body["airport"],
                        "--depart", body["depart"], "--return", body["return"],
                        "--adults", str(body.get("adults", 2)), "--guests", str(body.get("guests") or body.get("adults", 2))]
                if body.get("from"):
                    args += ["--from", body["from"]]
                if str(body.get("flex", "auto")) != "auto":
                    args += ["--flex", str(int(body["flex"]))]
                if body.get("lat") is not None:
                    args += ["--lat", str(body["lat"]), "--lon", str(body["lon"])]
                created = json.loads(_cli(*args).splitlines()[0])
                _mark_running()
                _bg("run", "--quick", "--watch", created["id"])
                return self._send(200, created)
            if u.path == "/api/dates":
                args = ["dates", body["watch"], "--depart", body["depart"], "--return", body["return"]]
                if str(body.get("flex", "auto")) != "auto":
                    args += ["--flex", str(int(body["flex"]))]
                out = json.loads(_cli(*args).splitlines()[0])
                _forget(body["watch"], out)
                _mark_running()
                _bg("run", "--quick", "--watch", body["watch"])
                return self._send(200, out)
            if u.path == "/api/select":
                _cli("select", body["watch"])
                return self._send(200, {"ok": True})
            if u.path == "/api/remove":
                _cli("remove", body["watch"])
                return self._send(200, {"ok": True})
            if u.path == "/api/ack":
                _cli("ack")
                return self._send(200, {"ok": True})
            if u.path == "/api/open":
                url = body.get("url", "")
                if url.startswith(("https://", "http://")):
                    system.open_url(url)
                return self._send(200, {"ok": True})
            if u.path == "/api/config":
                system.open_file(config.CONFIG_PATH)
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(400, {"error": str(e)})


def _settings():
    g = config.load()["general"]
    return {"language": g["language"], "currency": g["currency"], "currencies": fx.CURRENCIES,
            "search_times": list(g["search_times"]), "notify": bool(g["notify"]),
            "notify_drop_pct": g["notify_drop_pct"], "default_origin": g["default_origin"],
            "autostart": autostart.enabled() if autostart.supported() else False,
            "autostart_supported": autostart.supported(),
            "scheduler": "systemd" if system.has_systemd() else "app"}


def _save_settings(body):
    """Write the settings dialog to [general]; tomlkit keeps the user's comments."""
    times = [str(x).strip() for x in body.get("search_times", []) if str(x).strip()]
    for x in times:
        if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", x):
            raise ValueError(i18n.t("set.bad_time", value=x))
    doc = config.load_doc()
    g = doc.setdefault("general", {})
    if body.get("language") in ("auto", *i18n.LANGS):
        g["language"] = body["language"]
    if body.get("currency") in fx.CURRENCIES:
        g["currency"] = body["currency"]
    if times:
        g["search_times"] = sorted({x.zfill(5) for x in times})
    if re.fullmatch(r"[A-Za-z]{3}", str(body.get("default_origin", ""))):
        g["default_origin"] = body["default_origin"].upper()
    if "notify" in body:
        g["notify"] = bool(body["notify"])
    if body.get("notify_drop_pct"):
        g["notify_drop_pct"] = max(1, min(50, int(body["notify_drop_pct"])))
    if "autostart" in body and autostart.supported():
        g["autostart"] = bool(body["autostart"])
        autostart.apply(g["autostart"])
    config.save_doc(doc)
    i18n.reset()


def _forget(watch, dates):
    """Old dates' results must not be shown as if they were for the new dates."""
    from datetime import date, timedelta
    st = read_status()
    dep, ret = date.fromisoformat(dates["depart"]), date.fromisoformat(dates["return"])
    flex, days = dates["flex_days"], (ret - dep).days
    for w in st.get("watches", []):
        if w.get("id") == watch:
            w["reference_dates"] = {"depart": dates["depart"], "return": dates["return"]}
            w["window"] = {"earliest_depart": (dep - timedelta(days=flex)).isoformat(),
                           "latest_return": (ret + timedelta(days=flex)).isoformat(),
                           "flex_days": flex, "min_days": days - dates["shorten_days"], "max_days": days}
            w["by_origin"] = {}
            for k in ("overall", "reference", "same_depart", "headline", "alternatives"):
                w[k] = None if k != "alternatives" else []
    write_status(st)


def _mark_running():
    st = read_status()
    st["running"] = True
    write_status(st)


def serve(port=8765):
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
