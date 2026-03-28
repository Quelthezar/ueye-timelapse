"""
Video export utility for timelapse sessions.

Stitches a folder of sequentially numbered images into a video file.
Can be used as a library function, from the GUI, or from the command line.

CLI usage:
    python -m ueye_timelapse.video /path/to/session --fps 24
    python -m ueye_timelapse.video /path/to/session --format avi
    python -m ueye_timelapse.video /path/to/session  # auto-detect fps

Requires opencv-python:
    pip install opencv-python
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False


# =========================================================================
# Codec / format configuration
# =========================================================================

# Format name -> (fourcc code, file extension)
# mp4v is widely supported; XVID for AVI is near-universal.
VIDEO_FORMATS = {
    "mp4": ("mp4v", ".mp4"),
    "avi": ("XVID", ".avi"),
}

DEFAULT_FPS = 24.0


# =========================================================================
# Core functions
# =========================================================================

def find_session_images(session_dir: str | Path) -> List[Path]:
    """Find all timelapse frame images in a session directory.

    Looks in the ``images/`` subdirectory for image files with common
    extensions (``.png``, ``.tiff``, ``.tif``, ``.jpg``, ``.jpeg``, ``.bmp``).
    Falls back to the session root if no ``images/`` subfolder exists.

    Args:
        session_dir: Path to the session directory.

    Returns:
        Sorted list of image file paths.
    """
    session_dir = Path(session_dir)
    images_dir = session_dir / "images"

    if not images_dir.is_dir():
        # Fall back to session root (older session format)
        images_dir = session_dir

    # Collect image files with common extensions
    extensions = {".png", ".tiff", ".tif", ".jpg", ".jpeg", ".bmp"}
    images = sorted(
        p for p in images_dir.iterdir()
        if p.is_file() and p.suffix.lower() in extensions
    )

    return images


def suggest_fps(session_dir: str | Path) -> Optional[float]:
    """Suggest a playback FPS based on the session's capture interval.

    Reads ``session_metadata.json`` to find the capture interval, then
    suggests an FPS that produces a reasonable-length video. The heuristic
    aims for roughly 1 minute of video per hour of real capture time,
    capped between 10 and 60 fps.

    Args:
        session_dir: Path to the session directory.

    Returns:
        Suggested FPS, or None if metadata is not available.
    """
    meta_path = Path(session_dir) / "session_metadata.json"
    if not meta_path.exists():
        return None

    try:
        with open(meta_path) as f:
            metadata = json.load(f)
        interval = metadata.get("interval_seconds")
        if interval is None or interval <= 0:
            return None
    except (json.JSONDecodeError, OSError):
        return None

    # Heuristic: target ~1 minute of video per hour of real time.
    # Real time per frame = interval seconds.
    # We want: (num_frames / fps) ≈ real_duration / 60
    # So: fps ≈ 60 / interval ... but cap it to a sensible range.
    suggested = 60.0 / interval
    suggested = max(10.0, min(60.0, suggested))

    # Round to a clean number
    suggested = round(suggested)

    return float(suggested)


def create_video(
        session_dir: str | Path,
        output_path: Optional[str | Path] = None,
        fps: Optional[float] = None,
        video_format: str = "mp4",
        progress_callback=None,
) -> Path:
    """Create a video from a timelapse session's images.

    Args:
        session_dir: Path to the session directory containing images.
        output_path: Where to save the video. If None, saves to the
            session directory as ``timelapse.<ext>``.
        fps: Playback frames per second. If None, auto-suggests based
            on the capture interval, falling back to 24 fps.
        video_format: ``"mp4"`` or ``"avi"``.
        progress_callback: Optional callable ``(current, total)`` called
            after each frame is written, for progress reporting.

    Returns:
        Path to the created video file.

    Raises:
        RuntimeError: If OpenCV is not available.
        FileNotFoundError: If no images are found.
        ValueError: If the video format is not supported.
    """
    if not OPENCV_AVAILABLE:
        raise RuntimeError(
            "OpenCV is required for video export. "
            "Install it with: pip install opencv-python"
        )

    session_dir = Path(session_dir)

    # Resolve format
    video_format = video_format.lower()
    if video_format not in VIDEO_FORMATS:
        raise ValueError(
            f"Unsupported format '{video_format}'. "
            f"Supported: {', '.join(VIDEO_FORMATS.keys())}"
        )
    fourcc_str, extension = VIDEO_FORMATS[video_format]

    # Find images
    images = find_session_images(session_dir)
    if not images:
        # Report the actual directory that was searched
        images_dir = session_dir / "images"
        search_dir = images_dir if images_dir.is_dir() else session_dir
        raise FileNotFoundError(
            f"No image files found in {search_dir}"
        )

    # Resolve FPS
    if fps is None:
        fps = suggest_fps(session_dir) or DEFAULT_FPS
    fps = max(1.0, fps)

    # Resolve output path
    if output_path is None:
        output_path = session_dir / f"timelapse{extension}"
    output_path = Path(output_path)

    # Read first image to get dimensions
    first_frame = cv2.imread(str(images[0]), cv2.IMREAD_UNCHANGED)
    if first_frame is None:
        raise RuntimeError(f"Failed to read first image: {images[0]}")

    height, width = first_frame.shape[:2]

    logger.info(
        f"Creating video: {len(images)} frames, {width}x{height}, "
        f"{fps} fps, format={video_format}, output={output_path}"
    )

    # Create video writer
    fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
    writer = cv2.VideoWriter(
        str(output_path), fourcc, fps, (width, height), isColor=True
    )

    if not writer.isOpened():
        raise RuntimeError(
            f"Failed to create video writer. "
            f"Codec '{fourcc_str}' may not be available on this system."
        )

    try:
        total = len(images)
        for i, image_path in enumerate(images):
            frame = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
            if frame is None:
                logger.warning(f"Skipping unreadable image: {image_path}")
                continue

            # Normalize frame format for VideoWriter: 3-channel BGR, fixed size.
            # Grayscale -> BGR
            if frame.ndim == 2:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            # BGRA (4-channel, e.g. PNG/TIFF with alpha) -> BGR
            elif frame.ndim == 3 and frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

            # Ensure frame size matches the video size expected by the writer.
            if frame.shape[1] != width or frame.shape[0] != height:
                logger.warning(
                    "Resizing frame from %sx%s to %sx%s for video output: %s",
                    frame.shape[1],
                    frame.shape[0],
                    width,
                    height,
                    image_path,
                )
                frame = cv2.resize(frame, (width, height))

            writer.write(frame)

            if progress_callback is not None:
                progress_callback(i + 1, total)

    finally:
        writer.release()

    logger.info(f"Video saved: {output_path}")
    return output_path


# =========================================================================
# CLI entry point
# =========================================================================

def main():
    """Command-line interface for video export."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Create a timelapse video from a session folder.",
        prog="python -m ueye_timelapse.video",
    )
    parser.add_argument(
        "session_dir",
        help="Path to the session directory",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Playback FPS (default: auto-detect from session metadata)",
    )
    parser.add_argument(
        "--format",
        choices=list(VIDEO_FORMATS.keys()),
        default="mp4",
        dest="video_format",
        help="Video format (default: mp4)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output file path (default: timelapse.<ext> in session dir)",
    )

    args = parser.parse_args()

    # Set up logging for CLI
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    session_dir = Path(args.session_dir)
    if not session_dir.is_dir():
        print(f"Error: not a directory: {session_dir}", file=sys.stderr)
        sys.exit(1)

    # Show what we found
    images = find_session_images(session_dir)
    if not images:
        print(f"Error: no images found in {session_dir}", file=sys.stderr)
        sys.exit(1)

    suggested = suggest_fps(session_dir)
    fps = args.fps or suggested or DEFAULT_FPS
    print(f"Found {len(images)} images")
    if suggested and args.fps is None:
        print(f"Auto-detected FPS: {fps} (from capture interval)")
    else:
        print(f"Using FPS: {fps}")

    # Progress display
    def show_progress(current, total):
        pct = current / total * 100
        print(f"\r  Writing frame {current}/{total} ({pct:.0f}%)", end="", flush=True)

    try:
        output = create_video(
            session_dir=session_dir,
            output_path=args.output,
            fps=fps,
            video_format=args.video_format,
            progress_callback=show_progress,
        )
        print(f"\nVideo saved: {output}")
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()