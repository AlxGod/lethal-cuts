"""The timeline bar under the video: the whole game from left to right.

Shows every clip as a shaded, numbered bar, the start mark while a clip is
being marked, moments marked while recording, and the playhead. Clicking or
dragging on it jumps the video. The mouse wheel zooms in, so a 3-hour game
can be worked on a few minutes at a time.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from .project import Clip, format_time

CLIP_COLORS = [QColor("#b0304a"), QColor("#7b4fc9")]  # alternate so neighbouring clips stand apart
SELECTED_COLOR = QColor("#f0b840")
PLAYHEAD_COLOR = QColor("#ffffff")
PENDING_COLOR = QColor("#40c08a")
CUT_COLOR = QColor("#d0404a")  # long videos: the parts being cut out
MOMENT_COLOR = QColor("#f0b840")
MIN_VIEW_SECONDS = 20.0        # the most it zooms in
ZOOM_STEP = 0.8                # each wheel notch shows this much of what was shown
LABEL_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200]  # seconds between time labels
LABEL_GAP = 80                 # pixels wanted between time labels


class Timeline(QWidget):
    seek_requested = Signal(float)  # seconds
    clip_clicked = Signal(int)      # index into the clip list
    view_changed = Signal()         # zoomed or scrolled

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(64)
        self.setMouseTracking(True)
        self.duration = 0.0
        self.position = 0.0
        self.clips: list[Clip] = []
        self.selected = -1
        self.pending_start: float | None = None
        self.moments: list[float] = []
        self.moment_window = 300.0  # each moment covers this many seconds before it
        self.clip_colors = list(CLIP_COLORS)
        self.cut_style = False  # True while making a long video: the bars are cuts
        self.view_start = 0.0
        self.view_length = 0.0  # 0 = the whole video
        self._dragging = False

    # --- state from the main window ---
    def set_duration(self, seconds: float) -> None:
        self.duration = seconds
        self.view_start, self.view_length = 0.0, 0.0
        self.view_changed.emit()
        self.update()

    def set_position(self, seconds: float) -> None:
        moved = abs(seconds - self.position) > 0.001
        self.position = seconds
        if moved and self.zoomed:
            start, length = self.view()
            if not start <= seconds <= start + length:
                # Keep the playhead in sight while playing or jumping, a page at a time
                self.set_view_start(seconds - length * 0.1)
        self.update()

    def set_clips(self, clips: list[Clip], selected: int = -1) -> None:
        self.clips = clips
        self.selected = selected
        self.update()

    def set_moments(self, moments: list[float], window: float) -> None:
        self.moments = list(moments)
        self.moment_window = window
        self.update()

    def set_colors(self, a: str, b: str) -> None:
        self.clip_colors = [QColor(a), QColor(b)]
        self.update()

    def set_pending_start(self, seconds: float | None) -> None:
        self.pending_start = seconds
        self.update()

    # --- zoom ---
    @property
    def zoomed(self) -> bool:
        return 0 < self.view_length < self.duration

    def view(self) -> tuple[float, float]:
        """The part of the video shown: (start, length) in seconds."""
        if not self.zoomed:
            return 0.0, self.duration
        return self.view_start, self.view_length

    def set_view_start(self, seconds: float) -> None:
        if not self.zoomed:
            return
        self.view_start = min(max(seconds, 0.0), self.duration - self.view_length)
        self.view_changed.emit()
        self.update()

    def zoom(self, factor: float, anchor: float | None = None) -> None:
        """Shows factor times as much (under 1 zooms in), keeping the anchor time where it is."""
        if self.duration <= 0:
            return
        start, length = self.view()
        anchor = self.position if anchor is None else anchor
        frac = (anchor - start) / length if length else 0.5
        new_length = min(max(length * factor, min(MIN_VIEW_SECONDS, self.duration)), self.duration)
        if new_length >= self.duration:
            self.view_start, self.view_length = 0.0, 0.0
        else:
            self.view_length = new_length
            self.view_start = min(max(anchor - frac * new_length, 0.0), self.duration - new_length)
        self.view_changed.emit()
        self.update()

    def zoom_out_fully(self) -> None:
        self.view_start, self.view_length = 0.0, 0.0
        self.view_changed.emit()
        self.update()

    # --- geometry ---
    def _track(self) -> QRectF:
        return QRectF(8, 18, self.width() - 16, self.height() - 26)

    def _x(self, seconds: float) -> float:
        """Where a time is drawn. Times outside the zoomed view land just off the track's ends."""
        t = self._track()
        start, length = self.view()
        if length <= 0:
            return t.left()
        frac = min(max((seconds - start) / length, -0.01), 1.01)
        return t.left() + t.width() * frac

    def _seconds_at(self, x: float) -> float:
        t = self._track()
        if t.width() <= 0:
            return 0.0
        start, length = self.view()
        return min(max(start + (x - t.left()) / t.width() * length, 0.0), self.duration)

    def _label_step(self, length: float) -> float:
        labels = max(self._track().width() / LABEL_GAP, 1)
        return next((s for s in LABEL_STEPS if length / s <= labels), LABEL_STEPS[-1])

    # --- drawing ---
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = self._track()
        p.fillRect(self.rect(), QColor("#16121e"))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2a2338"))
        p.drawRoundedRect(track, 4, 4)
        p.setClipRect(QRectF(0, 0, self.width(), self.height()))
        start, length = self.view()

        # Time labels along the top, at round times (every 10 minutes, every 30 seconds...)
        if self.duration > 0:
            p.setPen(QColor("#8a80a0"))
            p.setFont(QFont("Segoe UI", 8))
            step = self._label_step(length)
            first = int(start // step) * step
            secs = first
            while secs <= start + length + 0.001:
                if secs >= start - 0.001:
                    x = self._x(secs)
                    label = format_time(secs, tenths=False)
                    w = p.fontMetrics().horizontalAdvance(label)
                    p.drawText(int(min(max(x - w / 2, 0), self.width() - w)), 12, label)
                    p.drawLine(int(x), int(track.top()), int(x), int(track.top() + 3))
                secs += step

        p.setClipRect(track)
        # Moments marked while recording: a gold window over the minutes before each key press
        for m in self.moments:
            x1, x2 = self._x(m - self.moment_window), self._x(m)
            if x2 < track.left() or x1 > track.right():
                continue
            shade = QColor(MOMENT_COLOR)
            shade.setAlpha(45)
            p.setPen(Qt.NoPen)
            p.setBrush(shade)
            p.drawRect(QRectF(x1, track.top(), max(x2 - x1, 1), track.height()))

        # Clip bars
        number_font = QFont("Segoe UI", 8, QFont.Bold)
        p.setFont(number_font)
        for i, clip in enumerate(self.clips):
            if clip.end < start or clip.start > start + length:
                continue
            x1, x2 = self._x(clip.start), self._x(clip.end)
            rect = QRectF(x1, track.top(), max(x2 - x1, 3), track.height())
            if self.cut_style:
                # Cuts: dark and striped, since these parts get left out
                color = SELECTED_COLOR if i == self.selected else CUT_COLOR
                p.setPen(QPen(color, 1))
                p.setBrush(QColor(20, 8, 12, 220))
                p.drawRect(rect)
                p.setBrush(QBrush(color, Qt.BDiagPattern))
                p.drawRect(rect)
            else:
                color = SELECTED_COLOR if i == self.selected else self.clip_colors[i % 2]
                fill = QColor(color)
                fill.setAlpha(170)
                p.setPen(QPen(color, 1))
                p.setBrush(fill)
                p.drawRect(rect)
            label = str(i + 1)
            visible = rect.intersected(track)
            if p.fontMetrics().horizontalAdvance(label) + 4 <= visible.width():
                p.setPen(QColor("#ffffff"))
                p.drawText(visible, Qt.AlignCenter, label)

        # Moment flags: where the key was pressed
        for m in self.moments:
            x = self._x(m)
            if not track.left() - 1 <= x <= track.right() + 1:
                continue
            p.setPen(QPen(MOMENT_COLOR, 2))
            p.drawLine(int(x), int(track.top()), int(x), int(track.bottom()))
            p.setPen(Qt.NoPen)
            p.setBrush(MOMENT_COLOR)
            top = track.top()
            p.drawPolygon(QPolygonF([QPointF(x, top), QPointF(x - 6, top), QPointF(x, top + 8)]))

        # Clip being marked: from the start mark to the playhead
        if self.pending_start is not None:
            x1 = self._x(self.pending_start)
            x2 = self._x(max(self.position, self.pending_start))
            mark = CUT_COLOR if self.cut_style else PENDING_COLOR
            fill = QColor(mark)
            fill.setAlpha(90)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawRect(QRectF(x1, track.top(), max(x2 - x1, 1), track.height()))
            p.setPen(QPen(mark, 2))
            p.drawLine(int(x1), int(track.top()), int(x1), int(track.bottom()))

        # Playhead
        p.setClipping(False)
        if start <= self.position <= start + length:
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

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self.zoomed:
            self.zoom_out_fully()  # back to the whole game

    def mouseMoveEvent(self, event):
        if self.duration > 0:
            self.setToolTip(format_time(self._seconds_at(event.position().x())) +
                            ("" if self.zoomed else "\nScroll the mouse wheel here to zoom in"))
        if self._dragging:
            self.seek_requested.emit(self._seconds_at(event.position().x()))

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def wheelEvent(self, event):
        if self.duration <= 0:
            return
        delta = event.angleDelta()
        notches = (delta.y() or delta.x()) / 120
        if not notches:
            return
        if event.modifiers() & Qt.ShiftModifier or (delta.x() and not delta.y()):
            start, length = self.view()
            self.set_view_start(start - notches * length * 0.2)  # Shift + wheel slides along
        else:
            self.zoom(ZOOM_STEP ** notches, self._seconds_at(event.position().x()))
        event.accept()
