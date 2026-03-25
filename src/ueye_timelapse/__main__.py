"""Entry point for ueye-timelapse application."""

import sys


def main():
    """Launch the timelapse application."""
    from PyQt5.QtWidgets import QApplication
    from ueye_timelapse.app import TimelapseWindow

    app = QApplication(sys.argv)
    app.setApplicationName("uEye Timelapse")

    window = TimelapseWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()