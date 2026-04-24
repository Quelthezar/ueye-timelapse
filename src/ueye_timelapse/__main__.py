"""Entry point for `python -m ueye_timelapse`.

All launch logic lives in `launcher.py` so the diagnostic wrapper runs
identically whether the app is started via the console script or the
module form.
"""

from ueye_timelapse.launcher import main


if __name__ == "__main__":
    main()
