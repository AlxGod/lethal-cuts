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

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath

from . import pause_title, text_look
from .project import Clip, Overlay

SHORT_FRAME = (1080, 1920)
ANIM_SECONDS = 0.3     # how long coming in or going out takes
POP_FROM = 0.6         # "pop" grows from this size
ANIMS = {"none": "None", "fade": "Fade", "pop": "Pop", "slide": "Slide in from the side",
         "type": "Typewriter (letter by letter)"}
ANIMS_OUT = {"none": "None", "fade": "Fade", "pop": "Pop", "slide": "Slide out to the side"}
DEFAULT_SECONDS = 4.0  # text
CARD_SECONDS = 5.0
MIN_SECONDS = 0.5
MIN_SIZE, MAX_SIZE = 0.1, 1.0
TEXT_FONT = "Segoe UI"
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
    if o.kind == "pause":
        return f'"{o.text.replace("*", "").strip()[:30]}"'
    words = o.text.replace("*", "").strip()  # the highlight stars aren't shown
    first = words.splitlines()[0] if words else "(no text yet)"
    return f'"{first[:40]}"'


# --- drawing ---
_cache: dict[tuple, QImage] = {}


def forget_pictures() -> None:
    """Draws everything fresh next time (a card picture finished downloading)."""
    _cache.clear()


def _key(o: Overlay, w: int, h: int, letters: int | None = None) -> tuple:
    if o.kind == "card":
        return ("card", (o.card or {}).get("image", ""), round(o.size, 4), w, h)
    return (o.kind, text_look.look_key(o), w, h, letters)


def render(o: Overlay, frame_w: int, frame_h: int, letters: int | None = None) -> QImage:
    """The overlay as a picture with a see-through background, at the finished video's size.
    letters: for the typewriter, how many letters are showing so far (None = all)."""
    key = _key(o, frame_w, frame_h, letters)
    image = _cache.get(key)
    if image is None:
        if o.kind == "card":
            image = _render_card(o, frame_w)
        elif o.kind == "pause":
            image = pause_title.render_pause(o, frame_w, frame_h, letters)  # letters = the countdown number
        else:
            image = text_look.render_text(o, frame_w, letters)
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = image
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
    typed: int = 0        # typewriter: how many pictures (one more letter each), named <image stem>_0001.png...
    type_rate: float = 0  # typewriter: letters a second
    concat: Path | None = None  # captions: FFmpeg's list of pictures and how long each shows


def freezes_in_clip(overlays: list[Overlay], clip: Clip) -> list[tuple[float, int]]:
    """Pause cards in a Short: (seconds into the clip where it freezes, how many seconds), in order."""
    return sorted((o.start - clip.start, pause_title.pause_seconds(o)) for o in overlays
                  if o.kind == "pause" and clip.start < o.start < clip.end - 0.05)


def times_in_clip(overlays: list[Overlay], clip: Clip) -> list[tuple[Overlay, float, float]]:
    """The overlays that show during a Short, with their times counted from the start of the finished
    Short. Each pause card adds its seconds there, pushing everything after it later."""
    freezes = freezes_in_clip(overlays, clip)

    def out(t_clip: float) -> float:
        return t_clip + sum(s for at, s in freezes if t_clip > at + 1e-6)

    found = []
    for o in overlays:
        if o.kind == "pause":
            if clip.start < o.start < clip.end - 0.05:
                at = out(o.start - clip.start)
                found.append((o, at, at + pause_title.pause_seconds(o)))
            continue
        a, b = max(o.start, clip.start), min(o.end, clip.end)
        if b - a >= 0.05:
            found.append((o, out(a - clip.start), out(b - clip.start)))
    return found


def to_output_time(t: float, pieces: list[tuple[float, float]], overlaps: list[float] | None = None,
                   lead: float = 0.0) -> float:
    """A time in the recording, as a time in the long video (the cut parts take no time).
    overlaps: seconds each join's transition overlaps the two sides (0 for a hard cut), which
    pulls everything after it that much earlier. lead: the title card's time at the start."""
    out = sum(min(max(t - a, 0.0), b - a) for a, b in pieces)
    for j, d in enumerate(overlaps or []):
        if d and t >= pieces[j + 1][0]:
            out -= d
    return max(out, 0.0) + lead


def times_in_long(overlays: list[Overlay], pieces: list[tuple[float, float]],
                  overlaps: list[float] | None = None, lead: float = 0.0) -> list[tuple[Overlay, float, float]]:
    """The overlays that show in the long video. One that runs into a cut just ends sooner."""
    found = []
    for o in overlays:
        if o.kind == "pause":
            continue  # pause cards are for Shorts
        a, b = to_output_time(o.start, pieces, overlaps, lead), to_output_time(o.end, pieces, overlaps, lead)
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
        typed, rate = 0, 0.0
        if o.kind == "pause":
            # One picture a second, counting down
            typed, rate = pause_title.pause_seconds(o), 1.0
            for n in range(1, typed + 1):
                frame = path.with_name(f"{path.stem}_{n:04d}.png")
                if not frame.exists() and not render(o, frame_w, frame_h, typed - n + 1).save(str(frame), "PNG"):
                    raise OSError(f"Couldn't save the countdown pictures in {folder}")
        elif o.kind == "text" and o.anim_in == "type":
            typed, rate = text_look.letter_count(o, frame_w), text_look.type_rate(o, end - start)
            for n in range(1, typed + 1):
                frame = path.with_name(f"{path.stem}_{n:04d}.png")
                if not frame.exists() and not render(o, frame_w, frame_h, n).save(str(frame), "PNG"):
                    raise OSError(f"Couldn't save the typewriter pictures for {describe(o)} in {folder}")
        placed.append(Placed(path, start, end, cx, cy, image.width(), image.height(), o.anim_in, o.anim_out,
                             slide_offsets(cx, image.width(), frame_w), typed, rate))
    return placed


def _ease_left(k: str) -> str:
    """FFmpeg's version of (1 - k)^3, the part of an ease-out still to go."""
    return f"pow(1-{k},3)"


def image_inputs(placed: list[Placed], fps: int) -> list[str]:
    """Each picture goes in once, as a single frame. The graph repeats it (see filter_graph), so FFmpeg
    holds one copy of it in memory, not a queue of copies waiting for their turn."""
    args = []
    for p in placed:
        if p.concat:
            args += ["-f", "concat", "-safe", "0", "-i", str(p.concat)]
        elif p.typed:
            # Typewriter: one picture per letter, played as a short video at the typing speed
            pattern = p.image.with_name(f"{p.image.stem}_%04d.png")
            args += ["-framerate", f"{p.type_rate:.4f}", "-start_number", "1", "-i", str(pattern)]
        else:
            args += ["-i", str(p.image)]
    return args


def filter_graph(pre: str, post: str, placed: list[Placed], first_input: int, fps: int = 30,
                 source: str = "[0:v]") -> str:
    """A -filter_complex graph: the video (source) through `pre`, each overlay laid on in turn, then `post`.
    The result is labelled [vout]."""
    parts = [f"{source}{pre or 'null'}[b0]"]
    last = "b0"
    for i, p in enumerate(placed):
        s, e = p.start, p.end
        a = anim_seconds(e - s)
        k_in, k_out = f"clip((t-{s:.4f})/{a:.4f},0,1)", f"clip(({e:.4f}-t)/{a:.4f},0,1)"
        frames = max(int(round((e - s) * fps)) + 1, 1)
        if p.concat:
            # Captions: already timed from the start of the video, one picture per moment
            parts.append(f"[{first_input + i}:v]format=rgba,fps={fps}[o{i}]")
            parts.append(f"[{last}][o{i}]overlay=x='(main_w-overlay_w)/2':y='{p.cy:.2f}-overlay_h/2':"
                         f"eof_action=pass[b{i + 1}]")
            last = f"b{i + 1}"
            continue
        if p.typed:
            # The letters arrive at the typing speed; the last picture then holds until it goes away
            hold = max(e - s - p.typed / p.type_rate, 0) + 0.2
            steps = ["format=rgba", f"setpts=PTS-STARTPTS+{s:.4f}/TB", f"fps={fps}",
                     f"tpad=stop_mode=clone:stop_duration={hold:.3f}"]
        else:
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
