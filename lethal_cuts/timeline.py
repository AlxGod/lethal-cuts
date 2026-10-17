"""The timeline bar under the video: the whole game from left to right.

Shows every clip as a shaded, numbered bar, the start mark while a clip is
being marked, and the playhead. Clicking or dragging on it jumps the video.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .project import Clip, format_time

CLIP_COLORS = [QColor("#b0304a"), QColor("#7b4fc9")]  # alternate so neighbouring clips stand apart
SELECTED_COLOR = QColor("#f0b840")
PLAYHEAD_COLOR = QColor("#ffffff")
PENDING_COLOR = QColor("#40c08a")


class Timeline(QWidget):
    seek_requested = Signal(float)  # seconds
    clip_clicked = Signal(int)      # index into the clip list

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(64)
        self.setMouseTracking(True)
        self.duration = 0.0
        self.position = 0.0
        self.clips: list[Clip] = []
        self.selected = -1
        self.pending_start: float | None = None
        self._dragging = False

    # --- state from the main window ---
    def set_duration(self, seconds: float) -> None:
        self.duration = seconds
        self.update()

    def set_position(self, seconds: float) -> None:
        self.position = seconds
        self.update()

    def set_clips(self, clips: list[Clip], selected: int = -1) -> None:
        self.clips = clips
        self.selected = selected
        self.update()

    def set_pending_start(self, seconds: float | None) -> None:
        self.pending_start = seconds
        self.update()

    # --- geometry ---
    def _track(self) -> QRectF:
        return QRectF(8, 18, self.width() - 16, self.height() - 26)

    def _x(self, seconds: float) -> float:
        t = self._track()
        if self.duration <= 0:
            return t.left()
        return t.left() + t.width() * min(max(seconds / self.duration, 0.0), 1.0)

    def _seconds_at(self, x: float) -> float:
        t = self._track()
        if t.width() <= 0:
            return 0.0
        return min(max((x - t.left()) / t.width(), 0.0), 1.0) * self.duration

    # --- drawing ---
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = self._track()
        p.fillRect(self.rect(), QColor("#16121e"))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2a2338"))
        p.drawRoundedRect(track, 4, 4)

        # Time labels along the top
        if self.duration > 0:
            p.setPen(QColor("#8a80a0"))
            p.setFont(QFont("Segoe UI", 8))
            for i in range(0, 11):
                secs = self.duration * i / 10
                x = self._x(secs)
                label = format_time(secs, tenths=False)
                w = p.fontMetrics().horizontalAdvance(label)
                p.drawText(int(min(max(x - w / 2, 0), self.width() - w)), 12, label)

        # Clip bars
        number_font = QFont("Segoe UI", 8, QFont.Bold)
        p.setFont(number_font)
        for i, clip in enumerate(self.clips):
            x1, x2 = self._x(clip.start), self._x(clip.end)
            rect = QRectF(x1, track.top(), max(x2 - x1, 3), track.height())
            color = SELECTED_COLOR if i == self.selected else CLIP_COLORS[i % 2]
            fill = QColor(color)
            fill.setAlpha(170)
            p.setPen(QPen(color, 1))
            p.setBrush(fill)
            p.drawRect(rect)
            label = str(i + 1)
            if p.fontMetrics().horizontalAdvance(label) + 4 <= rect.width():
                p.setPen(QColor("#ffffff"))
                p.drawText(rect, Qt.AlignCenter, label)

        # Clip being marked: from the start mark to the playhead
        if self.pending_start is not None:
            x1 = self._x(self.pending_start)
            x2 = self._x(max(self.position, self.pending_start))
            fill = QColor(PENDING_COLOR)
            fill.setAlpha(90)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawRect(QRectF(x1, track.top(), max(x2 - x1, 1), track.height()))
            p.setPen(QPen(PENDING_COLOR, 2))
            p.drawLine(int(x1), int(track.top() - 4), int(x1), int(track.bottom() + 4))

        # Playhead
        x = self._x(self.position)
        p.setPen(QPen(PLAYHEAD_COLOR, 2))
        p.drawLine(int(x), int(track.top() - 6), int(x), int(track.bottom() + 6))
        p.end()

    # --- mouse ---
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self.duration <= 0:
            return
        self._dragging = True
        secs = self._seconds_at(event.position().x())
        for i, clip in enumerate(self.clips):
            if clip.start <= secs <= clip.end:
                self.clip_clicked.emit(i)
                break
        self.seek_requested.emit(secs)

    def mouseMoveEvent(self, event):
        if self.duration > 0:
            self.setToolTip(format_time(self._seconds_at(event.position().x())))
        if self._dragging:
            self.seek_requested.emit(self._seconds_at(event.position().x()))

    def mouseReleaseEvent(self, event):
        self._dragging = False
