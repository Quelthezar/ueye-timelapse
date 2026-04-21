"""Entry point for ueye-timelapse application."""

import sys
from pathlib import Path


APP_ID = "ueye-timelapse.Quelthezar.App.1"


def _icon_path() -> Path:
    """Locate the app icon, whether running from source or a PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent.parent
    return base / "ueyetimelapse_icon.ico"


def main():
    """Launch the timelapse application."""
    # On Windows, set an explicit AppUserModelID before any window is created
    # so the taskbar uses our window icon instead of grouping under python.exe.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QApplication
    from ueye_timelapse.app import TimelapseWindow

    app = QApplication(sys.argv)
    app.setApplicationName("uEye Timelapse")

    icon_file = _icon_path()
    if icon_file.exists():
        icon = QIcon(str(icon_file))
        app.setWindowIcon(icon)

    window = TimelapseWindow()
    if icon_file.exists():
        window.setWindowIcon(icon)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
