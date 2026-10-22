"""How text overlays look: fonts, colors, outline, shadow, background box, highlighted words,
the ready-made styles (Hook, Callout, Name tag, Plain) and the typewriter animation.

Words between *stars* are drawn in the highlight color, so "That's *LETHAL*" makes one word pop.
The text is drawn into a QImage. The typewriter draws the same layout with only the first
letters filled in, so the text never shifts while it types.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen

from .project import Overlay

TEXT_WRAP = 0.9       # text wraps at this fraction of the video's width
LETTER_SIZE = 0.15    # letter height for size 1.0, as a fraction of the video's width
TYPE_SPEED = 18       # typewriter letters a second (faster if needed to finish in time)
TYPE_SHARE = 0.6      # the typing takes at most this share of the time it's on screen

# Fonts that come with Windows, so the export looks the same on any PC. (label, family, weight)
FONTS = [
    ("Segoe UI Black", "Segoe UI", 900), ("Segoe UI Bold", "Segoe UI", 700), ("Impact", "Impact", 400),
    ("Bahnschrift", "Bahnschrift", 700), ("Arial Black", "Arial", 900), ("Franklin Gothic", "Franklin Gothic Medium", 400),
    ("Georgia", "Georgia", 700), ("Comic Sans", "Comic Sans MS", 700), ("Ink Free", "Ink Free", 400),
    ("Segoe Print", "Segoe Print", 700), ("Consolas", "Consolas", 700),
]

# The ready-made styles. Picking one sets these, plus where it sits (Shorts, long video) and how it moves.
STYLES = {
    "hook": {
        "name": "Hook", "tip": "A big headline in capitals at the top",
        "look": dict(font="Segoe UI", weight=900, color="#ffffff", accent="#ffd400", outline=0.16,
                     outline_color="#000000", shadow=True, box="", stripe=False, caps=True, align="center"),
        "short": (0.5, 0.27, 0.72), "long": (0.5, 0.13, 0.5), "in": "pop", "out": "fade",
    },
    "callout": {
        "name": "Callout", "tip": "Dark words in a gold box",
        "look": dict(font="Segoe UI", weight=900, color="#16121e", accent="#b0304a", outline=0.0,
                     outline_color="#000000", shadow=True, box="#f0b840", stripe=False, caps=False, align="center"),
        "short": (0.5, 0.64, 0.46), "long": (0.5, 0.78, 0.3), "in": "pop", "out": "pop",
    },
    "nametag": {
        "name": "Name tag", "tip": "A small tag low on one side, for who's who",
        "look": dict(font="Segoe UI", weight=700, color="#ffffff", accent="#f0b840", outline=0.0,
                     outline_color="#000000", shadow=False, box="#e616121e", stripe=True, caps=False, align="left"),
        "short": (0.3, 0.62, 0.34), "long": (0.16, 0.88, 0.2), "in": "slide", "out": "slide",
    },
    "plain": {
        "name": "Plain", "tip": "White words with a black outline",
        "look": dict(font="Segoe UI", weight=900, color="#ffffff", accent="#ffd400", outline=0.14,
                     outline_color="#000000", shadow=False, box="", stripe=False, caps=False, align="center"),
        "short": (0.5, 0.5, 0.6), "long": (0.5, 0.5, 0.4), "in": "fade", "out": "fade",
    },
}
DEFAULT_STYLE = {"short": "hook", "long": "callout"}


def apply_style(o: Overlay, style: str, long: bool, place: bool = True) -> None:
    """Gives the overlay a ready-made look. With place, it also moves to where that style usually goes."""
    s = STYLES.get(style, STYLES["plain"])
    o.style = style
    for name, value in s["look"].items():
        setattr(o, name, value)
    if place:
        o.x, o.y, o.size = s["long" if long else "short"]
        o.anim_in, o.anim_out = s["in"], s["out"]


def look_key(o: Overlay) -> tuple:
    return (o.text, round(o.size, 4), o.font, o.weight, o.color, o.accent, round(o.outline, 3), o.outline_color,
            o.shadow, o.box, o.stripe, o.caps, o.align)


def font_for(o: Overlay, frame_w: int) -> QFont:
    font = QFont(o.font)
    font.setPixelSize(max(int(o.size * frame_w * LETTER_SIZE), 8))
    font.setWeight(QFont.Weight(min(max(int(o.weight), 100), 900)))
    return font


# --- layout: lines of words, each word made of pieces that are highlighted or not ---
def _words(text: str, caps: bool) -> list[list[list[tuple[str, bool]]]]:
    """Paragraphs of words; a word is a list of (piece, highlighted). Stars switch the highlight on and off."""
    if caps:
        text = text.upper()
    paragraphs, accent = [], False
    for paragraph in text.splitlines() or [""]:
        words = []
        for token in paragraph.split(" "):
            pieces = []
            for i, part in enumerate(token.split("*")):
                if i:
                    accent = not accent
                if part:
                    pieces.append((part, accent))
            if pieces:
                words.append(pieces)
        paragraphs.append(words)
    return paragraphs


def _layout(o: Overlay, frame_w: int):
    font = font_for(o, frame_w)
    m = QFontMetricsF(font)
    space = m.horizontalAdvance(" ")
    width_of = lambda word: sum(m.horizontalAdvance(t) for t, _ in word)
    limit = frame_w * TEXT_WRAP
    lines = []
    for words in _words(o.text.strip() or "Your text", o.caps):
        line, w = [], 0.0
        for word in words:
            ww = width_of(word)
            if line and w + space + ww > limit:
                lines.append((line, w))
                line, w = [], 0.0
            w = w + space + ww if line else ww
            line.append(word)
        lines.append((line, w))
    return font, m, space, lines


def letter_count(o: Overlay, frame_w: int = 1080) -> int:
    """Letters that get typed one by one (spaces don't count)."""
    return sum(len(t) for line, _ in _layout(o, frame_w)[3] for word in line for t, _ in word)


def type_rate(o: Overlay, length: float) -> float:
    """Typewriter letters a second: steady, but quick enough to finish while there's time to read it."""
    return max(TYPE_SPEED, letter_count(o) / max(length * TYPE_SHARE, 0.1))


def typed_letters(o: Overlay, start: float, end: float, t: float) -> int | None:
    """How many letters are showing at time t (None = all of them, no typewriter)."""
    if o.kind != "text" or o.anim_in != "type":
        return None
    total = letter_count(o)
    return min(total, max(int((t - start) * type_rate(o, end - start)) + 1, 1))


def render_text(o: Overlay, frame_w: int, letters: int | None = None) -> QImage:
    font, m, space, lines = _layout(o, frame_w)
    px = font.pixelSize()
    line_h = m.height()
    text_w = max((w for _, w in lines), default=0.0)
    outline = px * max(o.outline, 0.0)
    has_box = bool(o.box)
    pad_x, pad_y = (px * 0.45, px * 0.2) if has_box else (0.0, 0.0)
    stripe_w = px * 0.16 if has_box and o.stripe else 0.0
    shadow = (px * 0.05, px * 0.08) if o.shadow else (0.0, 0.0)
    margin = outline + max(shadow) + 3
    box = QRectF(margin, margin, text_w + pad_x * 2 + stripe_w, line_h * len(lines) + pad_y * 2)
    image = QImage(int(box.right() + margin) + 1, int(box.bottom() + margin) + 1, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    plain, lit = QPainterPath(), QPainterPath()
    left = box.left() + stripe_w + pad_x
    left_to_type = 10 ** 9 if letters is None else letters
    for i, (line, w) in enumerate(lines):
        x = left if o.align == "left" else left + (text_w - w) / 2
        y = box.top() + pad_y + i * line_h + m.ascent()
        for word in line:
            for piece, accent in word:
                shown = piece[:max(left_to_type, 0)]
                left_to_type -= len(piece)
                if shown:
                    (lit if accent else plain).addText(QPointF(x, y), font, shown)
                x += m.horizontalAdvance(piece)
            x += space

    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    if has_box:
        radius = px * 0.28
        if o.shadow:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 110))
            p.drawRoundedRect(box.translated(*shadow), radius, radius)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(o.box))
        p.drawRoundedRect(box, radius, radius)
        if stripe_w:
            bar = QPainterPath()
            bar.addRoundedRect(box, radius, radius)
            p.setClipPath(bar)
            p.fillRect(QRectF(box.left(), box.top(), stripe_w, box.height()), QColor(o.accent))
            p.setClipping(False)
    both = QPainterPath(plain)
    both.addPath(lit)
    if o.shadow and not has_box:
        # A soft drop shadow: the outline's shape, offset down and right, see-through
        p.setPen(QPen(QColor(0, 0, 0, 120), outline * 2 + px * 0.04, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawPath(both.translated(*shadow))
    if outline > 0:
        # Drawn first and twice as wide, so half of it shows around the letters
        p.setPen(QPen(QColor(o.outline_color), outline * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(both)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(o.color))
    p.drawPath(plain)
    p.setBrush(QColor(o.accent))
    p.drawPath(lit)
    p.end()
    return image
