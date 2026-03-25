"""
Camera controller for IDS uEye cameras.

Simplified, self-contained controller for timelapse capture.
Adapted from the trihelmcontrol project's CameraController.

The camera operates in continuous streaming mode (free run). Frames are
captured to a host memory buffer and can be read on-demand for either
live preview or timed capture.

Requires the pyueye library (Windows and Linux only).
"""

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

# Attempt to import pyueye
try:
    from pyueye import ueye
    PYUEYE_AVAILABLE = True
except ImportError:
    PYUEYE_AVAILABLE = False

# Attempt to import PIL for image saving
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================

class CameraError(Exception):
    """Base exception for camera-related errors."""
    pass


class CameraNotAvailableError(CameraError):
    """Raised when pyueye library is not available."""
    pass


class CameraConnectionError(CameraError):
    """Raised when camera connection fails."""
    pass


class CameraConfigurationError(CameraError):
    """Raised when camera configuration fails."""
    pass


class CameraOperationError(CameraError):
    """Raised when a camera operation fails."""
    pass


# =============================================================================
# Camera Controller
# =============================================================================

class CameraController:
    """Controller for IDS uEye cameras.

    Provides connection, frame capture, and image saving for timelapse use.

    The camera operates in continuous streaming mode once connected.
    Frames can be read on-demand via get_frame() or capture_image().

    Example usage:
        controller = CameraController()
        controller.connect()

        frame = controller.get_frame()           # raw frame
        image, meta = controller.capture_image()  # frame + metadata

        controller.disconnect()
    """

    def __init__(self):
        """Initialize the camera controller."""
        if not PYUEYE_AVAILABLE:
            logger.warning(
                "pyueye library not available - camera functions will not work"
            )

        # Connection state
        self._is_connected = False
        self._is_streaming = False

        # Camera handles and memory (pyueye types)
        self._hCam = None
        self._pcImageMemory = None
        self._MemID = None
        self._pitch = None

        # Image parameters
        self._width = 0
        self._height = 0
        self._bits_per_pixel = 8  # Monochrome
        self._bytes_per_pixel = 1

        # Camera info (populated on connect)
        self._camera_info: Dict[str, Any] = {}

        # Thread safety for frame reads
        self._frame_lock = threading.Lock()

        logger.debug("CameraController initialized")

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def is_connected(self) -> bool:
        """Whether camera is connected and streaming."""
        return self._is_connected and self._is_streaming

    @property
    def camera_info(self) -> Dict[str, Any]:
        """Camera information (model, serial, resolution, etc.).

        Returns empty dict if not connected.
        """
        return self._camera_info.copy()

    @property
    def frame_width(self) -> int:
        """Image width in pixels (0 if not connected)."""
        if isinstance(self._width, int):
            return self._width
        return self._width.value if self._is_connected else 0

    @property
    def frame_height(self) -> int:
        """Image height in pixels (0 if not connected)."""
        if isinstance(self._height, int):
            return self._height
        return self._height.value if self._is_connected else 0

    # =========================================================================
    # Connection Management
    # =========================================================================

    def connect(self, camera_id: int = 0) -> bool:
        """Connect to camera and start streaming.

        Args:
            camera_id: Camera ID to connect to. 0 = first available.

        Returns:
            True if connection successful.

        Raises:
            CameraNotAvailableError: If pyueye is not installed.
            CameraConnectionError: If connection to camera fails.
            CameraConfigurationError: If camera configuration fails.
        """
        if not PYUEYE_AVAILABLE:
            raise CameraNotAvailableError(
                "pyueye library is not available. "
                "This library only works on Windows and Linux."
            )

        if self._is_connected:
            logger.warning("Camera already connected, disconnecting first")
            self.disconnect()

        logger.info(f"Connecting to camera (ID: {camera_id})...")

        try:
            self._hCam = ueye.HIDS(camera_id)

            nRet = ueye.is_InitCamera(self._hCam, None)
            if nRet != ueye.IS_SUCCESS:
                raise CameraConnectionError(
                    f"Failed to initialize camera (error code: {nRet})"
                )

            logger.debug("Camera initialized successfully")

            self._read_camera_info()
            self._configure_camera()
            self._setup_capture()

            self._is_connected = True
            logger.info(
                f"Connected to camera: "
                f"{self._camera_info.get('model', 'Unknown')}"
            )
            return True

        except CameraError:
            self._cleanup_on_error()
            raise
        except Exception as e:
            self._cleanup_on_error()
            raise CameraConnectionError(
                f"Unexpected error connecting to camera: {e}"
            )

    def disconnect(self):
        """Disconnect from camera and release all resources."""
        logger.info("Disconnecting from camera...")

        # Stop capture
        if self._is_streaming and self._hCam is not None:
            try:
                ueye.is_StopLiveVideo(self._hCam, ueye.IS_FORCE_VIDEO_STOP)
                self._is_streaming = False
                logger.debug("Stopped live video")
            except Exception as e:
                logger.warning(f"Error stopping live video: {e}")

        # Free image memory
        if self._pcImageMemory is not None and self._hCam is not None:
            try:
                ueye.is_FreeImageMem(
                    self._hCam, self._pcImageMemory, self._MemID
                )
                logger.debug("Freed image memory")
            except Exception as e:
                logger.warning(f"Error freeing image memory: {e}")
            self._pcImageMemory = None
            self._MemID = None

        # Close camera
        if self._hCam is not None:
            try:
                ueye.is_ExitCamera(self._hCam)
                logger.debug("Camera closed")
            except Exception as e:
                logger.warning(f"Error closing camera: {e}")
            self._hCam = None

        self._is_connected = False
        self._camera_info = {}
        logger.info("Camera disconnected")

    # =========================================================================
    # Internal Setup
    # =========================================================================

    def _read_camera_info(self):
        """Read camera and sensor information."""
        cInfo = ueye.CAMINFO()
        nRet = ueye.is_GetCameraInfo(self._hCam, cInfo)
        if nRet != ueye.IS_SUCCESS:
            logger.warning(
                f"Failed to get camera info (error code: {nRet})"
            )

        sInfo = ueye.SENSORINFO()
        nRet = ueye.is_GetSensorInfo(self._hCam, sInfo)
        if nRet != ueye.IS_SUCCESS:
            raise CameraConfigurationError(
                f"Failed to get sensor info (error code: {nRet})"
            )

        self._camera_info = {
            "model": sInfo.strSensorName.decode("utf-8"),
            "serial": cInfo.SerNo.decode("utf-8"),
            "max_width": sInfo.nMaxWidth.value,
            "max_height": sInfo.nMaxHeight.value,
        }
        logger.debug(f"Camera info: {self._camera_info}")

    def _configure_camera(self):
        """Configure camera settings (monochrome, full sensor, auto-exposure)."""
        # Reset to defaults
        nRet = ueye.is_ResetToDefault(self._hCam)
        if nRet != ueye.IS_SUCCESS:
            logger.warning(
                f"Failed to reset camera to defaults (error code: {nRet})"
            )

        # DIB display mode
        nRet = ueye.is_SetDisplayMode(self._hCam, ueye.IS_SET_DM_DIB)
        if nRet != ueye.IS_SUCCESS:
            raise CameraConfigurationError(
                f"Failed to set display mode (error code: {nRet})"
            )

        # Monochrome 8-bit
        nRet = ueye.is_SetColorMode(self._hCam, ueye.IS_CM_MONO8)
        if nRet != ueye.IS_SUCCESS:
            raise CameraConfigurationError(
                f"Failed to set color mode (error code: {nRet})"
            )

        self._bits_per_pixel = 8
        self._bytes_per_pixel = 1

        # Full sensor AOI
        rectAOI = ueye.IS_RECT()
        nRet = ueye.is_AOI(
            self._hCam, ueye.IS_AOI_IMAGE_GET_AOI,
            rectAOI, ueye.sizeof(rectAOI),
        )
        if nRet != ueye.IS_SUCCESS:
            raise CameraConfigurationError(
                f"Failed to get AOI (error code: {nRet})"
            )

        self._width = rectAOI.s32Width
        self._height = rectAOI.s32Height

        self._camera_info["width"] = self._width.value
        self._camera_info["height"] = self._height.value
        self._camera_info["bits_per_pixel"] = self._bits_per_pixel

        logger.debug(
            f"Camera configured: "
            f"{self._width}x{self._height}, {self._bits_per_pixel}bpp"
        )

    def _setup_capture(self):
        """Allocate memory and start continuous capture with auto-exposure."""
        # Allocate image memory
        self._pcImageMemory = ueye.c_mem_p()
        self._MemID = ueye.int()

        nRet = ueye.is_AllocImageMem(
            self._hCam,
            self._width,
            self._height,
            ueye.INT(self._bits_per_pixel),
            self._pcImageMemory,
            self._MemID,
        )
        if nRet != ueye.IS_SUCCESS:
            raise CameraConfigurationError(
                f"Failed to allocate image memory (error code: {nRet})"
            )

        nRet = ueye.is_SetImageMem(
            self._hCam, self._pcImageMemory, self._MemID
        )
        if nRet != ueye.IS_SUCCESS:
            raise CameraConfigurationError(
                f"Failed to set image memory (error code: {nRet})"
            )

        # Enable auto exposure
        nRet = ueye.is_SetAutoParameter(
            self._hCam,
            ueye.IS_SET_ENABLE_AUTO_SHUTTER,
            ueye.c_double(1),
            ueye.c_double(0),
        )
        if nRet != ueye.IS_SUCCESS:
            logger.warning(
                f"Failed to enable auto exposure (error code: {nRet})"
            )

        # Get pitch (bytes per row, may include padding)
        self._pitch = ueye.INT()
        nRet = ueye.is_InquireImageMem(
            self._hCam,
            self._pcImageMemory,
            self._MemID,
            self._width,
            self._height,
            ueye.INT(self._bits_per_pixel),
            self._pitch,
        )
        if nRet != ueye.IS_SUCCESS:
            raise CameraConfigurationError(
                f"Failed to inquire image memory (error code: {nRet})"
            )

        # Start live video (continuous capture)
        nRet = ueye.is_CaptureVideo(self._hCam, ueye.IS_DONT_WAIT)
        if nRet != ueye.IS_SUCCESS:
            raise CameraConfigurationError(
                f"Failed to start live video (error code: {nRet})"
            )

        self._is_streaming = True
        logger.debug("Capture started (continuous streaming mode)")

    def _cleanup_on_error(self):
        """Clean up resources after a failed connection attempt."""
        if self._pcImageMemory is not None and self._hCam is not None:
            try:
                ueye.is_FreeImageMem(
                    self._hCam, self._pcImageMemory, self._MemID
                )
            except Exception:
                pass
            self._pcImageMemory = None
            self._MemID = None

        if self._hCam is not None:
            try:
                ueye.is_ExitCamera(self._hCam)
            except Exception:
                pass
            self._hCam = None

        self._is_connected = False
        self._is_streaming = False

    # =========================================================================
    # Frame Capture
    # =========================================================================

    def get_frame(self) -> Optional[np.ndarray]:
        """Get current frame from camera buffer.

        Returns:
            Numpy array (grayscale, uint8, full resolution) or None.
            The returned array is a copy — caller owns it.

        Raises:
            CameraOperationError: If frame read fails.
        """
        if not self.is_connected:
            return None

        with self._frame_lock:
            try:
                array = ueye.get_data(
                    self._pcImageMemory,
                    self._width.value,
                    self._height.value,
                    self._bits_per_pixel,
                    self._pitch.value,
                    copy=False,
                )

                frame = np.reshape(
                    array,
                    (self._height.value, self._width.value, self._bytes_per_pixel),
                )

                if self._bytes_per_pixel == 1:
                    frame = frame.squeeze(axis=2)

                return frame.copy()

            except Exception as e:
                raise CameraOperationError(f"Failed to read frame: {e}")

    def capture_image(self) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        """Capture image with metadata.

        Returns:
            (image_array, metadata_dict), or (None, {}) on failure.

        Metadata keys:
            timestamp, timestamp_unix, width, height,
            bits_per_pixel, camera_model, camera_serial
        """
        if not self.is_connected:
            logger.warning("Cannot capture image - camera not connected")
            return None, {}

        capture_time = datetime.now()
        frame = self.get_frame()

        if frame is None:
            return None, {}

        metadata = {
            "timestamp": capture_time.isoformat(),
            "timestamp_unix": capture_time.timestamp(),
            "width": self._width.value,
            "height": self._height.value,
            "bits_per_pixel": self._bits_per_pixel,
            "camera_model": self._camera_info.get("model", "Unknown"),
            "camera_serial": self._camera_info.get("serial", "Unknown"),
        }

        logger.debug(f"Image captured at {capture_time.isoformat()}")
        return frame, metadata

    # =========================================================================
    # Image Saving
    # =========================================================================

    @staticmethod
    def save_image(image: np.ndarray, filepath: str) -> bool:
        """Save an image to file using Pillow.

        Args:
            image: Numpy array containing the image data.
            filepath: Path to save (extension determines format: .png, .tiff).

        Returns:
            True if save successful.

        Raises:
            CameraOperationError: If Pillow is not available or save fails.
        """
        if not PIL_AVAILABLE:
            raise CameraOperationError(
                "Pillow (PIL) is not available - cannot save image"
            )

        try:
            img = Image.fromarray(image)
            img.save(filepath)
            logger.debug(f"Image saved to {filepath}")
            return True
        except Exception as e:
            raise CameraOperationError(f"Failed to save image: {e}")

    # =========================================================================
    # Context Manager
    # =========================================================================

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    def __del__(self):
        if self._is_connected:
            try:
                self.disconnect()
            except Exception:
                pass