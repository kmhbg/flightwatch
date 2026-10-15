"""Decide when to alert, and send desktop notifications. The bar widget shows the same alert
(status.json → watch.alert.unread) until it is acknowledged with `flightwatch ack`."""
import json
import os
import shutil
import subprocess

from . import system
from .config import STATE_DIR
from .i18n import money, t
from .pricing import CATEGORIES, label

STATE = STATE_DIR / "notify_state.json"


def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(s):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1))


def evaluate(watch, headline, drop_pct):
    """Compare the new headline price with the last one we alerted on / saw.
    Returns alert text or None. Alerts when the price enters 'target'/'good', improves category,
    or drops by at least drop_pct percent since the last run."""
    if not headline:
        return None
    state = _load()
    key = f"{watch['id']}:{headline['origin']}"  # per airport, so switching airport isn't a "price drop"
    prev = state.get(key, {})
    total, cat = headline["total"], headline["category"]
    reasons = []
    prev_total, prev_cat = prev.get("total"), prev.get("category")
    if cat in ("target", "good") and (prev_cat is None or CATEGORIES.index(cat) < CATEGORIES.index(prev_cat)):
        reasons.append(label(cat).lower())
    elif prev_cat and CATEGORIES.index(cat) < CATEGORIES.index(prev_cat):
        reasons.append(t("notify.now", cat=label(cat).lower(), prev=label(prev_cat).lower()))
    if prev_total and total <= prev_total * (1 - drop_pct / 100):
        reasons.append(t("notify.dropped", amount=money(prev_total - total), pct=f"{(1 - total / prev_total) * 100:.0f}"))
    state[key] = {"total": total, "category": cat}
    _save(state)
    if not reasons:
        return None
    return t("notify.text", name=watch["name"], price=money(total), reasons=", ".join(reasons))


def send(title, body, url="", urgency="normal"):
    """Linux: notify-send from the search process itself. Windows/macOS: nothing here – the long-running
    `flightwatch app` sees the new unread alert in status.json and shows it (see app.py)."""
    if not system.LINUX or not shutil.which("notify-send"):
        return
    args = ["notify-send", "-a", "Flightwatch", "-u", urgency, "-i", "airplane-mode-symbolic", title, body]
    if url and shutil.which("xdg-open"):
        # With an action, notify-send waits for the click; run detached so the runner isn't blocked.
        script = 'a=$(notify-send "$@" -A "open=$LABEL"); [ "$a" = open ] && xdg-open "$URL"'
        subprocess.Popen(["sh", "-c", script, "sh", *args[1:]], env={**os.environ, "URL": url, "LABEL": t("notify.open")},
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(args, check=False)
