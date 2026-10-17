"""Math for the tall 9:16 crop box: keeping its shape, keeping it inside the video,
and converting between fractions of the video and on-screen rectangles."""
from __future__ import annotations

from PySide6.QtCore import QRectF

from .project import Crop

TALL = 9 / 16           # width / height of a phone screen
MIN_HEIGHT = 0.2        # the box can't shrink below a fifth of the video's height
OUTPUT_HEIGHT = 1920    # exported clips are 1080x1920


def box_width(h: float, aspect: float) -> float:
    """Box width as a fraction of the video width. aspect = video width / height."""
    return h * TALL / aspect


def max_height(aspect: float) -> float:
    """The tallest box that fits: full height, unless the video is narrower than 9:16."""
    return min(1.0, aspect / TALL)


def default_crop(aspect: float) -> Crop:
    h = max_height(aspect)
    w = box_width(h, aspect)
    return Crop((1 - w) / 2, (1 - h) / 2, h)


def clamp(crop: Crop, aspect: float) -> Crop:
    h = min(max(crop.h, MIN_HEIGHT), max_height(aspect))
    w = box_width(h, aspect)
    return Crop(min(max(crop.x, 0.0), 1 - w), min(max(crop.y, 0.0), 1 - h), h)


def to_rect(crop: Crop, video: QRectF) -> QRectF:
    aspect = video.width() / video.height()
    return QRectF(
        video.left() + crop.x * video.width(),
        video.top() + crop.y * video.height(),
        box_width(crop.h, aspect) * video.width(),
        crop.h * video.height(),
    )


def source_pixels_tall(crop: Crop, source_height: float) -> float:
    """How many real video pixels tall the box is; under 1920 means the export is enlarged."""
    return crop.h * source_height
