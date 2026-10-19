"""Cards and text shown on top of the video: how they look, move, and get into the export.

Each overlay is drawn once as a picture (a QImage) at the finished video's size. The Editor
shows that same picture over the video, and the export hands it to FFmpeg as a still image
laid over the video, so what you see while editing is what ends up in the file. The
animations (fade, pop, slide) use the same maths in both places.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen

from .project import Clip, Overlay

SHORT_FRAME = (1080, 1920)
ANIM_SECONDS = 0.3     # how long coming in or going out takes
POP_FROM = 0.6         # "pop" grows from this size
ANIMS = {"none": "None", "fade": "Fade", "pop": "Pop", "slide": "Slide in from the side"}
ANIMS_OUT = {"none": "None", "fade": "Fade", "pop": "Pop", "slide": "Slide out to the side"}
DEFAULT_SECONDS = 4.0  # text
CARD_SECONDS = 5.0
MIN_SECONDS = 0.5
MIN_SIZE, MAX_SIZE = 0.1, 1.0
TEXT_FONT = "Segoe UI"
TEXT_WRAP = 0.9        # text wraps at this fraction of the video's width
CARD_CORNER = 0.045    # Magic cards' rounded corners, as a fraction of their width


def long_frame(src_w: int, src_h: int, size: str) -> tuple[int, int]:
    """The long video's size in pixels, the same way long_export works it out."""
    h = src_h if size == "source" or src_h <= 1080 else 1080
    w = src_w if h == src_h else int(h * src_w / src_h) // 2 * 2
    return max(w, 2), max(h, 2)


def visible_at(overlays: list[Overlay], t: float) -> list[int]:
    return [i for i, o in enumerate(overlays) if o.start <= t <= o.end]


def describe(o: Overlay) -> str:
    if o.kind == "card":
        return (o.card or {}).get("name", "Card")
    first = o.text.strip().splitlines()[0] if o.text.strip() else "(no text yet)"
    return f'"{first[:40]}"'


# --- drawing ---
_cache: dict[tuple, QImage] = {}


def forget_pictures() -> None:
    """Draws everything fresh next time (a card picture finished downloading)."""
    _cache.clear()


def _key(o: Overlay, w: int, h: int) -> tuple:
    card = (o.card or {}).get("image", "")
    return (o.kind, o.text, o.style, round(o.size, 4), card, w, h)


def render(o: Overlay, frame_w: int, frame_h: int) -> QImage:
    """The overlay as a picture with a see-through background, at the finished video's size."""
    key = _key(o, frame_w, frame_h)
    image = _cache.get(key)
    if image is None:
        image = _render_card(o, frame_w) if o.kind == "card" else _render_text(o, frame_w)
        if len(_cache) > 60:
            _cache.clear()
        _cache[key] = image
    return image


def text_font(o: Overlay, frame_w: int) -> QFont:
    font = QFont(TEXT_FONT)
    font.setPixelSize(max(int(o.size * frame_w * 0.15), 8))
    font.setWeight(QFont.Black)
    return font


def _wrap(text: str, metrics: QFontMetricsF, width: float) -> list[str]:
    lines = []
    for paragraph in (text or " ").splitlines() or [" "]:
        line = ""
        for word in paragraph.split(" "):
            test = f"{line} {word}" if line else word
            if line and metrics.horizontalAdvance(test) > width:
                lines.append(line)
                line = word
            else:
                line = test
        lines.append(line)
    return lines


def _render_text(o: Overlay, frame_w: int) -> QImage:
    """White bold text with a thick black outline: readable on any part of the video."""
    font = text_font(o, frame_w)
    metrics = QFontMetricsF(font)
    lines = _wrap(o.text.strip() or "Your text", metrics, frame_w * TEXT_WRAP)
    outline = max(font.pixelSize() * 0.14, 2.0)
    line_h = metrics.height()
    width = max(metrics.horizontalAdvance(line) for line in lines)
    pad = outline + 2
    image = QImage(int(width + pad * 2) + 1, int(line_h * len(lines) + pad * 2) + 1, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    path = QPainterPath()
    for i, line in enumerate(lines):
        x = pad + (width - metrics.horizontalAdvance(line)) / 2  # centered lines
        path.addText(QPointF(x, pad + i * line_h + metrics.ascent()), font, line)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(0, 0, 0), outline * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)  # the outline is drawn first and twice as wide, so half of it shows around the letters
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255))
    p.drawPath(path)
    p.end()
    return image


def _render_card(o: Overlay, frame_w: int) -> QImage:
    width = max(int(o.size * frame_w), 16)
    height = int(width * 88 / 63)  # a Magic card is 63 x 88 mm
    source = QImage((o.card or {}).get("image", ""))
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    shape = QPainterPath()
    shape.addRoundedRect(QRectF(0, 0, width, height), width * CARD_CORNER, width * CARD_CORNER)
    p.setClipPath(shape)
    if source.isNull():
        # The picture is missing (still downloading, or deleted): a plain stand-in with the name
        p.fillRect(QRectF(0, 0, width, height), QColor("#2a2338"))
        p.setPen(QColor("#f0b840"))
        font = QFont(TEXT_FONT)
        font.setPixelSize(max(width // 10, 8))
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(0, 0, width, height), Qt.AlignCenter | Qt.TextWordWrap, describe(o))
    else:
        p.drawImage(QRectF(0, 0, width, height), source)
    p.end()
    return image


# --- where it sits and how it moves (shared by the Editor and the export) ---
def resting_center(o: Overlay, img_w: float, img_h: float, frame_w: int, frame_h: int) -> tuple[float, float]:
    """The middle of the overlay in pixels, kept far enough in that the whole thing stays on screen."""
    def fit(value, half, full):
        return full / 2 if half * 2 >= full else min(max(value, half), full - half)
    return fit(o.x * frame_w, img_w / 2, frame_w), fit(o.y * frame_h, img_h / 2, frame_h)


def anim_seconds(length: float) -> float:
    return max(min(ANIM_SECONDS, length / 2), 0.01)


def slide_offsets(cx: float, img_w: float, frame_w: int) -> float:
    """How far a slide starts off to the side: just past the nearest side edge."""
    return -(cx + img_w / 2) if cx < frame_w / 2 else frame_w - cx + img_w / 2


def look(o: Overlay, start: float, end: float, t: float, slide_off: float) -> tuple[float, float, float]:
    """(opacity 0-1, size multiplier, sideways shift in pixels) at time t, for an overlay shown from start to end."""
    a = anim_seconds(end - start)
    p = min(max((t - start) / a, 0.0), 1.0)  # how far it has come in
    q = min(max((end - t) / a, 0.0), 1.0)    # how far it is from leaving
    opacity, scale, dx = 1.0, 1.0, 0.0
    for anim, k in ((o.anim_in, p), (o.anim_out, q)):
        if anim in ("fade", "pop"):
            opacity *= k
        if anim == "pop":
            scale *= POP_FROM + (1 - POP_FROM) * (1 - (1 - k) ** 3)
        if anim == "slide":
            dx += slide_off * (1 - k) ** 3
    return opacity, scale, dx


# --- export ---
@dataclass
class Placed:
    """One overlay ready for FFmpeg: its picture file, when it shows (seconds into the
    finished video) and where its middle sits (pixels)."""
    image: Path
    start: float
    end: float
    cx: float
    cy: float
    width: int
    height: int
    anim_in: str
    anim_out: str
    slide_off: float


def times_in_clip(overlays: list[Overlay], clip: Clip) -> list[tuple[Overlay, float, float]]:
    """The overlays that show during a Short, with their times counted from the clip's start."""
    found = []
    for o in overlays:
        a, b = max(o.start, clip.start), min(o.end, clip.end)
        if b - a >= 0.05:
            found.append((o, a - clip.start, b - clip.start))
    return found


def to_output_time(t: float, pieces: list[tuple[float, float]]) -> float:
    """A time in the recording, as a time in the long video (the cut parts take no time)."""
    return sum(min(max(t - a, 0.0), b - a) for a, b in pieces)


def times_in_long(overlays: list[Overlay], pieces: list[tuple[float, float]]) -> list[tuple[Overlay, float, float]]:
    """The overlays that show in the long video. One that runs into a cut just ends sooner."""
    found = []
    for o in overlays:
        a, b = to_output_time(o.start, pieces), to_output_time(o.end, pieces)
        if b - a >= 0.05:
            found.append((o, a, b))
    return found


def prepare(timed: list[tuple[Overlay, float, float]], frame_w: int, frame_h: int, folder: Path) -> list[Placed]:
    """Draws each overlay into a PNG file for FFmpeg. Runs on the main thread (text drawing needs it)."""
    folder.mkdir(parents=True, exist_ok=True)
    placed = []
    for o, start, end in timed:
        image = render(o, frame_w, frame_h)
        name = hashlib.sha1(repr(_key(o, frame_w, frame_h)).encode()).hexdigest()[:16] + ".png"
        path = folder / name
        if not path.exists() and not image.save(str(path), "PNG"):
            raise OSError(f"Couldn't save the picture for {describe(o)} in {folder}")
        cx, cy = resting_center(o, image.width(), image.height(), frame_w, frame_h)
        placed.append(Placed(path, start, end, cx, cy, image.width(), image.height(), o.anim_in, o.anim_out,
                             slide_offsets(cx, image.width(), frame_w)))
    return placed


def _ease_left(k: str) -> str:
    """FFmpeg's version of (1 - k)^3, the part of an ease-out still to go."""
    return f"pow(1-{k},3)"


def image_inputs(placed: list[Placed], fps: int) -> list[str]:
    """Each picture goes in once, as a single frame. The graph repeats it (see filter_graph), so FFmpeg
    holds one copy of it in memory, not a queue of copies waiting for their turn."""
    args = []
    for p in placed:
        args += ["-i", str(p.image)]
    return args


def filter_graph(pre: str, post: str, placed: list[Placed], first_input: int, fps: int = 30) -> str:
    """A -filter_complex graph: the video through `pre`, each overlay laid on in turn, then `post`.
    The result is labelled [vout]."""
    parts = [f"[0:v]{pre}[b0]"]
    last = "b0"
    for i, p in enumerate(placed):
        s, e = p.start, p.end
        a = anim_seconds(e - s)
        k_in, k_out = f"clip((t-{s:.4f})/{a:.4f},0,1)", f"clip(({e:.4f}-t)/{a:.4f},0,1)"
        frames = max(int(round((e - s) * fps)) + 1, 1)
        steps = ["format=rgba", f"loop=loop={frames - 1}:size=1:start=0", f"setpts=N/{fps}/TB+{s:.4f}/TB"]
        if p.anim_in in ("fade", "pop"):
            steps.append(f"fade=t=in:st={s:.4f}:d={a:.4f}:alpha=1")
        if p.anim_out in ("fade", "pop"):
            steps.append(f"fade=t=out:st={e - a:.4f}:d={a:.4f}:alpha=1")
        scale = []
        if p.anim_in == "pop":
            scale.append(f"({POP_FROM}+{1 - POP_FROM:.2f}*(1-{_ease_left(k_in)}))")
        if p.anim_out == "pop":
            scale.append(f"({POP_FROM}+{1 - POP_FROM:.2f}*(1-{_ease_left(k_out)}))")
        if scale:
            factor = "*".join(scale)
            steps.append(f"scale=w='max(trunc({p.width}*{factor}/2)*2,2)':h='max(trunc({p.height}*{factor}/2)*2,2)'"
                         f":eval=frame")
        parts.append(f"[{first_input + i}:v]{','.join(steps)}[o{i}]")
        x = f"{p.cx:.2f}-overlay_w/2"
        if p.anim_in == "slide":
            x += f"+({p.slide_off:.2f})*{_ease_left(k_in)}"
        if p.anim_out == "slide":
            x += f"+({p.slide_off:.2f})*{_ease_left(k_out)}"
        parts.append(f"[{last}][o{i}]overlay=x='{x}':y='{p.cy:.2f}-overlay_h/2':eof_action=pass[b{i + 1}]")
        last = f"b{i + 1}"
    parts.append(f"[{last}]{post}[vout]")
    return ";".join(parts)
