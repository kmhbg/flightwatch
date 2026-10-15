"""Everything that differs between Linux, Windows and macOS: folders, starting ourselves in the background,
opening links/files, the run lock and the browser the page-based sources drive.

Linux keeps the XDG folders it always had (~/.config/flightwatch, ~/.local/state/flightwatch …), so an
existing install continues where it was.
"""
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

import platformdirs

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
LINUX = sys.platform.startswith("linux")
FROZEN = getattr(sys, "frozen", False)  # PyInstaller build
APP = "flightwatch" if LINUX else "Flightwatch"


def config_dir():
    return Path(platformdirs.user_config_dir(APP, appauthor=False))


def data_dir():
    return Path(platformdirs.user_data_dir(APP, appauthor=False))


def state_dir():
    return Path(platformdirs.user_state_dir(APP, appauthor=False))


def cache_dir():
    return Path(platformdirs.user_cache_dir(APP, appauthor=False))


def self_cmd():
    """Command that starts this program again (with arguments appended). PATH is not trusted: a unit
    started at boot or a GUI-launched app often lacks the folder the entry point lives in."""
    if FROZEN:
        return [sys.executable]
    me = os.path.abspath(sys.argv[0])
    if os.path.basename(me).startswith("flightwatch") and os.access(me, os.X_OK) and not me.endswith(".py"):
        return [me]
    found = shutil.which("flightwatch")
    return [found] if found else [sys.executable, "-m", "flightwatch"]


def has_systemd():
    return LINUX and bool(shutil.which("systemd-run")) and Path("/run/systemd/system").exists() \
        and bool(os.environ.get("XDG_RUNTIME_DIR"))


ENV_KEYS = ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "FLIGHTWATCH_CONFIG",
            "FLIGHTWATCH_LANG")


def spawn_bg(*args):
    """Run a flightwatch command detached, so it outlives the caller (the run lock keeps one search at a time).
    On systemd it becomes a transient user unit (own cgroup, logs in the journal)."""
    cmd = self_cmd() + list(args)
    if has_systemd():
        env = [f"--setenv={k}={os.environ[k]}" for k in ENV_KEYS if k in os.environ]
        subprocess.Popen(["systemd-run", "--user", "--no-block", "--collect", "--quiet", *env, *cmd],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if WINDOWS:
        kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)


def run_cli(*args, timeout=90):
    """Run a flightwatch command and wait for it (no console window on Windows)."""
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}
    return subprocess.run(self_cmd() + list(args), capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout, **kw)


def open_url(url):
    if LINUX and shutil.which("xdg-open"):
        # setsid: the browser must not belong to the web service's cgroup (it would die with a restart).
        subprocess.Popen(["setsid", "-f", "xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(url)


def open_file(path):
    """Open a text file in the user's editor."""
    path = str(path)
    if WINDOWS:
        subprocess.Popen(["notepad.exe", path], creationflags=subprocess.CREATE_NO_WINDOW)
    elif MACOS:
        subprocess.Popen(["open", "-t", path])
    elif shutil.which("omarchy"):
        subprocess.Popen(["setsid", "-f", "omarchy", "launch", "editor", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- browser for the page-based sources (Google Flights, Apollo, Booking …) ---------------------

def _chrome_version_ua():
    plat = {"win32": "Windows NT 10.0; Win64; x64", "darwin": "Macintosh; Intel Mac OS X 10_15_7"}.get(
        sys.platform, "X11; Linux x86_64")
    return f"Mozilla/5.0 ({plat}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"


USER_AGENT = _chrome_version_ua()


def browsers_path():
    """Where a downloaded Chromium lives when the computer has neither Chrome/Chromium nor Edge."""
    return cache_dir() / "ms-playwright"


def browser_launch_args():
    """Playwright launch kwargs: an installed Chrome/Chromium/Edge, else our own downloaded Chromium."""
    if LINUX:
        exe = shutil.which("chromium") or shutil.which("google-chrome-stable") or shutil.which("google-chrome")
        if exe:
            return {"executable_path": exe}
    if WINDOWS:
        return {"channel": "msedge"}  # Edge ships with Windows
    if MACOS:
        if Path("/Applications/Google Chrome.app").exists():
            return {"channel": "chrome"}
        if Path("/Applications/Microsoft Edge.app").exists():
            return {"channel": "msedge"}
    ensure_chromium()
    return {}


def ensure_chromium():
    """Download Playwright's headless Chromium once (≈250 MB) into the cache folder. Assigned, not setdefault:
    PyInstaller's Playwright hook sets "0" (inside the read-only program folder)."""
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path())
    if any(browsers_path().glob("chromium*")):
        return
    from playwright._impl._driver import compute_driver_executable, get_driver_env
    driver = compute_driver_executable()
    cmd = list(driver) if isinstance(driver, tuple) else [str(driver)]
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}
    subprocess.run(cmd + ["install", "--only-shell", "chromium"], env=get_driver_env(), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
