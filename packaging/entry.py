"""PyInstaller entry point: Flightwatch.exe / Flightwatch.app. No arguments = the desktop app; with
arguments it is the normal CLI (the app starts its own searches this way)."""
import sys

from flightwatch import main

if __name__ == "__main__":
    sys.exit(main())
