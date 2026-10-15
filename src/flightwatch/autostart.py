"""Start `flightwatch app` when the user logs in (Windows: HKCU Run key, macOS: LaunchAgent).
On Linux the systemd units in deploy/ do this job, so it is not offered there."""
import plistlib
from pathlib import Path

from . import system

NAME = "Flightwatch"
PLIST = Path.home() / "Library/LaunchAgents/se.flightwatch.app.plist"


def supported():
    return system.WINDOWS or system.MACOS


def _command():
    return system.self_cmd() + ["app", "--background"]  # tray only; the window opens from the icon


def enabled():
    if system.WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, NAME)
                return True
        except OSError:
            return False
    if system.MACOS:
        return PLIST.exists()
    return False


def apply(on):
    """Turn login start on/off; does nothing where unsupported."""
    if system.WINDOWS:
        import subprocess
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, subprocess.list2cmdline(_command()))
            else:
                try:
                    winreg.DeleteValue(k, NAME)
                except OSError:
                    pass
    elif system.MACOS:
        if on:
            PLIST.parent.mkdir(parents=True, exist_ok=True)
            PLIST.write_bytes(plistlib.dumps({"Label": "se.flightwatch.app", "ProgramArguments": _command(),
                                              "RunAtLoad": True, "ProcessType": "Interactive"}))
        else:
            PLIST.unlink(missing_ok=True)
