"""Two full-screen cards: the "What's your play?" pause card for Shorts, and the series title card
that opens a long video.

The pause card freezes the Short on one frame, darkens it, and counts down (3, 2, 1) under a
question, so viewers stop and think before seeing what was played. The title card is a few
seconds of "Series name / Episode 12 / who's playing", over the commanders' art.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen

from . import text_look
from .project import Overlay

PAUSE_TEXT = "What's your play?"
PAUSE_SECONDS = 3
PAUSE_MIN, PAUSE_MAX = 2, 10
TITLE_SECONDS = 4.0
TITLE_DIP = 0.6          # the title dips to black into the video, this long
MAX_COMMANDERS = 4
ART_BOX = (0.085, 0.11, 0.915, 0.555)  # where the artwork sits on a Magic card (left, top, right, bottom)


def new_pause(at: float) -> Overlay:
    o = Overlay("pause", round(at, 3), round(at + PAUSE_SECONDS, 3), text=PAUSE_TEXT, anim_in="fade",
                anim_out="none")
    text_look.apply_style(o, "hook", long=False, place=False)
    o.size = 0.62
    return o


def pause_seconds(o: Overlay) -> int:
    return int(min(max(round(o.length), PAUSE_MIN), PAUSE_MAX))


def render_pause(o: Overlay, frame_w: int, frame_h: int, number: int | None = None) -> QImage:
    """The whole frame: darkened, the question at the top, a big countdown number in a ring."""
    number = pause_seconds(o) if number is None else number
    image = QImage(frame_w, frame_h, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 120))
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    question = text_look.render_text(o, frame_w)
    p.drawImage(QPointF((frame_w - question.width()) / 2, frame_h * 0.3 - question.height() / 2), question)
    # The countdown: a gold ring with the number in it
    r = min(frame_w, frame_h) * 0.16
    center = QPointF(frame_w / 2, frame_h * 0.55)
    p.setPen(QPen(QColor(o.accent), r * 0.12))
    p.setBrush(QColor(0, 0, 0, 150))
    p.drawEllipse(center, r, r)
    font = QFont(o.font)
    font.setPixelSize(int(r * 1.15))
    font.setWeight(QFont.Black)
    path = QPainterPath()
    path.addText(QPointF(0, 0), font, str(number))
    box = path.boundingRect()
    path.translate(center.x() - box.center().x(), center.y() - box.center().y())
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.drawPath(path)
    p.end()
    return image


# --- the series title card ---
def new_title(series: str, episode: int) -> dict:
    return {"series": series or "Lethal Cuts", "episode": int(episode), "title": "", "cards": [],
            "seconds": TITLE_SECONDS}


def title_seconds(card: dict) -> float:
    try:
        return min(max(float(card.get("seconds", TITLE_SECONDS)), 2.0), 10.0)
    except (TypeError, ValueError):
        return TITLE_SECONDS


def _art(path: str) -> QImage:
    """Just the artwork from a card picture."""
    card = QImage(path)
    if card.isNull():
        return card
    l, t, r, b = ART_BOX
    return card.copy(int(card.width() * l), int(card.height() * t), int(card.width() * (r - l)),
                     int(card.height() * (b - t)))


def _fill(p: QPainter, image: QImage, area: QRectF):
    """Draws a picture to cover an area completely (cropping what doesn't fit)."""
    scale = max(area.width() / image.width(), area.height() / image.height())
    w, h = image.width() * scale, image.height() * scale
    p.drawImage(QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h), image)


def _text(p: QPainter, text: str, font: QFont, center: QPointF, color: str, max_w: float, outline: float = 0.0):
    path = QPainterPath()
    path.addText(QPointF(0, 0), font, text)
    box = path.boundingRect()
    if box.width() > max_w > 0:
        # Too wide: shrink it to fit
        font = QFont(font)
        font.setPixelSize(max(int(font.pixelSize() * max_w / box.width()), 8))
        path = QPainterPath()
        path.addText(QPointF(0, 0), font, text)
        box = path.boundingRect()
    path.translate(center.x() - box.center().x(), center.y() - box.center().y())
    if outline:
        p.setPen(QPen(QColor(0, 0, 0, 200), outline * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawPath(path)


def render_title(card: dict, frame_w: int, frame_h: int) -> QImage:
    image = QImage(frame_w, frame_h, QImage.Format_RGB32)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    full = QRectF(0, 0, frame_w, frame_h)
    gradient = QLinearGradient(0, 0, 0, frame_h)
    gradient.setColorAt(0, QColor("#1b1428"))
    gradient.setColorAt(1, QColor("#3a1f3f"))
    p.fillRect(full, gradient)
    # Each commander's art in a strip across the background, darkened
    arts = [a for a in (_art(c.get("image", "")) for c in card.get("cards", [])[:MAX_COMMANDERS]) if not a.isNull()]
    for i, art in enumerate(arts):
        strip = QRectF(frame_w * i / len(arts), 0, frame_w / len(arts), frame_h)
        p.save()
        p.setClipRect(strip)
        _fill(p, art, strip)
        p.restore()
    if arts:
        shade = QLinearGradient(0, 0, 0, frame_h)
        shade.setColorAt(0, QColor(10, 6, 16, 215))
        shade.setColorAt(0.6, QColor(10, 6, 16, 150))
        shade.setColorAt(1, QColor(10, 6, 16, 235))
        p.fillRect(full, shade)
    u = frame_h / 1080  # sizes are worked out for 1080 tall and scaled
    series = QFont("Segoe UI")
    series.setPixelSize(int(46 * u))
    series.setWeight(QFont.Bold)
    series.setLetterSpacing(QFont.PercentageSpacing, 118)
    _text(p, (card.get("series") or "").upper(), series, QPointF(frame_w / 2, frame_h * 0.17), "#f0b840", frame_w * 0.9)
    big = QFont("Segoe UI")
    big.setPixelSize(int(150 * u))
    big.setWeight(QFont.Black)
    _text(p, f"EPISODE {card.get('episode', 1)}", big, QPointF(frame_w / 2, frame_h * 0.33), "#ffffff", frame_w * 0.9,
          outline=6 * u)
    if card.get("title"):
        line = QFont("Segoe UI")
        line.setPixelSize(int(56 * u))
        line.setWeight(QFont.DemiBold)
        _text(p, card["title"], line, QPointF(frame_w / 2, frame_h * 0.47), "#ffffff", frame_w * 0.9, outline=3 * u)
    # The commanders themselves, fanned out along the bottom
    cards = [QImage(c.get("image", "")) for c in card.get("cards", [])[:MAX_COMMANDERS]]
    cards = [c for c in cards if not c.isNull()]
    if cards:
        h = frame_h * 0.4
        w = h * 63 / 88
        gap = w * 0.12
        total = len(cards) * w + (len(cards) - 1) * gap
        for i, c in enumerate(cards):
            x = (frame_w - total) / 2 + i * (w + gap)
            angle = (i - (len(cards) - 1) / 2) * 4
            p.save()
            p.translate(x + w / 2, frame_h * 0.77)
            p.rotate(angle)
            rect = QRectF(-w / 2, -h / 2, w, h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 120))
            p.drawRoundedRect(rect.translated(6 * u, 10 * u), w * 0.045, w * 0.045)
            shape = QPainterPath()
            shape.addRoundedRect(rect, w * 0.045, w * 0.045)
            p.setClipPath(shape)
            p.drawImage(rect, c)
            p.restore()
    p.end()
    return image


def title_dip(fps: int) -> float:
    """The dip from the title into the video, in whole frames."""
    return round(TITLE_DIP * fps) / fps


def title_lead(card: dict | None, fps: int = 30) -> float:
    """How much later everything in the long video starts because of the title card."""
    if not card:
        return 0.0
    return title_seconds(card) - title_dip(fps)
