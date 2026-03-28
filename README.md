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

```bash
# Install pyueye first (requires the IDS SDK runtime)
pip install pyueye

# Then install ueye-timelapse using uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .

# Optional: install with video export support (adds OpenCV)
uv pip install -e ".[video]"
```

### Building the executable from source

If you want to build the executable yourself (Windows only):

```bash
pip install pyinstaller
python build_exe.py
```

The output will be in `dist/ueye-timelapse/`. Zip that folder for distribution.

## Usage

```bash
# Via the installed entry point
ueye-timelapse

# Or run directly
python -m ueye_timelapse
```

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
      __main__.py           # entry point (ueye-timelapse command)
      app.py                # PyQt5 main window and GUI
      camera.py             # IDS uEye camera controller (pyueye)
      capture.py            # timelapse capture worker thread
      video.py              # video export utility (OpenCV)
```