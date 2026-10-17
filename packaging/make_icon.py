"""Draws the Lethal Cuts icon and saves icon.ico (16 to 256 px) and icon-512.png.

Dark purple-to-crimson rounded square, a film strip across it (the full game),
a glowing blade slashing through it, and one tall card-shaped frame lifted out
and glowing (the Short), with a spark where the blade cuts. No text.
Small sizes (16-32 px) use a simpler drawing so they stay readable.

Run:  python packaging/make_icon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient, QTransform,
)

OUT = Path(__file__).resolve().parent.parent / "assets"
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

BG_TOP = QColor("#1a0b2e")      # near-black purple
BG_BOTTOM = QColor("#5a0f22")   # dark crimson
STRIP = QColor("#0d0812")
STRIP_EDGE = QColor("#3b2a52")
HOLE = QColor("#6d5a8a")
FRAME_DIM = QColor("#2a1f3d")
CARD_FILL_TOP = QColor("#ffcf6b")
CARD_FILL_BOTTOM = QColor("#f08a3c")
BLADE = QColor("#fff4e0")
GLOW = QColor("#ff5a5a")


def draw(size: int, simple: bool) -> QImage:
    """Draws on a 1000x1000 canvas scaled down to `size`."""
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 1000, size / 1000)

    # Rounded-square background with a dark gradient
    bg = QPainterPath()
    bg.addRoundedRect(QRectF(20, 20, 960, 960), 210, 210)
    g = QLinearGradient(0, 0, 1000, 1000)
    g.setColorAt(0, BG_TOP)
    g.setColorAt(1, BG_BOTTOM)
    p.fillPath(bg, g)
    p.setClipPath(bg)
    # soft light from the cut point
    halo = QRadialGradient(QPointF(470, 540), 520)
    halo.setColorAt(0, QColor(255, 90, 90, 70))
    halo.setColorAt(1, QColor(255, 90, 90, 0))
    p.fillRect(QRectF(0, 0, 1000, 1000), halo)

    # Film strip across the middle, slightly tilted
    p.save()
    p.translate(500, 560)
    p.rotate(-8)
    strip_h = 300 if not simple else 340
    strip = QRectF(-640, -strip_h / 2, 1280, strip_h)
    p.setPen(QPen(STRIP_EDGE, 6))
    p.setBrush(STRIP)
    p.drawRect(strip)
    if not simple:
        # sprocket holes along both edges
        p.setPen(Qt.NoPen)
        p.setBrush(HOLE)
        for x in range(-620, 640, 70):
            p.drawRoundedRect(QRectF(x, -strip_h / 2 + 16, 36, 28), 6, 6)
            p.drawRoundedRect(QRectF(x, strip_h / 2 - 44, 36, 28), 6, 6)
        # dim frames along the strip
        p.setBrush(FRAME_DIM)
        for x in (-560, -350, 260, 470):
            p.drawRoundedRect(QRectF(x, -strip_h / 2 + 62, 170, strip_h - 124), 14, 14)
    # the gap left where the tall frame was cut out
    gap = QRectF(-85, -strip_h / 2 + 50, 170, strip_h - 100)
    p.setPen(QPen(QColor(255, 120, 90, 160), 5, Qt.DashLine) if not simple else Qt.NoPen)
    p.setBrush(QColor("#06030a"))
    p.drawRoundedRect(gap, 14, 14)
    p.restore()

    # The lifted, glowing card-shaped frame (the Short), tall like a phone screen
    card = QRectF(395, 170, 250, 400) if not simple else QRectF(360, 150, 300, 470)
    p.save()
    p.translate(card.center())
    p.rotate(6)
    p.translate(-card.center())
    for spread, alpha in ((60, 40), (38, 70), (20, 110)):  # outer glow
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 170, 80, alpha))
        p.drawRoundedRect(card.adjusted(-spread, -spread, spread, spread), 40 + spread, 40 + spread)
    cg = QLinearGradient(card.topLeft(), card.bottomRight())
    cg.setColorAt(0, CARD_FILL_TOP)
    cg.setColorAt(1, CARD_FILL_BOTTOM)
    p.setBrush(cg)
    p.setPen(QPen(QColor("#fff7e6"), 10 if not simple else 14))
    p.drawRoundedRect(card, 34, 34)
    if not simple:
        # thin inner border, like a generic playing card
        p.setPen(QPen(QColor(120, 40, 20, 150), 6))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(card.adjusted(26, 26, -26, -26), 18, 18)
    p.restore()

    # The blade: a long sharp diagonal slash with a glow
    slash = QPainterPath()
    slash.moveTo(120, 900)
    slash.lineTo(905, 95)
    slash.lineTo(880, 150)
    slash.lineTo(165, 905)
    slash.closeSubpath()
    for width, alpha in ((70, 35), (40, 70), (18, 130)):
        p.setPen(QPen(QColor(GLOW.red(), GLOW.green(), GLOW.blue(), alpha), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(slash)
    p.setPen(Qt.NoPen)
    p.setBrush(BLADE)
    p.drawPath(slash)

    # Spark where the blade cuts the strip
    center = QPointF(462, 548)  # on the blade, where it crosses the film strip
    spark = QRadialGradient(center, 150)
    spark.setColorAt(0, QColor(255, 255, 255, 255))
    spark.setColorAt(0.25, QColor(255, 230, 160, 220))
    spark.setColorAt(1, QColor(255, 120, 60, 0))
    p.setBrush(spark)
    p.drawEllipse(center, 150, 150)
    p.setBrush(QColor("#ffffff"))
    star = QPainterPath()
    rays = 4 if simple else 8
    for i in range(rays * 2):
        r = (130 if i % 2 == 0 else 22) * (1 if i % 4 == 0 or simple else 0.6 if i % 2 == 0 else 1)
        t = QTransform().rotate(i * 180 / rays + 15)
        pt = t.map(QPointF(r, 0)) + center
        star.moveTo(pt) if i == 0 else star.lineTo(pt)
    star.closeSubpath()
    p.drawPath(star)
    p.end()
    return img


def save_ico(images: list[QImage], path: Path) -> None:
    """Writes a Windows .ico holding PNG images of every size."""
    blobs = []
    for img in images:
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        blobs.append(bytes(buf.data()))
    header = (0).to_bytes(2, "little") + (1).to_bytes(2, "little") + len(images).to_bytes(2, "little")
    entries, offset = b"", 6 + 16 * len(images)
    for img, blob in zip(images, blobs):
        dim = 0 if img.width() >= 256 else img.width()  # 0 means 256 in the .ico format
        entries += bytes([dim, dim, 0, 0]) + (1).to_bytes(2, "little") + (32).to_bytes(2, "little")
        entries += len(blob).to_bytes(4, "little") + offset.to_bytes(4, "little")
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    OUT.mkdir(exist_ok=True)
    # Draw big and shrink, so edges are smooth at every size.
    images = []
    for size in ICO_SIZES:
        big = draw(size * 4, simple=size <= 32)
        images.append(big.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    save_ico(images, OUT / "icon.ico")
    draw(1024, simple=False).scaled(512, 512, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(OUT / "icon-512.png"))
    print("saved", OUT / "icon.ico", "and", OUT / "icon-512.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
