"""The timeline bar under the video: the whole game from left to right.

Shows every clip as a shaded, numbered bar, the start mark while a clip is
being marked, moments marked while recording, and the playhead. Clicking or
dragging on it jumps the video. The mouse wheel zooms in, so a 3-hour game
can be worked on a few minutes at a time. A thin strip along the bottom shows
the cards and text on screen; their bars can be dragged to move them, or by
their ends to change how long they show.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from .overlays import MIN_SECONDS, describe
from .project import Clip, Overlay, format_time

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
LANE_HEIGHT = 16               # the strip for cards and text
OVERLAY_COLORS = {"text": QColor("#38b2c4"), "card": QColor("#e07a3a")}
EDGE_GRAB = 6                  # pixels: grabbing this close to a bar's end changes its length


class Timeline(QWidget):
    seek_requested = Signal(float)  # seconds
    clip_clicked = Signal(int)      # index into the clip list
    view_changed = Signal()         # zoomed or scrolled
    overlay_clicked = Signal(int)   # index into the overlay list
    overlay_timed = Signal(int)     # an overlay's start or end was dragged (changed in place)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(64 + LANE_HEIGHT + 4)
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
        self.overlays: list[Overlay] = []
        self.selected_overlay = -1
        self._overlay_drag: tuple | None = None  # (index, "move"/"start"/"end", grab time, start, end)

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

    def set_overlays(self, overlays: list[Overlay], selected: int = -1) -> None:
        self.overlays = overlays
        self.selected_overlay = selected
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
        return QRectF(8, 18, self.width() - 16, self.height() - 30 - LANE_HEIGHT)

    def _lane(self) -> QRectF:
        t = self._track()
        return QRectF(t.left(), t.bottom() + 4, t.width(), LANE_HEIGHT)

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

        self._draw_lane(p, start, length)

        # Playhead
        p.setClipping(False)
        if start <= self.position <= start + length:
            x = self._x(self.position)
            p.setPen(QPen(PLAYHEAD_COLOR, 2))
            p.drawLine(int(x), int(track.top() - 6), int(x), int(self._lane().bottom() + 2))
        p.end()

    def _draw_lane(self, p: QPainter, start: float, length: float):
        """The strip of cards and text along the bottom."""
        lane = self._lane()
        p.setClipping(False)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#211b2c"))
        p.drawRoundedRect(lane, 3, 3)
        p.setClipRect(lane)
        if not self.overlays:
            p.setPen(QColor("#5c5370"))
            p.setFont(QFont("Segoe UI", 7))
            p.drawText(lane, Qt.AlignCenter, "Cards and text on screen show here")
            return
        p.setFont(QFont("Segoe UI", 7, QFont.Bold))
        order = sorted(range(len(self.overlays)), key=lambda i: i == self.selected_overlay)  # selected on top
        for i in order:
            o = self.overlays[i]
            if o.end < start or o.start > start + length:
                continue
            x1, x2 = self._x(o.start), self._x(o.end)
            rect = QRectF(x1, lane.top() + 1, max(x2 - x1, 4), lane.height() - 2)
            color = OVERLAY_COLORS.get(o.kind, OVERLAY_COLORS["text"])
            fill = QColor(color)
            fill.setAlpha(230 if i == self.selected_overlay else 150)
            p.setPen(QPen(QColor("#ffffff") if i == self.selected_overlay else color, 1.5))
            p.setBrush(fill)
            p.drawRoundedRect(rect, 3, 3)
            label = describe(o)
            visible = rect.intersected(lane).adjusted(3, 0, -3, 0)
            if visible.width() > 20:
                p.setPen(QColor("#ffffff"))
                p.drawText(visible, Qt.AlignVCenter | Qt.AlignLeft,
                           p.fontMetrics().elidedText(label, Qt.ElideRight, int(visible.width())))

    def _overlay_at(self, x: float, y: float):
        """(index, "start"/"end"/"move") for the overlay bar under the mouse, or None."""
        lane = self._lane()
        if not lane.top() - 2 <= y <= lane.bottom() + 2:
            return None
        order = sorted(range(len(self.overlays)), key=lambda i: i == self.selected_overlay, reverse=True)
        for i in order:
            o = self.overlays[i]
            x1, x2 = self._x(o.start), self._x(o.end)
            if x1 - EDGE_GRAB <= x <= max(x2, x1 + 4) + EDGE_GRAB:
                if x2 - x1 > EDGE_GRAB * 3:
                    if abs(x - x1) <= EDGE_GRAB:
                        return i, "start"
                    if abs(x - x2) <= EDGE_GRAB:
                        return i, "end"
                if x1 <= x <= max(x2, x1 + 4):
                    return i, "move"
        return None

    # --- mouse ---
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self.duration <= 0:
            return
        hit = self._overlay_at(event.position().x(), event.position().y())
        if hit:
            i, part = hit
            o = self.overlays[i]
            self.selected_overlay = i
            self._overlay_drag = (i, part, self._seconds_at(event.position().x()), o.start, o.end)
            self.overlay_clicked.emit(i)
            self.seek_requested.emit(o.end if part == "end" else o.start)
            self.update()
            return
        self._dragging = True
        secs = self._seconds_at(event.position().x())
        for i, clip in enumerate(self.clips):
            if clip.start <= secs <= clip.end:
                self.clip_clicked.emit(i)
                break
        self.seek_requested.emit(secs)

    def mouseDoubleClickEvent(self, event):
        if self._overlay_at(event.position().x(), event.position().y()):
            return  # double-clicking a card or text bar shouldn't zoom out
        if event.button() == Qt.LeftButton and self.zoomed:
            self.zoom_out_fully()  # back to the whole game

    def mouseMoveEvent(self, event):
        x, y = event.position().x(), event.position().y()
        if self._overlay_drag:
            self._drag_overlay(self._seconds_at(x))
            return
        hit = self._overlay_at(x, y) if self.duration > 0 else None
        if hit:
            o = self.overlays[hit[0]]
            self.setCursor(Qt.SizeHorCursor if hit[1] != "move" else Qt.OpenHandCursor)
            self.setToolTip(f"{describe(o)}: {format_time(o.start)} to {format_time(o.end)}\n"
                            "Drag to move it, or drag an end to change how long it shows")
            return
        self.unsetCursor()
        if self.duration > 0:
            self.setToolTip(format_time(self._seconds_at(x)) +
                            ("" if self.zoomed else "\nScroll the mouse wheel here to zoom in"))
        if self._dragging:
            self.seek_requested.emit(self._seconds_at(event.position().x()))

    def mouseReleaseEvent(self, event):
        self._dragging = False
        self._overlay_drag = None

    def _drag_overlay(self, secs: float):
        i, part, grabbed, start, end = self._overlay_drag
        o = self.overlays[i]
        length = end - start
        if part == "move":
            o.start = round(min(max(start + secs - grabbed, 0.0), max(self.duration - length, 0.0)), 3)
            o.end = round(o.start + length, 3)
            shown = o.start
        elif part == "start":
            o.start = round(min(max(secs, 0.0), o.end - MIN_SECONDS), 3)
            shown = o.start
        else:
            o.end = round(max(min(secs, self.duration), o.start + MIN_SECONDS), 3)
            shown = o.end
        self.update()
        self.overlay_timed.emit(i)
        self.seek_requested.emit(shown)  # show the frame where the moved edge lands

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
