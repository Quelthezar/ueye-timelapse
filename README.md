# ueye-timelapse

A small timelapse capture application for IDS uEye cameras, designed for
long-duration particle monitoring under a microscope.

## Features

- **Live preview** — continuous camera feed displayed in the GUI
- **Configurable interval** — from sub-second to many minutes between captures
- **Organized output** — timestamped session folders with numbered frames and a CSV capture log
- **PNG or TIFF** — lossless image formats
- **Manual capture** — single-shot "Capture Now" button for test images

## Requirements

- Python 3.10+
- IDS uEye camera with the [IDS uEye SDK](https://en.ids-imaging.com/ids-software-suite.html) installed
- The [`pyueye`](https://pypi.org/project/pyueye/) Python package (installed via `pip install pyueye` after the SDK is set up)
- Windows or Linux (pyueye does not support macOS)

## Installation

```bash
# Install pyueye first (requires the IDS SDK runtime)
pip install pyueye

# Then install ueye-timelapse
# Using uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .
```

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
3. Set the capture **interval** (value + unit) and choose the image **format**.
4. Set the **output directory** — this is the *parent* folder where session
   subfolders will be created. For example, if you select `D:\my_experiments`,
   each timelapse session creates a new folder like
   `D:\my_experiments\session_20260324_143052\` inside it.
   The default is `~/timelapse_output`.
5. Click **Start Timelapse** — images are saved to the session's `images/` subfolder.
6. Click **Stop** when done.

### Output structure

Each session creates a self-contained folder:

```
<your_output_directory>/
  session_20260324_143052/
    session_metadata.json       # interval, camera info, start time
    capture_log.csv             # frame_number, filename, timestamp, timestamp_unix
    images/
      frame_000001.png
      frame_000002.png
      ...
```

- **`session_metadata.json`** — records the capture interval, image format,
  camera model/serial, and session start time.
- **`capture_log.csv`** — one row per captured frame with the filename and
  both human-readable and Unix timestamps.
- **`images/`** — all captured frames, sequentially numbered.

## Optional: video export

If you have `opencv-python` installed, you can stitch frames into a video
(planned feature):

```bash
uv pip install "ueye-timelapse[video]"
```