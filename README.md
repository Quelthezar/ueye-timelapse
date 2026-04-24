# ueye-timelapse

A small timelapse capture application for IDS uEye cameras, designed for
long-duration particle monitoring under a microscope.

## Features

- **Live preview** — continuous camera feed displayed in the GUI, scales with window size
- **Configurable interval** — from sub-second to many minutes between captures
- **Flexible stop conditions** — stop manually, after a set duration, at a specific clock time, or after a fixed number of frames
- **Pause / resume** — pause a running session without losing it (duration mode suspends the countdown; clock time mode is absolute)
- **Estimated duration** — the UI previews how long the session will take before you start
- **Organized output** — timestamped session folders with numbered frames, a CSV capture log, and session metadata
- **PNG or TIFF** — lossless image formats
- **Manual capture** — single-shot "Capture Now" button for test images before starting a session
- **Video export** — stitch captured frames into an MP4 or AVI video, with auto-suggested playback FPS (requires OpenCV)
- **High-DPI support** — renders correctly on Retina / HiDPI displays

## Requirements

- Python 3.10+
- IDS uEye camera with the [IDS uEye SDK](https://en.ids-imaging.com/ids-software-suite.html) installed
- The [`pyueye`](https://pypi.org/project/pyueye/) Python package (installed via `pip install pyueye` after the SDK is set up)
- Windows or Linux (pyueye does not support macOS)

## Installation

### Option A: Standalone executable (recommended for end users)

1. Install the [IDS uEye SDK](https://en.ids-imaging.com/ids-software-suite.html)
   (the camera drivers are required regardless of installation method).
2. Download the latest `ueye-timelapse-windows.zip` from
   [GitHub Releases](https://github.com/Quelthezar/ueye-timelapse/releases).
3. Unzip and double-click `ueye-timelapse.exe`.

No Python installation required. Video export (MP4/AVI) is included.

### Option B: Install from source (for developers)

Requires Python 3.10+ and the [`pyueye`](https://pypi.org/project/pyueye/)
package (which in turn requires the IDS SDK).

**Important:** always install into a virtual environment and make sure that
environment is the one actually in use when you launch the app. A large
fraction of "module not found" errors come from installing into one Python
and launching from another. See [Troubleshooting](#troubleshooting) below
if something goes wrong.

With `uv` (recommended — see the [appendix](#appendix-setting-up-uv) if you
don't have it):

```bash
# Create and activate a virtual environment in the project directory
uv venv
source .venv/bin/activate      # Linux/macOS
.venv\Scripts\activate         # Windows (cmd / PowerShell)

# Install pyueye first (requires the IDS SDK runtime to be installed)
uv pip install pyueye

# Install the project in editable mode
uv pip install -e .

# Optional: include video export support (adds OpenCV)
uv pip install -e ".[video]"
```

With plain `pip`:

```bash
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
.venv\Scripts\activate         # Windows

pip install pyueye
pip install -e .
# Optional:
pip install -e ".[video]"
```

### Building the executable from source

If you want to build the executable yourself (Windows only):

```bash
pip install pyinstaller
python build_exe.py
```

The output will be in `dist/ueye-timelapse/`. Zip that folder for distribution.

## Usage

Activate the virtual environment you installed into, then:

```bash
# Via the installed entry point
ueye-timelapse

# Or run directly as a module (useful if the entry-point script is broken)
python -m ueye_timelapse
```

Both paths go through the same launcher, which checks for required
packages up front and prints a targeted message (with the active
interpreter path) if something is missing. See
[Troubleshooting](#troubleshooting) if you hit an import error.

### Quick start

1. Click **Connect** to connect to the first available uEye camera.
2. Verify the live preview shows a good image (check focus, framing).
   Use **Capture Now** to take a test shot and save it.
3. Set the capture **interval** (value + unit) and choose the image **format** (PNG or TIFF).
4. Set the **output directory** — this is the *parent* folder where session
   subfolders will be created. For example, if you select `D:\my_experiments`,
   each timelapse session creates a new folder like
   `D:\my_experiments\session_20260324_143052\` inside it.
   The default is `~/timelapse_output`.
5. Choose a **stop condition** (see below).
6. Click **Start Timelapse** — images are saved to the session's `images/` subfolder.
7. Use **Pause** / **Resume** if you need to temporarily halt capture.
8. Click **Stop** to end the session early, or let it stop automatically.
9. After the session finishes, you'll be offered to **export a video** (if OpenCV is installed).

### Stop conditions

The "Stop after" dropdown lets you choose when the session ends:

- **Manual** — runs until you click Stop. The default.
- **Duration** — runs for a specified amount of time (e.g., 2 hours). Pausing
  suspends the countdown, so paused time does not count toward the duration.
- **Clock time** — runs until a specific wall-clock time (e.g., 14:30). This is
  absolute — the session ends at that time regardless of pauses. If the chosen
  time has already passed today, it targets tomorrow.
- **Frame count** — runs until the specified number of frames have been captured
  (e.g., 500 frames).

An estimated duration is shown next to the stop condition controls before you
start, so you can verify the settings look right.

### Pause / resume

While a session is running, the **Pause** button temporarily halts capture.
The live preview continues updating so you can check on things (adjust focus,
inspect the sample, etc.) without ending the session. Press **Resume** to
continue where you left off.

The elapsed time display shows both total wall-clock time and time spent paused
(e.g., `01:23:45  (paused: 5m 23s)`).

### Output structure

Each session creates a self-contained folder:

```
<your_output_directory>/
  session_20260324_143052/
    session_metadata.json       # interval, camera info, start time, stop condition
    capture_log.csv             # frame_number, filename, timestamp, timestamp_unix
    images/
      frame_000001.png
      frame_000002.png
      ...
    timelapse.mp4               # (if video export was run)
```

- **`session_metadata.json`** — records the capture interval, image format,
  stop condition, camera model/serial, and session start time.
- **`capture_log.csv`** — one row per captured frame with the filename and
  both human-readable and Unix timestamps.
- **`images/`** — all captured frames, sequentially numbered.
- **`timelapse.mp4`** (or `.avi`) — exported video, if created.

### File menu

- **Open Session Folder** — opens the current/last session directory in your file manager.
- **Open Output Directory** — opens the parent output directory.
- **Export Video...** — export any session folder as a video (pick a folder, set FPS and format).
- **Quit** (Ctrl+Q) — close the application.

## Video export

Video export stitches a session's captured frames into a video file. It requires
OpenCV:

```bash
uv pip install "ueye-timelapse[video]"
# or: pip install opencv-python
```

### From the GUI

There are two ways to export a video:

1. **After a session finishes** — a dialog asks if you'd like to create a video.
2. **File → Export Video...** — select any session folder to export, even old ones.

The export dialog shows the number of frames, lets you set the playback FPS
(auto-suggested based on the capture interval), and choose between MP4 and AVI
format. A progress bar tracks the export.

### From the command line

You can also export videos without the GUI:

```bash
# Auto-detect FPS from session metadata, export as MP4
python -m ueye_timelapse.video /path/to/session

# Specify FPS and format
python -m ueye_timelapse.video /path/to/session --fps 30 --format avi

# Specify output path
python -m ueye_timelapse.video /path/to/session -o /path/to/output.mp4
```

The FPS auto-suggestion heuristic aims for roughly 1 minute of video per hour
of real capture time, capped between 10 and 60 fps.

## Project structure

```
ueye-timelapse/
  pyproject.toml            # package metadata and dependencies
  README.md
  src/
    ueye_timelapse/
      __init__.py
      __main__.py           # `python -m ueye_timelapse` — delegates to launcher
      launcher.py           # entry point with import diagnostics
      app.py                # PyQt5 main window and GUI
      camera.py             # IDS uEye camera controller (pyueye)
      capture.py            # timelapse capture worker thread
      video.py              # video export utility (OpenCV)
```

## Troubleshooting

The launcher prints a targeted error when a required package is missing,
including the Python interpreter path it's running under. That path is
usually the key clue: if it isn't the interpreter inside the virtual
environment you installed into, the fix is an environment issue, not a
package issue.

### `PyQt5 is not available in this Python environment`

The active Python can't import PyQt5. Most common causes:

- **Wrong environment active.** Compare the `Python executable` line in
  the error against the Python you installed PyQt5 into:
  ```bash
  which python        # Linux/macOS
  where  python       # Windows
  ```
  If they differ, activate the correct venv (`source .venv/bin/activate`
  on Linux/macOS, `.venv\Scripts\activate` on Windows) and try again.
- **PyQt5 genuinely missing.** `pip install PyQt5` (or re-run
  `pip install -e .`) into the correct environment.
- **System Python vs. user Python.** On some Linux distros (notably Arch)
  running `python` outside a venv may hit a system interpreter that can't
  see packages you installed elsewhere. Always launch from an activated
  venv.

### `pyueye is not installed` notice

This is a warning, not a fatal error — the GUI still launches, but camera
features are disabled. To enable them, install the
[IDS uEye SDK](https://en.ids-imaging.com/ids-software-suite.html), then
`pip install pyueye` into your environment.

### Video export is unavailable

`opencv-python` is an optional dependency. Install it with
`pip install -e ".[video]"` (or `pip install opencv-python`) into the
active environment.

### Something else failed to import

The launcher catches any `ImportError` raised during startup and prints
the name of the missing module plus the active interpreter. Reinstalling
the project into that environment (`pip install -e .`) resolves most
cases; if not, please open an issue with the full error output.

## Appendix: Setting up uv

[`uv`](https://docs.astral.sh/uv/) is a fast Python package and
environment manager. It is not required — plain `pip` and `venv` work
fine — but the workflow is shorter.

### Install

- **Linux / macOS:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows (PowerShell):**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- Or via your package manager (`brew install uv`, `pacman -S uv`, etc.).

See the [official uv install docs](https://docs.astral.sh/uv/getting-started/installation/)
for other options.

### Typical workflow in this project

From the project root:

```bash
# Create a virtual environment (.venv/ in the project directory)
uv venv

# Activate it
source .venv/bin/activate      # Linux/macOS
.venv\Scripts\activate         # Windows

# Install dependencies into the active venv
uv pip install pyueye          # requires the IDS SDK runtime
uv pip install -e ".[video]"   # editable install + optional video deps

# Launch
ueye-timelapse
```

You can also run the app without activating the venv by using
`uv run ueye-timelapse` — uv picks up `.venv/` automatically. This can
be convenient for one-off launches but makes the active interpreter
less visible in error messages, so activation is preferred while
troubleshooting.