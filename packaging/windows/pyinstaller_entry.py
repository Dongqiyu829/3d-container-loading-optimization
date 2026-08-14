"""PyInstaller entry point kept separate from source/developer launchers."""

from gui.app import main


if __name__ == "__main__":
    raise SystemExit(main())

