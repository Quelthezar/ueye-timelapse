"""
Timelapse capture worker.

Handles timed image capture in a QThread, saving images and maintaining
a capture log CSV. The worker emits signals for UI updates and runs
independently of the preview refresh.

Supports four stop conditions:
    - manual: run until explicitly stopped
    - duration: run for a specified number of seconds
    - clock_time: run until a specific wall-clock datetime
    - frame_count: run until N frames have been captured
"""

import csv
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt5.QtCore import QThread, pyqtSignal

from ueye_timelapse.camera import CameraController, CameraOperationError

logger = logging.getLogger(__name__)


# Stop condition mode constants
STOP_MANUAL = "manual"
STOP_DURATION = "duration"
STOP_CLOCK_TIME = "clock_time"
STOP_FRAME_COUNT = "frame_count"


class CaptureWorker(QThread):
    """Worker thread for timed timelapse capture.

    Captures images at a fixed interval, saves them to a session directory,
    and maintains a CSV log of all captures.

    Signals:
        image_captured(int, str): frame_number, filename
        countdown_tick(float): seconds remaining until next capture
        remaining_updated(str): human-readable string for remaining time/frames
        error_occurred(str): error message
        session_started(str): session directory path
        session_finished(int): total frames captured
    """

    image_captured = pyqtSignal(int, str)        # frame_number, filename
    countdown_tick = pyqtSignal(float)            # seconds_remaining
    remaining_updated = pyqtSignal(str)           # remaining display string
    paused_changed = pyqtSignal(bool)             # is_paused
    error_occurred = pyqtSignal(str)              # error message
    session_started = pyqtSignal(str)             # session directory path
    session_finished = pyqtSignal(int)            # total frames captured

    def __init__(
            self,
            camera: CameraController,
            output_dir: str,
            interval_seconds: float,
            image_format: str = "png",
            stop_condition: Optional[Dict[str, Any]] = None,
            parent=None,
    ):
        """Initialize the capture worker.

        Args:
            camera: Connected CameraController instance.
            output_dir: Base output directory. A timestamped session
                subfolder will be created inside it.
            interval_seconds: Time between captures in seconds.
            image_format: Image format — "png" or "tiff".
            stop_condition: When to stop capturing. Dict with key "mode" and
                mode-specific values:
                - {"mode": "manual"} — run until request_stop() (default)
                - {"mode": "duration", "seconds": float}
                - {"mode": "clock_time", "stop_at": datetime}
                - {"mode": "frame_count", "max_frames": int}
            parent: Qt parent object.
        """
        super().__init__(parent)

        self._camera = camera
        self._base_output_dir = Path(output_dir)
        self._interval_seconds = interval_seconds
        self._image_format = image_format.lower().strip(".")

        # Validate format
        if self._image_format not in ("png", "tiff", "tif"):
            logger.warning(
                f"Unknown format '{self._image_format}', defaulting to png"
            )
            self._image_format = "png"

        # Normalize tif -> tiff for consistency
        if self._image_format == "tif":
            self._image_format = "tiff"

        # Stop condition
        if stop_condition is None:
            stop_condition = {"mode": STOP_MANUAL}
        self._stop_condition = stop_condition

        self._stop_requested = False
        self._paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # starts unpaused (event is "set" = not blocked)
        self._total_paused_seconds = 0.0
        self._pause_start: Optional[datetime] = None
        self._frame_count = 0
        self._session_start: Optional[datetime] = None
        self._session_dir: Optional[Path] = None
        self._images_dir: Optional[Path] = None
        self._csv_path: Optional[Path] = None

    # =========================================================================
    # Public Interface
    # =========================================================================

    def request_stop(self):
        """Request the capture loop to stop after the current cycle."""
        self._stop_requested = True
        # Unblock pause so the thread can exit
        self._pause_event.set()

    def pause(self):
        """Pause capturing. The worker thread blocks until resumed."""
        if not self._paused:
            self._paused = True
            self._pause_start = datetime.now()
            self._pause_event.clear()  # block the thread
            self.paused_changed.emit(True)
            logger.info("Capture paused")

    def resume(self):
        """Resume capturing after a pause."""
        if self._paused:
            if self._pause_start is not None:
                paused_duration = (datetime.now() - self._pause_start).total_seconds()
                self._total_paused_seconds += paused_duration
                self._pause_start = None
            self._paused = False
            self._pause_event.set()  # unblock the thread
            self.paused_changed.emit(False)
            logger.info(
                f"Capture resumed (total paused: "
                f"{self._total_paused_seconds:.1f}s)"
            )

    def toggle_pause(self):
        """Toggle between paused and running."""
        if self._paused:
            self.resume()
        else:
            self.pause()

    @property
    def is_paused(self) -> bool:
        """Whether the worker is currently paused."""
        return self._paused

    @property
    def total_paused_seconds(self) -> float:
        """Total time spent paused (including current pause if active)."""
        total = self._total_paused_seconds
        if self._paused and self._pause_start is not None:
            total += (datetime.now() - self._pause_start).total_seconds()
        return total

    @property
    def frame_count(self) -> int:
        """Number of frames captured so far."""
        return self._frame_count

    @property
    def session_dir(self) -> Optional[Path]:
        """Path to the current session directory, or None."""
        return self._session_dir

    # =========================================================================
    # Thread Entry Point
    # =========================================================================

    def run(self):
        """Main capture loop — runs in worker thread."""
        self._stop_requested = False
        self._frame_count = 0
        self._session_start = datetime.now()

        # Create session directory
        try:
            self._session_dir = self._create_session_dir()
            self._csv_path = self._session_dir / "capture_log.csv"
            self._write_csv_header()
            self._save_session_metadata()
        except Exception as e:
            self.error_occurred.emit(f"Failed to create session directory: {e}")
            return

        self.session_started.emit(str(self._session_dir))

        mode = self._stop_condition["mode"]
        logger.info(
            f"Timelapse session started: {self._session_dir} "
            f"(interval={self._interval_seconds}s, format={self._image_format}, "
            f"stop={mode})"
        )

        # Capture loop
        try:
            while not self._stop_requested:
                # Block here if paused, but use a timeout so time-based
                # stop conditions (clock time, duration) can still be
                # evaluated while paused.
                if not self._pause_event.wait(timeout=0.5):
                    # Still paused after timeout; check stop conditions
                    if self._stop_requested or self._should_stop():
                        break
                    # Continue waiting while paused
                    continue

                if self._stop_requested:
                    break

                # Check stop condition BEFORE capturing
                if self._should_stop():
                    break

                # Capture a frame
                self._capture_one_frame()

                # Update remaining display
                self._emit_remaining()

                # Check again AFTER capturing (frame count condition)
                if self._should_stop():
                    break

                # Wait for the next interval, emitting countdown ticks
                self._wait_with_countdown()

        except Exception as e:
            error_msg = f"Unexpected error in capture loop: {e}"
            logger.error(error_msg, exc_info=True)
            self.error_occurred.emit(error_msg)

        # Finalize
        logger.info(
            f"Timelapse session finished: {self._frame_count} frames captured"
        )
        self.session_finished.emit(self._frame_count)

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _create_session_dir(self) -> Path:
        """Create a timestamped session directory with images/ subfolder."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = self._base_output_dir / f"session_{timestamp}"
        session_dir.mkdir(parents=True, exist_ok=True)

        self._images_dir = session_dir / "images"
        self._images_dir.mkdir(exist_ok=True)

        return session_dir

    def _save_session_metadata(self):
        """Save session metadata to a JSON file."""
        # Build a JSON-serializable version of the stop condition
        stop_info = dict(self._stop_condition)
        if "stop_at" in stop_info and isinstance(stop_info["stop_at"], datetime):
            stop_info["stop_at"] = stop_info["stop_at"].isoformat()

        metadata = {
            "session_start": self._session_start.isoformat(),
            "interval_seconds": self._interval_seconds,
            "image_format": self._image_format,
            "stop_condition": stop_info,
            "camera_info": self._camera.camera_info,
        }
        meta_path = self._session_dir / "session_metadata.json"
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)
        logger.debug(f"Session metadata saved to {meta_path}")

    def _should_stop(self) -> bool:
        """Check whether the stop condition has been met.

        Duration mode uses *active* time (wall-clock minus paused time),
        so pausing suspends the duration countdown.
        Clock time mode is absolute — it fires at the specified wall-clock
        time regardless of pause state.

        Returns:
            True if the session should end.
        """
        mode = self._stop_condition["mode"]

        if mode == STOP_MANUAL:
            return False

        elif mode == STOP_DURATION:
            # Active time = wall-clock elapsed minus time spent paused
            elapsed = (datetime.now() - self._session_start).total_seconds()
            active = elapsed - self.total_paused_seconds
            return active >= self._stop_condition["seconds"]

        elif mode == STOP_CLOCK_TIME:
            # Absolute wall-clock — fires regardless of pause
            return datetime.now() >= self._stop_condition["stop_at"]

        elif mode == STOP_FRAME_COUNT:
            return self._frame_count >= self._stop_condition["max_frames"]

        return False

    def _emit_remaining(self):
        """Emit a human-readable string describing what's remaining."""
        mode = self._stop_condition["mode"]

        if mode == STOP_MANUAL:
            self.remaining_updated.emit("∞ (manual stop)")

        elif mode == STOP_DURATION:
            # Remaining based on active time (excludes paused time)
            elapsed = (datetime.now() - self._session_start).total_seconds()
            active = elapsed - self.total_paused_seconds
            remaining_s = max(0, self._stop_condition["seconds"] - active)
            self.remaining_updated.emit(self._format_seconds(remaining_s))

        elif mode == STOP_CLOCK_TIME:
            remaining_s = max(
                0,
                (self._stop_condition["stop_at"] - datetime.now()).total_seconds(),
            )
            self.remaining_updated.emit(self._format_seconds(remaining_s))

        elif mode == STOP_FRAME_COUNT:
            remaining = max(
                0, self._stop_condition["max_frames"] - self._frame_count
            )
            self.remaining_updated.emit(f"{remaining} frames left")

    @staticmethod
    def _format_seconds(seconds: float) -> str:
        """Format a number of seconds as a human-readable duration string."""
        total = int(seconds)
        if total < 60:
            return f"{total}s remaining"
        elif total < 3600:
            m, s = divmod(total, 60)
            return f"{m}m {s:02d}s remaining"
        else:
            h, remainder = divmod(total, 3600)
            m, s = divmod(remainder, 60)
            return f"{h}h {m:02d}m remaining"

    def _write_csv_header(self):
        """Write the header row to the capture log CSV."""
        with open(self._csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "frame_number",
                "filename",
                "timestamp",
                "timestamp_unix",
            ])

    def _capture_one_frame(self):
        """Capture a single frame, save it, and log it."""
        try:
            image, metadata = self._camera.capture_image()
        except CameraOperationError as e:
            self.error_occurred.emit(f"Capture failed: {e}")
            return

        if image is None:
            self.error_occurred.emit("Capture returned None — camera may be disconnected")
            return

        # Build filename
        self._frame_count += 1
        filename = f"frame_{self._frame_count:06d}.{self._image_format}"
        filepath = self._images_dir / filename

        # Save image
        try:
            CameraController.save_image(image, str(filepath))
        except CameraOperationError as e:
            self.error_occurred.emit(f"Failed to save {filename}: {e}")
            return

        # Append to CSV log
        try:
            with open(self._csv_path, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    self._frame_count,
                    filename,
                    metadata.get("timestamp", ""),
                    metadata.get("timestamp_unix", ""),
                ])
        except Exception as e:
            logger.warning(f"Failed to write CSV row: {e}")

        logger.debug(f"Captured frame {self._frame_count}: {filename}")
        self.image_captured.emit(self._frame_count, filename)

    def _wait_with_countdown(self):
        """Wait for the capture interval, emitting countdown ticks.

        Checks for stop/pause requests every 0.25 seconds so the thread
        remains responsive. Uses timeout-based pause wait so time-based
        stop conditions can still fire while paused.
        """
        remaining = self._interval_seconds
        tick_interval = 0.25  # seconds between countdown updates

        while remaining > 0 and not self._stop_requested:
            # Block if paused, but with timeout so stop conditions
            # can be checked periodically
            if not self._pause_event.wait(timeout=tick_interval):
                # Still paused — check if we should stop anyway
                if self._stop_requested or self._should_stop():
                    break
                continue

            if self._stop_requested:
                break

            self.countdown_tick.emit(remaining)
            sleep_time = min(tick_interval, remaining)
            time.sleep(sleep_time)
            remaining -= sleep_time

        if not self._stop_requested:
            self.countdown_tick.emit(0.0)