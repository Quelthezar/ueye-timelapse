"""
Diagnostic launcher for the ueye-timelapse GUI.

Wraps the real app startup with targeted error messages when a required
package is missing. The aim is to turn a cryptic traceback like
``ImportError: No module named PyQt5`` (raised halfway through importing
the GUI) into a clear message that names the missing package and shows
which Python environment is actually being used — which is the usual
source of confusion ("I installed it, why isn't it found?").

Both ``ueye-timelapse`` (the installed console script) and
``python -m ueye_timelapse`` route through here.
"""

import sys
from pathlib import Path
from textwrap import dedent


APP_ID = "ueye-timelapse.Quelthezar.App.1"


def _env_info() -> str:
    return dedent(
        f"""
        Python executable: {sys.executable}
        Python version:    {sys.version.split()[0]}
        sys.prefix:        {sys.prefix}
        """
    ).strip()


def _fail(title: str, body: str) -> "None":
    message = f"ueye-timelapse: {title}\n\n{body}\n\n{_env_info()}\n"
    sys.stderr.write(message)
    sys.exit(1)


def _check_pyqt5() -> None:
    try:
        import PyQt5  # noqa: F401
        from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: F401
    except ImportError as exc:
        _fail(
            "PyQt5 is not available in this Python environment.",
            dedent(
                f"""
                Import error: {exc}

                To fix:
                  pip install PyQt5
                (or reinstall the project: pip install -e .)

                If you believe PyQt5 is already installed, the interpreter
                shown below is probably not the one you installed it into.
                Check with:
                  which python        (Linux/macOS)
                  where  python       (Windows)
                and activate the correct virtual environment before launching.
                """
            ).strip(),
        )


def _pyueye_notice() -> None:
    """Print a one-line notice if pyueye is missing.

    We do not hard-fail here: the GUI can launch without pyueye (camera
    features simply stay disabled and the UI reports it). This keeps the
    app useful for video export on machines without the IDS SDK.
    """
    try:
        import pyueye  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "ueye-timelapse: note: pyueye is not installed — camera "
            "features will be disabled. Install the IDS uEye SDK, then "
            "`pip install pyueye` to enable them.\n"
        )


def _icon_path() -> Path:
    """Locate the app icon, whether running from source or a PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent.parent
    return base / "ueyetimelapse_icon.ico"


def _run_app() -> None:
    # Imports kept local so _check_pyqt5 runs first and can report a
    # clean error before any GUI code is touched.
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


def main() -> None:
    """Launch the timelapse application with import diagnostics."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    _check_pyqt5()
    _pyueye_notice()

    try:
        _run_app()
    except ImportError as exc:
        _fail(
            f"Failed to import a required module: {exc.name or exc}",
            dedent(
                f"""
                Import error: {exc}

                This usually means a dependency is missing from the active
                Python environment. Try reinstalling the project into it:
                  pip install -e .
                """
            ).strip(),
        )


if __name__ == "__main__":
    main()
