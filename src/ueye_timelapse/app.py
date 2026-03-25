"""
Timelapse application main window.

A small PyQt5 GUI for capturing timelapse image sequences from an IDS uEye
camera. Provides a live preview, configurable capture interval, and
organized session output.
"""

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
from PyQt5.QtCore import QSize, Qt, QTime, QTimer, QUrl, pyqtSlot
from PyQt5.QtGui import QDesktopServices, QImage, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtWidgets import QTimeEdit

from ueye_timelapse.camera import (
    CameraController,
    CameraError,
    CameraNotAvailableError,
    PYUEYE_AVAILABLE,
)
from ueye_timelapse.capture import (
    CaptureWorker,
    STOP_MANUAL,
    STOP_DURATION,
    STOP_CLOCK_TIME,
    STOP_FRAME_COUNT,
)

logger = logging.getLogger(__name__)


class TimelapseWindow(QMainWindow):
    """Main application window for uEye timelapse capture.

    Layout (top to bottom):
        - Connection bar: connect/disconnect button, status indicator, camera info
        - Capture controls: interval, output dir, format, start/stop, capture-now
        - Status bar: frame count, countdown, session elapsed time
        - Live preview: fills all remaining space, scales with window
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("uEye Timelapse")
        self.setMinimumSize(640, 520)
        self.resize(900, 700)

        # Camera
        self._camera = CameraController()

        # Capture worker (created per session)
        self._capture_worker: Optional[CaptureWorker] = None
        self._is_capturing = False

        # Session tracking
        self._session_start_time: Optional[datetime] = None
        self._current_session_dir: Optional[Path] = None

        # Preview timer
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._preview_fps = 10.0  # Hz

        # Elapsed time timer
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_elapsed_time)

        # Build UI
        self._build_ui()
        self._update_ui_state()

    # =========================================================================
    # UI Construction
    # =========================================================================

    def _build_ui(self):
        """Build the complete user interface."""
        # --- Menu bar ---
        self._build_menu_bar()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(6)

        # --- Connection row ---
        layout.addWidget(self._build_connection_row())

        # --- Capture controls ---
        layout.addWidget(self._build_capture_controls())

        # --- Status row ---
        layout.addWidget(self._build_status_row())

        # --- Live preview (expands to fill space) ---
        layout.addWidget(self._build_preview_area(), stretch=1)

        # --- Status bar ---
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        if not PYUEYE_AVAILABLE:
            self._statusbar.showMessage(
                "⚠ pyueye not available — camera functions disabled"
            )

    def _build_menu_bar(self):
        """Build the application menu bar."""
        menu_bar = self.menuBar()

        # --- File menu ---
        file_menu = menu_bar.addMenu("&File")

        self._open_session_action = QAction("Open Session Folder", self)
        self._open_session_action.setEnabled(False)
        self._open_session_action.triggered.connect(self._on_open_session_folder)
        file_menu.addAction(self._open_session_action)

        self._open_output_action = QAction("Open Output Directory", self)
        self._open_output_action.triggered.connect(self._on_open_output_dir)
        file_menu.addAction(self._open_output_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _on_open_session_folder(self):
        """Open the current/last session folder in the system file manager."""
        if self._current_session_dir and self._current_session_dir.exists():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self._current_session_dir))
            )
        else:
            self._statusbar.showMessage("No session folder to open", 3000)

    def _on_open_output_dir(self):
        """Open the output directory in the system file manager."""
        output_dir = Path(self._output_dir_edit.text())
        if output_dir.exists():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(output_dir))
            )
        else:
            # Offer to create it
            reply = QMessageBox.question(
                self,
                "Directory Not Found",
                f"The output directory does not exist yet:\n{output_dir}\n\n"
                f"Create it now?",
                QMessageBox.Yes | QMessageBox.No,
                )
            if reply == QMessageBox.Yes:
                try:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    QDesktopServices.openUrl(
                        QUrl.fromLocalFile(str(output_dir))
                    )
                except Exception as e:
                    QMessageBox.warning(
                        self, "Error",
                        f"Could not create directory:\n{e}",
                    )

    def _build_connection_row(self) -> QGroupBox:
        """Build the camera connection controls."""
        group = QGroupBox("Camera")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        row = QHBoxLayout(group)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setFixedWidth(100)
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        row.addWidget(self._connect_btn)

        # Status indicator dot
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(14, 14)
        self._status_dot.setStyleSheet(
            "background-color: gray; border-radius: 7px; border: 1px solid #555;"
        )
        row.addWidget(self._status_dot)

        self._connection_label = QLabel("Not connected")
        row.addWidget(self._connection_label)

        row.addSpacing(20)

        row.addWidget(QLabel("Model:"))
        self._model_label = QLabel("—")
        row.addWidget(self._model_label)

        row.addSpacing(12)

        row.addWidget(QLabel("Resolution:"))
        self._resolution_label = QLabel("—")
        row.addWidget(self._resolution_label)

        row.addStretch()
        return group

    def _build_capture_controls(self) -> QGroupBox:
        """Build the capture configuration controls."""
        group = QGroupBox("Capture Settings")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        outer = QVBoxLayout(group)

        # Row 1: interval, format, output dir
        row1 = QHBoxLayout()

        row1.addWidget(QLabel("Interval:"))
        self._interval_spin = QDoubleSpinBox()
        self._interval_spin.setRange(0.5, 9999.0)
        self._interval_spin.setValue(30.0)
        self._interval_spin.setDecimals(1)
        self._interval_spin.setSingleStep(1.0)
        self._interval_spin.setFixedWidth(80)
        row1.addWidget(self._interval_spin)

        self._interval_unit = QComboBox()
        self._interval_unit.addItems(["seconds", "minutes"])
        self._interval_unit.setFixedWidth(90)
        row1.addWidget(self._interval_unit)

        row1.addSpacing(16)

        row1.addWidget(QLabel("Format:"))
        self._format_combo = QComboBox()
        self._format_combo.addItems(["PNG", "TIFF"])
        self._format_combo.setFixedWidth(70)
        row1.addWidget(self._format_combo)

        row1.addSpacing(16)

        row1.addWidget(QLabel("Output:"))
        self._output_dir_edit = QLineEdit()
        default_dir = str(Path.home() / "timelapse_output")
        self._output_dir_edit.setText(default_dir)
        self._output_dir_edit.setReadOnly(True)
        self._output_dir_edit.setToolTip(
            "Parent folder for timelapse sessions.\n"
            "Each session creates a timestamped subfolder inside this directory\n"
            "(e.g. session_20260324_143052/)."
        )
        row1.addWidget(self._output_dir_edit, stretch=1)

        self._browse_btn = QPushButton("Browse...")
        self._browse_btn.setFixedWidth(75)
        self._browse_btn.clicked.connect(self._on_browse_clicked)
        row1.addWidget(self._browse_btn)

        outer.addLayout(row1)

        # Row 2: stop condition
        row2 = QHBoxLayout()

        row2.addWidget(QLabel("Stop after:"))
        self._stop_mode_combo = QComboBox()
        self._stop_mode_combo.addItems([
            "Manual",        # index 0
            "Duration",      # index 1
            "Clock time",    # index 2
            "Frame count",   # index 3
        ])
        self._stop_mode_combo.setFixedWidth(110)
        self._stop_mode_combo.currentIndexChanged.connect(
            self._on_stop_mode_changed
        )
        row2.addWidget(self._stop_mode_combo)

        # Stacked widget for mode-specific inputs
        self._stop_params_stack = QStackedWidget()
        self._stop_params_stack.setFixedHeight(28)

        # Page 0: Manual — empty placeholder
        self._stop_params_stack.addWidget(QLabel("  (stop manually)"))

        # Page 1: Duration — value + unit
        duration_widget = QWidget()
        duration_layout = QHBoxLayout(duration_widget)
        duration_layout.setContentsMargins(0, 0, 0, 0)
        self._duration_spin = QDoubleSpinBox()
        self._duration_spin.setRange(0.1, 9999.0)
        self._duration_spin.setValue(1.0)
        self._duration_spin.setDecimals(1)
        self._duration_spin.setSingleStep(0.5)
        self._duration_spin.setFixedWidth(80)
        duration_layout.addWidget(self._duration_spin)
        self._duration_unit = QComboBox()
        self._duration_unit.addItems(["minutes", "hours"])
        self._duration_unit.setFixedWidth(80)
        duration_layout.addWidget(self._duration_unit)
        duration_layout.addStretch()
        self._stop_params_stack.addWidget(duration_widget)

        # Page 2: Clock time — time picker
        clock_widget = QWidget()
        clock_layout = QHBoxLayout(clock_widget)
        clock_layout.setContentsMargins(0, 0, 0, 0)
        clock_layout.addWidget(QLabel("Stop at:"))
        self._clock_time_edit = QTimeEdit()
        self._clock_time_edit.setDisplayFormat("HH:mm")
        self._clock_time_edit.setFixedWidth(80)
        # Default to 1 hour from now
        default_stop = QTime.currentTime().addSecs(3600)
        self._clock_time_edit.setTime(default_stop)
        clock_layout.addWidget(self._clock_time_edit)
        clock_layout.addStretch()
        self._stop_params_stack.addWidget(clock_widget)

        # Page 3: Frame count — spinbox
        frames_widget = QWidget()
        frames_layout = QHBoxLayout(frames_widget)
        frames_layout.setContentsMargins(0, 0, 0, 0)
        self._frame_count_spin = QSpinBox()
        self._frame_count_spin.setRange(1, 999999)
        self._frame_count_spin.setValue(100)
        self._frame_count_spin.setFixedWidth(90)
        frames_layout.addWidget(self._frame_count_spin)
        frames_layout.addWidget(QLabel("frames"))
        frames_layout.addStretch()
        self._stop_params_stack.addWidget(frames_widget)

        row2.addWidget(self._stop_params_stack, stretch=1)

        # Estimated duration label (updates live as settings change)
        self._estimate_label = QLabel("")
        self._estimate_label.setStyleSheet("color: #666; font-style: italic;")
        row2.addWidget(self._estimate_label)

        outer.addLayout(row2)

        # Connect signals to update the estimate whenever settings change
        # (Note: _stop_mode_combo is already connected to _on_stop_mode_changed
        # above, which calls _update_duration_estimate, so no need to connect
        # it again here.)
        self._duration_spin.valueChanged.connect(self._update_duration_estimate)
        self._duration_unit.currentIndexChanged.connect(
            self._update_duration_estimate
        )
        self._clock_time_edit.timeChanged.connect(self._update_duration_estimate)
        self._frame_count_spin.valueChanged.connect(
            self._update_duration_estimate
        )
        self._interval_spin.valueChanged.connect(self._update_duration_estimate)
        self._interval_unit.currentIndexChanged.connect(
            self._update_duration_estimate
        )

        # Row 3: start, pause, stop, capture-now
        row3 = QHBoxLayout()

        self._start_btn = QPushButton("▶  Start Timelapse")
        self._start_btn.setFixedWidth(150)
        self._start_btn.clicked.connect(self._on_start_clicked)
        row3.addWidget(self._start_btn)

        self._pause_btn = QPushButton("⏸  Pause")
        self._pause_btn.setFixedWidth(100)
        self._pause_btn.setEnabled(False)
        self._pause_btn.clicked.connect(self._on_pause_clicked)
        row3.addWidget(self._pause_btn)

        self._stop_btn = QPushButton("■  Stop")
        self._stop_btn.setFixedWidth(90)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        row3.addWidget(self._stop_btn)

        row3.addSpacing(20)

        self._capture_now_btn = QPushButton("📷  Capture Now")
        self._capture_now_btn.setFixedWidth(130)
        self._capture_now_btn.clicked.connect(self._on_capture_now_clicked)
        row3.addWidget(self._capture_now_btn)

        row3.addStretch()
        outer.addLayout(row3)

        return group

    def _on_stop_mode_changed(self, index: int):
        """Switch the visible stop-condition parameter widget."""
        self._stop_params_stack.setCurrentIndex(index)
        self._update_duration_estimate()

    def _update_duration_estimate(self):
        """Update the estimated duration label based on current settings."""
        mode_index = self._stop_mode_combo.currentIndex()

        if mode_index == 0:  # Manual
            self._estimate_label.setText("")
            return

        elif mode_index == 1:  # Duration
            value = self._duration_spin.value()
            unit = self._duration_unit.currentText()
            if unit == "hours":
                total_seconds = value * 3600
            else:
                total_seconds = value * 60

        elif mode_index == 2:  # Clock time
            qt_time = self._clock_time_edit.time()
            now = datetime.now()
            stop_at = now.replace(
                hour=qt_time.hour(),
                minute=qt_time.minute(),
                second=0,
                microsecond=0,
            )
            if stop_at <= now:
                stop_at += timedelta(days=1)
            total_seconds = (stop_at - now).total_seconds()

        elif mode_index == 3:  # Frame count
            max_frames = self._frame_count_spin.value()
            interval = self._get_interval_seconds()
            # First frame is captured immediately; only (max_frames - 1)
            # waits occur between captures.
            total_seconds = (max_frames - 1) * interval if max_frames > 1 else 0

        else:
            self._estimate_label.setText("")
            return

        # Format the estimate
        self._estimate_label.setText(f"≈ {self._format_duration(total_seconds)}")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format seconds into a human-readable duration string."""
        total = int(seconds)
        if total < 60:
            return f"{total}s"
        elif total < 3600:
            m, s = divmod(total, 60)
            return f"{m}m {s:02d}s"
        else:
            h, remainder = divmod(total, 3600)
            m, _ = divmod(remainder, 60)
            return f"{h}h {m:02d}m"

    def _on_pause_clicked(self):
        """Toggle pause/resume on the capture worker."""
        if self._capture_worker is not None:
            self._capture_worker.toggle_pause()

    def _build_status_row(self) -> QGroupBox:
        """Build the session status display."""
        group = QGroupBox("Session Status")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        row = QHBoxLayout(group)

        row.addWidget(QLabel("Frames:"))
        self._frame_count_label = QLabel("0")
        self._frame_count_label.setStyleSheet("font-weight: bold;")
        row.addWidget(self._frame_count_label)

        row.addSpacing(20)

        row.addWidget(QLabel("Next capture in:"))
        self._countdown_label = QLabel("—")
        self._countdown_label.setStyleSheet("font-weight: bold;")
        self._countdown_label.setMinimumWidth(60)
        row.addWidget(self._countdown_label)

        row.addSpacing(20)

        row.addWidget(QLabel("Remaining:"))
        self._remaining_label = QLabel("—")
        self._remaining_label.setStyleSheet("font-weight: bold;")
        self._remaining_label.setMinimumWidth(100)
        row.addWidget(self._remaining_label)

        row.addSpacing(20)

        row.addWidget(QLabel("Elapsed:"))
        self._elapsed_label = QLabel("—")
        self._elapsed_label.setStyleSheet("font-weight: bold;")
        row.addWidget(self._elapsed_label)

        row.addSpacing(20)

        row.addWidget(QLabel("Session:"))
        self._session_dir_label = QLabel("—")
        self._session_dir_label.setStyleSheet("color: #666;")
        row.addWidget(self._session_dir_label, stretch=1)

        return group

    def _build_preview_area(self) -> QWidget:
        """Build the live preview display area."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        self._preview_label = QLabel("Connect camera to see live preview")
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setStyleSheet(
            "QLabel {"
            "  background-color: #1a1a1a;"
            "  color: #888;"
            "  font-size: 14px;"
            "  border: 1px solid #333;"
            "}"
        )
        self._preview_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        layout.addWidget(self._preview_label)

        return container

    # =========================================================================
    # UI State Management
    # =========================================================================

    def _update_ui_state(self):
        """Update button enable/disable states based on current state."""
        connected = self._camera.is_connected
        capturing = self._is_capturing

        # Connection
        self._connect_btn.setText("Disconnect" if connected else "Connect")
        self._connect_btn.setEnabled(not capturing)
        self._status_dot.setStyleSheet(
            f"background-color: {'#4CAF50' if connected else 'gray'}; "
            f"border-radius: 7px; border: 1px solid #555;"
        )
        self._connection_label.setText(
            "Connected" if connected else "Not connected"
        )

        # Camera info
        if connected:
            info = self._camera.camera_info
            self._model_label.setText(info.get("model", "—"))
            w = info.get("width", "?")
            h = info.get("height", "?")
            self._resolution_label.setText(f"{w} × {h}")
        else:
            self._model_label.setText("—")
            self._resolution_label.setText("—")

        # Capture controls
        self._start_btn.setEnabled(connected and not capturing)
        self._pause_btn.setEnabled(capturing)
        self._stop_btn.setEnabled(capturing)
        self._capture_now_btn.setEnabled(connected and not capturing)
        self._interval_spin.setEnabled(not capturing)
        self._interval_unit.setEnabled(not capturing)
        self._format_combo.setEnabled(not capturing)
        self._browse_btn.setEnabled(not capturing)
        self._stop_mode_combo.setEnabled(not capturing)
        self._duration_spin.setEnabled(not capturing)
        self._duration_unit.setEnabled(not capturing)
        self._clock_time_edit.setEnabled(not capturing)
        self._frame_count_spin.setEnabled(not capturing)

        # Reset pause button text when not capturing
        if not capturing:
            self._pause_btn.setText("⏸  Pause")

    # =========================================================================
    # Connection
    # =========================================================================

    def _on_connect_clicked(self):
        """Handle connect / disconnect button."""
        if self._camera.is_connected:
            self._disconnect_camera()
        else:
            self._connect_camera()

    def _connect_camera(self):
        """Attempt to connect to the camera."""
        try:
            self._camera.connect()
            self._statusbar.showMessage("Camera connected", 3000)
            self._start_preview()
        except CameraNotAvailableError:
            QMessageBox.critical(
                self, "pyueye Not Available",
                "The pyueye library is not installed.\n"
                "It only works on Windows and Linux.",
            )
        except CameraError as e:
            QMessageBox.critical(
                self, "Connection Failed", f"Could not connect to camera:\n{e}"
            )
        finally:
            self._update_ui_state()

    def _disconnect_camera(self):
        """Disconnect from the camera."""
        self._stop_preview()
        self._camera.disconnect()
        self._preview_label.setText("Connect camera to see live preview")
        self._preview_label.setPixmap(QPixmap())  # clear any image
        self._statusbar.showMessage("Camera disconnected", 3000)
        self._update_ui_state()

    # =========================================================================
    # Live Preview
    # =========================================================================

    def _start_preview(self):
        """Start the live preview refresh timer."""
        interval_ms = int(1000 / self._preview_fps)
        self._preview_timer.start(interval_ms)
        logger.debug(f"Preview timer started ({self._preview_fps} fps)")

    def _stop_preview(self):
        """Stop the live preview refresh timer."""
        self._preview_timer.stop()
        logger.debug("Preview timer stopped")

    @pyqtSlot()
    def _refresh_preview(self):
        """Fetch a frame from the camera and display it in the preview label."""
        if not self._camera.is_connected:
            return

        try:
            frame = self._camera.get_frame()
        except Exception as e:
            logger.warning(f"Preview frame error: {e}")
            return

        if frame is None:
            return

        self._display_frame(frame)

    def _display_frame(self, frame: np.ndarray):
        """Convert a numpy frame to QPixmap and display it, scaled to fit.

        Accounts for high-DPI displays by using the label's device pixel
        ratio so the image renders at full sharpness on Retina/HiDPI screens.
        """
        h, w = frame.shape[:2]

        # Grayscale -> QImage
        if frame.ndim == 2:
            qimg = QImage(
                frame.data, w, h, w, QImage.Format_Grayscale8
            )
        else:
            # Shouldn't happen for our mono camera, but handle just in case
            bytes_per_line = frame.shape[1] * frame.shape[2]
            qimg = QImage(
                frame.data, w, h, bytes_per_line, QImage.Format_RGB888
            )

        pixmap = QPixmap.fromImage(qimg)

        # Scale to fit the label while preserving aspect ratio.
        # On high-DPI screens, the label's logical size differs from its
        # physical pixel size. We scale to the physical size for sharpness,
        # then set the device pixel ratio so Qt knows the true dimensions.
        dpr = self._preview_label.devicePixelRatioF()
        label_size = self._preview_label.size()
        physical_size = QSize(
            int(label_size.width() * dpr),
            int(label_size.height() * dpr),
        )
        scaled = pixmap.scaled(
            physical_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        scaled.setDevicePixelRatio(dpr)
        self._preview_label.setPixmap(scaled)

    # =========================================================================
    # Capture Controls
    # =========================================================================

    def _get_interval_seconds(self) -> float:
        """Get the capture interval in seconds from the UI controls."""
        value = self._interval_spin.value()
        if self._interval_unit.currentText() == "minutes":
            value *= 60.0
        return value

    def _on_browse_clicked(self):
        """Open a directory picker for the output directory."""
        current = self._output_dir_edit.text()
        chosen = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", current
        )
        if chosen:
            self._output_dir_edit.setText(chosen)

    def _on_start_clicked(self):
        """Start a timelapse capture session."""
        if not self._camera.is_connected:
            QMessageBox.warning(
                self, "No Camera", "Please connect the camera first."
            )
            return

        interval = self._get_interval_seconds()
        output_dir = self._output_dir_edit.text()
        image_format = self._format_combo.currentText().lower()

        if not output_dir:
            QMessageBox.warning(
                self, "No Output Directory",
                "Please select an output directory.",
            )
            return

        # Build stop condition from UI
        stop_condition = self._build_stop_condition()
        if stop_condition is None:
            return  # validation failed, message already shown

        # Create and configure worker
        self._capture_worker = CaptureWorker(
            camera=self._camera,
            output_dir=output_dir,
            interval_seconds=interval,
            image_format=image_format,
            stop_condition=stop_condition,
            parent=self,
        )

        # Connect signals
        self._capture_worker.image_captured.connect(self._on_image_captured)
        self._capture_worker.countdown_tick.connect(self._on_countdown_tick)
        self._capture_worker.remaining_updated.connect(self._on_remaining_updated)
        self._capture_worker.paused_changed.connect(self._on_paused_changed)
        self._capture_worker.error_occurred.connect(self._on_capture_error)
        self._capture_worker.session_started.connect(self._on_session_started)
        self._capture_worker.session_finished.connect(self._on_session_finished)

        # Start
        self._is_capturing = True
        self._session_start_time = datetime.now()
        self._estimate_label.setText("")  # hide estimate while running
        self._elapsed_timer.start(1000)
        self._capture_worker.start()
        self._update_ui_state()

        mode_label = self._stop_mode_combo.currentText()
        self._statusbar.showMessage(
            f"Timelapse started (every {interval:.1f}s, stop: {mode_label})",
            5000,
        )

    def _build_stop_condition(self) -> Optional[dict]:
        """Build a stop condition dict from the current UI state.

        Returns:
            Stop condition dict, or None if validation fails.
        """
        mode_index = self._stop_mode_combo.currentIndex()

        if mode_index == 0:  # Manual
            return {"mode": STOP_MANUAL}

        elif mode_index == 1:  # Duration
            value = self._duration_spin.value()
            unit = self._duration_unit.currentText()
            if unit == "hours":
                seconds = value * 3600
            else:
                seconds = value * 60
            return {"mode": STOP_DURATION, "seconds": seconds}

        elif mode_index == 2:  # Clock time
            qt_time = self._clock_time_edit.time()
            now = datetime.now()
            stop_at = now.replace(
                hour=qt_time.hour(),
                minute=qt_time.minute(),
                second=0,
                microsecond=0,
            )
            # If the chosen time is already past, assume tomorrow
            if stop_at <= now:
                from datetime import timedelta
                stop_at += timedelta(days=1)
            return {"mode": STOP_CLOCK_TIME, "stop_at": stop_at}

        elif mode_index == 3:  # Frame count
            max_frames = self._frame_count_spin.value()
            return {"mode": STOP_FRAME_COUNT, "max_frames": max_frames}

        return {"mode": STOP_MANUAL}

    def _on_stop_clicked(self):
        """Stop the current timelapse session."""
        if self._capture_worker is not None:
            self._capture_worker.request_stop()
            self._statusbar.showMessage("Stopping timelapse...", 3000)

    def _on_capture_now_clicked(self):
        """Capture a single test image (not part of a timelapse session)."""
        if not self._camera.is_connected:
            return

        try:
            image, metadata = self._camera.capture_image()
        except Exception as e:
            QMessageBox.warning(
                self, "Capture Failed", f"Could not capture image:\n{e}"
            )
            return

        if image is None:
            self._statusbar.showMessage("Capture returned no image", 3000)
            return

        # Display the captured frame
        self._display_frame(image)

        # Ask where to save
        fmt = self._format_combo.currentText().lower()
        filter_str = (
            "PNG Files (*.png);;TIFF Files (*.tiff *.tif)"
            if fmt == "png"
            else "TIFF Files (*.tiff *.tif);;PNG Files (*.png)"
        )
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Captured Image", "", filter_str
        )
        if filepath:
            try:
                CameraController.save_image(image, filepath)
                self._statusbar.showMessage(f"Image saved: {filepath}", 5000)
            except Exception as e:
                QMessageBox.warning(
                    self, "Save Failed", f"Could not save image:\n{e}"
                )

    # =========================================================================
    # Capture Worker Signal Handlers
    # =========================================================================

    @pyqtSlot(int, str)
    def _on_image_captured(self, frame_number: int, filename: str):
        """Handle a newly captured frame from the worker."""
        self._frame_count_label.setText(str(frame_number))
        self._statusbar.showMessage(f"Captured: {filename}", 2000)

    @pyqtSlot(float)
    def _on_countdown_tick(self, seconds_remaining: float):
        """Update the countdown display."""
        if seconds_remaining <= 0:
            self._countdown_label.setText("now")
        elif seconds_remaining < 60:
            self._countdown_label.setText(f"{seconds_remaining:.0f}s")
        else:
            mins = int(seconds_remaining) // 60
            secs = int(seconds_remaining) % 60
            self._countdown_label.setText(f"{mins}m {secs:02d}s")

    @pyqtSlot(str)
    def _on_remaining_updated(self, remaining_text: str):
        """Update the remaining time/frames display."""
        self._remaining_label.setText(remaining_text)

    @pyqtSlot(bool)
    def _on_paused_changed(self, is_paused: bool):
        """Handle pause state change from the worker."""
        if is_paused:
            self._pause_btn.setText("▶  Resume")
            self._countdown_label.setText("paused")
            self._statusbar.showMessage("Timelapse paused", 5000)
        else:
            self._pause_btn.setText("⏸  Pause")
            self._statusbar.showMessage("Timelapse resumed", 3000)

    @pyqtSlot(str)
    def _on_capture_error(self, error_msg: str):
        """Handle an error from the capture worker."""
        logger.error(f"Capture error: {error_msg}")
        self._statusbar.showMessage(f"Error: {error_msg}", 5000)

    @pyqtSlot(str)
    def _on_session_started(self, session_dir: str):
        """Handle session start — display session directory."""
        self._current_session_dir = Path(session_dir)
        self._open_session_action.setEnabled(True)

        # Show just the session folder name, not the full path
        folder_name = self._current_session_dir.name
        self._session_dir_label.setText(folder_name)
        self._session_dir_label.setToolTip(session_dir)

    @pyqtSlot(int)
    def _on_session_finished(self, total_frames: int):
        """Handle session completion."""
        self._is_capturing = False
        self._elapsed_timer.stop()
        self._countdown_label.setText("—")
        self._remaining_label.setText("—")
        self._update_ui_state()

        session_dir = ""
        if self._capture_worker is not None and self._capture_worker.session_dir:
            session_dir = str(self._capture_worker.session_dir)

        self._capture_worker = None

        self._statusbar.showMessage(
            f"Timelapse complete: {total_frames} frames", 10000
        )

        QMessageBox.information(
            self,
            "Timelapse Complete",
            f"Captured {total_frames} frames.\n\n"
            f"Saved to:\n{session_dir}",
        )

    # =========================================================================
    # Elapsed Time
    # =========================================================================

    @pyqtSlot()
    def _update_elapsed_time(self):
        """Update the elapsed time display (called every second).

        Shows wall-clock elapsed time, plus paused time if any.
        """
        if self._session_start_time is None:
            return

        elapsed = datetime.now() - self._session_start_time
        total_secs = int(elapsed.total_seconds())
        hours, remainder = divmod(total_secs, 3600)
        minutes, seconds = divmod(remainder, 60)
        elapsed_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        # Show paused time if the worker has accumulated any
        if self._capture_worker is not None:
            paused = self._capture_worker.total_paused_seconds
            if paused >= 1.0:
                elapsed_str += f"  (paused: {self._format_duration(paused)})"

        self._elapsed_label.setText(elapsed_str)

    # =========================================================================
    # Window Close
    # =========================================================================

    def closeEvent(self, event):
        """Handle window close — clean up camera and worker."""
        # Stop capture if running
        if self._capture_worker is not None and self._capture_worker.isRunning():
            self._capture_worker.request_stop()
            self._capture_worker.wait(3000)

        # Stop preview
        self._stop_preview()
        self._elapsed_timer.stop()

        # Disconnect camera
        if self._camera.is_connected:
            self._camera.disconnect()

        event.accept()