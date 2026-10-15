# PyInstaller spec: one folder build (fast start, no unpacking on every launch).
#   pip install ".[gui,build]" && python packaging/make_icons.py && pyinstaller packaging/flightwatch.spec
# Windows: dist/Flightwatch/Flightwatch.exe (then packaging/windows/flightwatch.iss)
# macOS:   dist/Flightwatch.app (then hdiutil → .dmg, see .github/workflows/release.yml)
import sys
from importlib.metadata import version
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = Path(SPECPATH)
VERSION = version("flightwatch")

datas = collect_data_files("flightwatch")  # webapp/, i18n/, queries/, assets/
datas += collect_data_files("desktop_notifier")
hidden = collect_submodules("flightwatch") + collect_submodules("desktop_notifier") + collect_submodules("pystray")
if sys.platform == "win32":
    hidden += collect_submodules("winrt")  # desktop-notifier's toast backend
    hidden += ["webview.platforms.edgechromium", "webview.platforms.winforms"]
elif sys.platform == "darwin":
    hidden += ["webview.platforms.cocoa"]

a = Analysis(
    [str(HERE / "entry.py")],
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
icon = str(HERE / ("icon.ico" if sys.platform == "win32" else "icon.icns" if sys.platform == "darwin" else "icon.png"))
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Flightwatch",
    console=False,  # GUI app; output goes to the log file in the state folder
    icon=icon,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Flightwatch")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Flightwatch.app",
        icon=icon,
        bundle_identifier="se.flightwatch.app",
        version=VERSION,
        info_plist={
            "CFBundleName": "Flightwatch",
            "CFBundleDisplayName": "Flightwatch",
            "CFBundleShortVersionString": VERSION,
            "LSUIElement": True,  # menu bar app: no Dock icon, the window opens from the menu bar
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
