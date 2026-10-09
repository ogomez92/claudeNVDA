# ClauVDA NVDA Add-on - Computer use screen capture
# -*- coding: utf-8 -*-

"""Capture the screen for Claude and map coordinates between the two spaces.

Claude sees a screenshot that can be smaller than the real desktop and answers
with coordinates in that image's pixel space. :class:`Display` captures the
whole virtual desktop with wxPython, scales it to the model's image limits, and
maps Claude's coordinates back to physical screen pixels.

Capture uses wx drawing calls, so it must run on NVDA's main thread.
"""

import ctypes
import math
import os
import tempfile

import wx
from logHandler import log

# Image limits of every model that supports the computer toolset: at most
# 2576 px on the long edge and 4784 visual tokens, one per 28x28 pixel patch.
# The API rejects larger images instead of shrinking them.
MAX_LONG_EDGE = 2576
MAX_VISUAL_TOKENS = 4784
_PATCH = 28

# System metrics for the bounding rectangle of all monitors, in pixels.
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79
_SM_CXSCREEN = 0
_SM_CYSCREEN = 1


def _virtual_screen_rect() -> tuple[int, int, int, int]:
    """Return (x, y, width, height) of the whole virtual desktop."""
    user32 = ctypes.windll.user32
    x = user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
    height = user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
    if width <= 0 or height <= 0:
        x, y = 0, 0
        width = user32.GetSystemMetrics(_SM_CXSCREEN)
        height = user32.GetSystemMetrics(_SM_CYSCREEN)
    return x, y, width, height


def _visual_tokens(width: int, height: int) -> int:
    return math.ceil(width / _PATCH) * math.ceil(height / _PATCH)


def fit_size(width: int, height: int, max_edge: int) -> tuple[int, int]:
    """Largest size with the same aspect ratio that fits the image limits.

    Never upscales. The long edge is capped at ``max_edge`` (itself capped at
    MAX_LONG_EDGE) and the total at MAX_VISUAL_TOKENS: a 4:3 or multi-monitor
    desktop at 2576 px wide would exceed the token limit and be rejected.
    """
    scale = min(1.0, min(max_edge, MAX_LONG_EDGE) / max(width, height))
    # Start from the area bound, then step down for the patch rounding.
    scale = min(scale, math.sqrt(MAX_VISUAL_TOKENS * _PATCH * _PATCH / (width * height)))
    while True:
        out_w = max(1, int(width * scale))
        out_h = max(1, int(height * scale))
        if _visual_tokens(out_w, out_h) <= MAX_VISUAL_TOKENS:
            return out_w, out_h
        scale *= 0.99


def _capture_to_png(src_x: int, src_y: int, src_w: int, src_h: int, out_w: int, out_h: int) -> bytes:
    """Capture a screen region, resize it to out_w x out_h and return PNG bytes."""
    screen_dc = wx.ScreenDC()
    bitmap = wx.Bitmap(src_w, src_h)
    mem_dc = wx.MemoryDC(bitmap)
    try:
        mem_dc.Blit(0, 0, src_w, src_h, screen_dc, src_x, src_y)
    finally:
        mem_dc.SelectObject(wx.NullBitmap)
    image = bitmap.ConvertToImage()
    if (out_w, out_h) != (src_w, src_h):
        image = image.Scale(out_w, out_h, wx.IMAGE_QUALITY_HIGH)
    # wx writes PNG most portably to a file, so round-trip through one.
    handle, path = tempfile.mkstemp(suffix=".png", prefix="clauvda_cu_")
    os.close(handle)
    try:
        if not image.SaveFile(path, wx.BITMAP_TYPE_PNG):
            raise RuntimeError("Could not encode the screenshot")
        with open(path, "rb") as png_file:
            return png_file.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            log.debugWarning(f"Could not remove temporary screenshot {path}", exc_info=True)


class Display:
    """Screen geometry and scaling for one computer use session."""

    def __init__(self, max_edge: int):
        self.max_edge = max_edge
        self.refresh()

    def refresh(self) -> None:
        """Re-read the desktop geometry (monitors can change between tasks)."""
        self.origin_x, self.origin_y, self.phys_width, self.phys_height = _virtual_screen_rect()
        #: Size of the screenshots Claude receives; its coordinates are in this space.
        self.width, self.height = fit_size(self.phys_width, self.phys_height, self.max_edge)
        self.scale_x = self.width / self.phys_width
        self.scale_y = self.height / self.phys_height

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        """Map a screenshot coordinate from Claude to a physical screen pixel."""
        x = min(max(float(x), 0.0), self.width - 1)
        y = min(max(float(y), 0.0), self.height - 1)
        return (
            self.origin_x + int(round(x / self.scale_x)),
            self.origin_y + int(round(y / self.scale_y)),
        )

    def to_image(self, screen_x: int, screen_y: int) -> tuple[int, int]:
        """Map a physical screen pixel to screenshot coordinates."""
        return (
            int((screen_x - self.origin_x) * self.scale_x),
            int((screen_y - self.origin_y) * self.scale_y),
        )

    def capture(self) -> bytes:
        """A PNG of the whole desktop at screenshot size. Main thread only."""
        return _capture_to_png(
            self.origin_x,
            self.origin_y,
            self.phys_width,
            self.phys_height,
            self.width,
            self.height,
        )

    def capture_region(self, region) -> bytes:
        """A PNG of a screenshot-space region at full resolution, for zoom.

        The region is captured from the physical screen and scaled to fit the
        usual screenshot size with its aspect ratio kept. Claude's coordinates
        stay in the full screenshot's space afterwards. Main thread only.
        """
        if not isinstance(region, (list, tuple)) or len(region) != 4:
            raise ValueError("region must be [x0, y0, x1, y1]")
        sx0, sy0 = self.to_screen(region[0], region[1])
        sx1, sy1 = self.to_screen(region[2], region[3])
        left, top = min(sx0, sx1), min(sy0, sy1)
        width, height = max(1, abs(sx1 - sx0)), max(1, abs(sy1 - sy0))
        scale = min(self.width / width, self.height / height)
        out_w, out_h = fit_size(max(1, int(width * scale)), max(1, int(height * scale)), self.max_edge)
        return _capture_to_png(left, top, width, height, out_w, out_h)
