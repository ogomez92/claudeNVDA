# ClauVDA NVDA Add-on - Video Capture Module
# -*- coding: utf-8 -*-

"""
Screen video capture for Claude AI analysis.

Claude's Messages API doesn't accept video files directly — we record to mp4
with imageio-ffmpeg, then sample still frames to send as images.
"""

import os
import sys
import threading
import time
from datetime import datetime
from logHandler import log

# Add lib directory to path
from .consts import LIBS_DIR

if LIBS_DIR not in sys.path:
    sys.path.insert(0, LIBS_DIR)

log.info(f"videocapture LIBS_DIR: {LIBS_DIR}")
log.info(f"videocapture LIBS_DIR exists: {os.path.exists(LIBS_DIR)}")

try:
    import mss
    import mss.tools
    MSS_AVAILABLE = True
    log.info("mss loaded successfully")
except ImportError as e:
    MSS_AVAILABLE = False
    log.warning(f"mss not available for video capture: {e}")
except Exception as e:
    MSS_AVAILABLE = False
    log.error(f"mss import error: {e}", exc_info=True)

try:
    import imageio.v3 as iio
    IMAGEIO_AVAILABLE = True
    log.info("imageio.v3 loaded successfully")
except ImportError:
    try:
        import imageio as iio
        IMAGEIO_AVAILABLE = True
        log.info("imageio loaded successfully")
    except ImportError as e:
        IMAGEIO_AVAILABLE = False
        log.warning(f"imageio not available for video encoding: {e}")
    except Exception as e:
        IMAGEIO_AVAILABLE = False
        log.error(f"imageio import error: {e}", exc_info=True)
except Exception as e:
    IMAGEIO_AVAILABLE = False
    log.error(f"imageio.v3 import error: {e}", exc_info=True)


class VideoCapture:
    """Screen video capture handler."""

    def __init__(self, output_dir: str, fps: int = 10, max_duration: int = 60, scale: float = 0.5):
        """
        Initialize video capture.

        Args:
            output_dir: Directory to save video files
            fps: Frames per second (default 10 for smaller files)
            max_duration: Maximum recording duration in seconds (default 60)
            scale: Scale factor to reduce resolution (0.5 = half size for smaller files)
        """
        self.output_dir = output_dir
        self.fps = fps
        self.max_duration = max_duration
        self.scale = scale

        self._recording = False
        self._thread = None
        self._frames = []
        self._start_time = None
        self._output_path = None

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._recording

    @property
    def is_available(self) -> bool:
        """Check if video capture is available."""
        return MSS_AVAILABLE and IMAGEIO_AVAILABLE

    def start(self) -> bool:
        """
        Start recording screen.

        Returns:
            True if recording started successfully
        """
        if not self.is_available:
            log.error("Video capture not available - missing dependencies")
            return False

        if self._recording:
            log.warning("Already recording")
            return False

        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)

        # Generate output filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._output_path = os.path.join(self.output_dir, f"capture_{timestamp}.mp4")

        # Reset state
        self._frames = []
        self._start_time = time.time()
        self._recording = True

        # Start capture thread
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

        log.info(f"Started video recording to {self._output_path}")
        return True

    def stop(self) -> str | None:
        """
        Stop recording and save video.

        Returns:
            Path to saved video file, or None if failed
        """
        if not self._recording:
            log.warning("Not recording")
            return None

        self._recording = False

        # Wait for capture thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        # Save video
        if self._frames:
            try:
                return self._save_video()
            except Exception as e:
                log.error(f"Failed to save video: {e}", exc_info=True)
                return None
        else:
            log.warning("No frames captured")
            return None

    def _capture_loop(self):
        """Main capture loop - runs in background thread."""
        frame_interval = 1.0 / self.fps

        try:
            # Import PIL for resizing
            from PIL import Image
            import numpy as np

            with mss.mss() as sct:
                # Capture primary monitor
                monitor = sct.monitors[1]  # Primary monitor

                # Pre-calculate target size
                target_width = int(monitor["width"] * self.scale)
                target_height = int(monitor["height"] * self.scale)

                while self._recording:
                    loop_start = time.time()

                    # Check max duration
                    elapsed = time.time() - self._start_time
                    if elapsed >= self.max_duration:
                        log.info(f"Max recording duration reached ({self.max_duration}s)")
                        self._recording = False
                        break

                    # Capture frame
                    try:
                        img = sct.grab(monitor)

                        # Convert to PIL Image for resizing
                        pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")

                        # Resize to reduce file size
                        if self.scale < 1.0:
                            pil_img = pil_img.resize(
                                (target_width, target_height),
                                Image.Resampling.BILINEAR  # Fast resize for video
                            )

                        # Convert to numpy array
                        frame = np.array(pil_img)
                        self._frames.append(frame)
                    except Exception as e:
                        log.error(f"Frame capture error: {e}")

                    # Maintain frame rate
                    elapsed_frame = time.time() - loop_start
                    sleep_time = frame_interval - elapsed_frame
                    if sleep_time > 0:
                        time.sleep(sleep_time)

        except Exception as e:
            log.error(f"Capture loop error: {e}", exc_info=True)
            self._recording = False

    def _save_video(self) -> str:
        """Save captured frames to video file."""
        if not self._frames:
            raise ValueError("No frames to save")

        log.info(f"Saving {len(self._frames)} frames to video...")

        # Try different methods to save video
        saved = False
        last_error = None

        # Method 1: Use imageio-ffmpeg directly with writer
        try:
            import imageio_ffmpeg
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            log.info(f"Using ffmpeg from: {ffmpeg_path}")

            # Get frame dimensions from first frame
            height, width = self._frames[0].shape[:2]

            # Write using imageio-ffmpeg writer
            writer = imageio_ffmpeg.write_frames(
                self._output_path,
                (width, height),
                fps=self.fps,
                codec="libx264",
                pix_fmt_in="rgb24",
                pix_fmt_out="yuv420p",
            )
            writer.send(None)  # Initialize

            for frame in self._frames:
                writer.send(frame.tobytes())

            writer.close()
            saved = True
            log.info("Video saved using imageio-ffmpeg writer")
        except Exception as e:
            last_error = e
            log.warning(f"imageio-ffmpeg writer failed: {e}")

        # Method 2: Try imageio with auto-detection
        if not saved:
            try:
                iio.imwrite(
                    self._output_path,
                    self._frames,
                    fps=self.fps,
                )
                saved = True
                log.info("Video saved using imageio auto-detection")
            except Exception as e:
                last_error = e
                log.warning(f"imageio auto-detection failed: {e}")

        if not saved:
            raise RuntimeError(f"Failed to save video: {last_error}")

        # Clear frames to free memory
        self._frames = []

        log.info(f"Video saved to {self._output_path}")
        return self._output_path

    def get_duration(self) -> float:
        """Get current recording duration in seconds."""
        if self._start_time and self._recording:
            return time.time() - self._start_time
        return 0.0


# Default video analysis prompt
VIDEO_ANALYSIS_PROMPT = """Describe this video in detail, but concise. Get as much information as you can and if there is any important text in the video read it."""


# Global capture instance
_capture: VideoCapture | None = None


def get_capture(output_dir: str) -> VideoCapture:
    """Get or create the video capture instance."""
    global _capture
    if _capture is None:
        _capture = VideoCapture(output_dir)
    return _capture


def extract_frames(
    video_path: str,
    output_dir: str,
    max_frames: int = 12,
    max_dimension: int = 1024,
    quality: int = 80,
) -> list[str]:
    """Sample up to ``max_frames`` evenly from a video and save them as JPEGs.

    Claude accepts still images but not video files, so we rasterise the clip
    down to a small strip of frames that fit comfortably in a single request.
    Returns the list of saved frame paths, in order.
    """
    if not IMAGEIO_AVAILABLE:
        log.error("imageio not available; cannot extract frames")
        return []

    os.makedirs(output_dir, exist_ok=True)

    try:
        from PIL import Image
    except ImportError as e:
        log.error(f"PIL not available for frame extraction: {e}")
        return []

    try:
        # First, count total frames so we can sample uniformly.
        try:
            meta = iio.immeta(video_path, plugin="pyav") if hasattr(iio, "immeta") else {}
        except Exception:
            meta = {}

        frames_list = []
        try:
            # imageio.v3 returns a generator of numpy arrays
            frames_iter = iio.imiter(video_path)
        except Exception:
            # Fallback: read whole video
            frames_iter = iter(iio.imread(video_path))

        all_frames = list(frames_iter)
        if not all_frames:
            log.warning("No frames decoded from video")
            return []

        total = len(all_frames)
        if total <= max_frames:
            picks = list(range(total))
        else:
            step = total / max_frames
            picks = [int(i * step) for i in range(max_frames)]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved = []
        for n, idx in enumerate(picks):
            frame = all_frames[idx]
            img = Image.fromarray(frame)
            if max(img.size) > max_dimension:
                img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            path = os.path.join(output_dir, f"frame_{timestamp}_{n:03d}.jpg")
            img.convert("RGB").save(path, "JPEG", quality=quality, optimize=True)
            saved.append(path)

        log.info(f"Extracted {len(saved)} frames from {video_path}")
        return saved
    except Exception as e:
        log.error(f"Frame extraction failed: {e}", exc_info=True)
        return []
