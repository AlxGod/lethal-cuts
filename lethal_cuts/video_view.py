"""The video picture, with the tall 9:16 crop box and any cards or text drawn on top.

The video is drawn inside a QGraphicsView (a canvas). The crop box and the overlays
are drawn in this view's foreground, so the vertical preview can zoom the same canvas
into the box without the box's outline showing up in it. Overlays sit inside the
finished video's frame (the crop box for Shorts, the whole picture for long videos)
and can be dragged around and resized there.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsTextItem, QGraphicsView

from . import crop as cropmath
from . import overlays as ov
from .project import Crop, Overlay

HANDLE = 12          # corner handle size in pixels
BOX_COLOR = QColor("#f0b840")
UNSET_COLOR = QColor("#ffffff")


class VideoView(QGraphicsView):
    clicked = Signal()
    crop_changed = Signal(object)  # Crop, while the user drags or resizes the box
    overlay_pressed = Signal(int)  # index of the overlay clicked on the video
    overlay_changed = Signal(int)  # an overlay was moved or resized (changed in place)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QBrush(QColor("#000000")))
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.NoFocus)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setMouseTracking(True)

        self.video_item = QGraphicsVideoItem()
        self.video_item.setAspectRatioMode(Qt.KeepAspectRatio)
        # nativeSize() stays empty with Qt's FFmpeg player, so the size comes from the video sink.
        self.video_item.videoSink().videoSizeChanged.connect(self._layout)
        self.scene().addItem(self.video_item)

        self.hint = QGraphicsTextItem("Open a game video (Ctrl+O), or drag one onto this window")
        self.hint.setDefaultTextColor(QColor("#9a8fb0"))
        self.hint.setFont(QFont("Segoe UI", 14))
        self.scene().addItem(self.hint)

        self.crop: Crop | None = None   # the box being shown, or None when no clip is selected
        self.crop_is_set = False        # False = the centered default nobody has placed yet
        self.previewing = False
        self.box_color = QColor(BOX_COLOR)
        self._drag: tuple | None = None  # ("move", grab offset) or ("resize", fixed corner), or an overlay drag

        # Overlays: set by the main window as the video plays
        self.overlays: list[Overlay] = []
        self.overlay_time = 0.0
        self.overlay_crop: Crop | None = None  # Shorts: the box the overlays sit in. None = the whole picture
        self.overlay_size = (1920, 1080)       # the finished video's size in pixels
        self.overlay_bounds: tuple[float, float] | None = None  # previewing one clip: overlays are cut to it
        self.selected_overlay = -1
        self.editing = True                    # paused: show the selected overlay's outline and handle

    # --- state from the main window ---
    def set_has_video(self, has_video: bool) -> None:
        self.hint.setVisible(not has_video)

    def video_rect(self) -> QRectF:
        """Where the video picture sits on the canvas (inside the black bars)."""
        area = QRectF(self.video_item.pos(), self.video_item.size())
        native = self.source_size()
        if native.isEmpty():
            return area
        scale = min(area.width() / native.width(), area.height() / native.height())
        w, h = native.width() * scale, native.height() * scale
        return QRectF(area.left() + (area.width() - w) / 2, area.top() + (area.height() - h) / 2, w, h)

    def aspect(self) -> float:
        r = self.video_rect()
        return r.width() / r.height() if r.height() > 0 else 16 / 9

    def source_size(self) -> QSizeF:
        """The video's real size in pixels (e.g. 3840x2160), or empty before it loads."""
        return QSizeF(self.video_item.videoSink().videoSize())

    def has_picture(self) -> bool:
        return not self.source_size().isEmpty()

    def show_crop(self, crop: Crop | None, is_set: bool = True) -> None:
        """Shows a clip's box. Pass None to hide it (no clip selected)."""
        self.crop = crop
        self.crop_is_set = is_set
        self._layout()

    def effective_crop(self) -> Crop:
        return self.crop or cropmath.default_crop(self.aspect())

    def set_preview(self, on: bool) -> None:
        self.previewing = on
        self._layout()

    def set_overlays(self, overlays: list[Overlay], t: float, crop: Crop | None, size: tuple[int, int],
                     selected: int, editing: bool, bounds: tuple[float, float] | None = None) -> None:
        self.overlays, self.overlay_time, self.overlay_crop = overlays, t, crop
        self.overlay_size, self.selected_overlay, self.editing, self.overlay_bounds = size, selected, editing, bounds
        self.viewport().update()

    # --- overlay geometry ---
    def overlay_frame(self) -> QRectF:
        """Where the finished video's picture sits on the canvas."""
        video = self.video_rect()
        if self.overlay_crop is None:
            return video
        return cropmath.to_rect(cropmath.clamp(self.overlay_crop, self.aspect()), video)

    def _shown_window(self, o: Overlay) -> tuple[float, float]:
        if self.overlay_bounds:
            return max(o.start, self.overlay_bounds[0]), min(o.end, self.overlay_bounds[1])
        return o.start, o.end

    def visible_overlays(self) -> list[int]:
        found = []
        for i, o in enumerate(self.overlays):
            a, b = self._shown_window(o)
            if a <= self.overlay_time <= b:
                found.append(i)
        return found

    def overlay_rect(self, index: int, animated: bool = True) -> tuple[QRectF, float]:
        """Where an overlay is drawn on the canvas right now, and how see-through it is."""
        o = self.overlays[index]
        w_px, h_px = self.overlay_size
        frame = self.overlay_frame()
        k = frame.width() / w_px
        image = ov.render(o, w_px, h_px)
        cx, cy = ov.resting_center(o, image.width(), image.height(), w_px, h_px)
        opacity, scale, dx = 1.0, 1.0, 0.0
        if animated:
            a, b = self._shown_window(o)
            opacity, scale, dx = ov.look(o, a, b, self.overlay_time, ov.slide_offsets(cx, image.width(), w_px))
        w, h = image.width() * scale, image.height() * scale
        rect = QRectF(frame.left() + (cx + dx - w / 2) * k, frame.top() + (cy - h / 2) * k, w * k, h * k)
        return rect, opacity

    def _handle_size(self) -> float:
        """The resize handle stays the same size on screen, even zoomed into the vertical preview."""
        return HANDLE / max(self.transform().m11(), 0.01)

    # --- layout ---
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout()

    def _layout(self):
        w, h = self.viewport().width(), self.viewport().height()
        self.scene().setSceneRect(0, 0, w, h)
        self.video_item.setSize(QSizeF(w, h))
        r = self.hint.boundingRect()
        self.hint.setPos((w - r.width()) / 2, (h - r.height()) / 2)
        if self.crop is not None and not self.crop_is_set:
            # Nobody has placed this box yet: keep it centered for the video's real shape.
            self.crop = cropmath.default_crop(self.aspect())
        if self.previewing and self.has_picture():
            # Zoom the canvas so the crop box fills the view: exactly the vertical clip.
            self.fitInView(cropmath.to_rect(self.effective_crop(), self.video_rect()), Qt.KeepAspectRatio)
        else:
            self.resetTransform()
        self.viewport().update()

    # --- drawing the box ---
    def drawForeground(self, painter: QPainter, rect: QRectF):
        if not self.has_picture():
            return
        if self.previewing:
            self._draw_preview_mask(painter)
        elif self.crop is not None:
            self._draw_crop(painter)
        self._draw_overlays(painter)

    def _draw_overlays(self, painter: QPainter):
        visible = self.visible_overlays()
        if not visible:
            return
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(self.overlay_frame())  # just like the export, nothing shows outside the video
        w_px, h_px = self.overlay_size
        for i in visible:
            rect, opacity = self.overlay_rect(i)
            if opacity <= 0.001:
                continue
            painter.setOpacity(opacity)
            painter.drawImage(rect, ov.render(self.overlays[i], w_px, h_px))
        painter.setOpacity(1.0)
        if self.editing and self.selected_overlay in visible:
            rect, _ = self.overlay_rect(self.selected_overlay, animated=False)
            pen = QPen(BOX_COLOR, 2 / max(self.transform().m11(), 0.01), Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            hs = self._handle_size()
            painter.setPen(Qt.NoPen)
            painter.setBrush(BOX_COLOR)
            painter.drawRect(QRectF(rect.right() - hs / 2, rect.bottom() - hs / 2, hs, hs))
        painter.restore()

    def _draw_crop(self, painter: QPainter):
        video = self.video_rect()
        box = cropmath.to_rect(self.crop, video)
        painter.setRenderHint(QPainter.Antialiasing)

        # Darken everything outside the box
        outside = QPainterPath()
        outside.addRect(video)
        inner = QPainterPath()
        inner.addRect(box)
        painter.fillPath(outside.subtracted(inner), QColor(0, 0, 0, 150))

        color = self.box_color if self.crop_is_set else UNSET_COLOR
        pen = QPen(color, 2, Qt.SolidLine if self.crop_is_set else Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(box)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        for corner in self._corners(box):
            painter.drawRect(QRectF(corner.x() - HANDLE / 2, corner.y() - HANDLE / 2, HANDLE, HANDLE))

        label = "9:16" if self.crop_is_set else "9:16  (drag to place)"
        source_h = self.source_size().height()
        if source_h and cropmath.source_pixels_tall(self.crop, source_h) < cropmath.OUTPUT_HEIGHT * 0.9:
            label += "  zoomed in: may look softer"
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        metrics = painter.fontMetrics()
        tag = QRectF(box.left(), box.top() - 22, metrics.horizontalAdvance(label) + 12, 20)
        if tag.top() < video.top():
            tag.moveTop(box.top() + 4)
            tag.moveLeft(box.left() + 4)
        painter.setBrush(QColor(0, 0, 0, 170))
        painter.drawRoundedRect(tag, 4, 4)
        painter.setPen(color)
        painter.drawText(tag, Qt.AlignCenter, label)

    def _draw_preview_mask(self, painter: QPainter):
        """In preview, black out whatever is beside the box, then label it."""
        box = cropmath.to_rect(self.effective_crop(), self.video_rect())
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        outside = QPainterPath()
        outside.addRect(visible.adjusted(-2, -2, 2, 2))
        inner = QPainterPath()
        inner.addRect(box)
        painter.fillPath(outside.subtracted(inner), QColor("#000000"))
        # The label is drawn in screen pixels so it doesn't grow with the zoom.
        painter.save()
        painter.resetTransform()
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
        painter.setPen(QColor("#f0b840"))
        painter.drawText(QRectF(0, 8, self.viewport().width(), 24), Qt.AlignHCenter,
                         "Vertical preview    (P or Esc to go back)")
        painter.restore()

    @staticmethod
    def _corners(box: QRectF) -> list[QPointF]:
        return [box.topLeft(), box.topRight(), box.bottomLeft(), box.bottomRight()]

    # --- dragging the box ---
    def _hit(self, pos: QPointF):
        """What the mouse is over: ('resize', fixed opposite corner), ('move', None) or None."""
        if self.crop is None or self.previewing or not self.has_picture():
            return None
        box = cropmath.to_rect(self.crop, self.video_rect())
        corners = self._corners(box)
        opposite = [box.bottomRight(), box.bottomLeft(), box.topRight(), box.topLeft()]
        for corner, fixed in zip(corners, opposite):
            if abs(pos.x() - corner.x()) <= HANDLE and abs(pos.y() - corner.y()) <= HANDLE:
                return ("resize", fixed)
        if box.contains(pos):
            return ("move", None)
        return None

    def _overlay_hit(self, pos: QPointF):
        """The overlay under the mouse: ("ov_resize", index) on the selected one's corner, ("ov_move", index), or None."""
        if not self.has_picture():
            return None
        visible = self.visible_overlays()
        if self.selected_overlay in visible:
            rect, _ = self.overlay_rect(self.selected_overlay, animated=False)
            hs = self._handle_size()
            if abs(pos.x() - rect.right()) <= hs and abs(pos.y() - rect.bottom()) <= hs:
                return ("ov_resize", self.selected_overlay)
        # The selected one first, then the one drawn on top
        for i in sorted(visible, key=lambda i: (i == self.selected_overlay, i), reverse=True):
            if self.overlay_rect(i, animated=False)[0].contains(pos):
                return ("ov_move", i)
        return None

    def _overlay_drag(self, pos: QPointF):
        kind, index, data = self._drag
        o = self.overlays[index]
        w_px, h_px = self.overlay_size
        frame = self.overlay_frame()
        if kind == "ov_move":
            center = pos - data
            o.x = min(max((center.x() - frame.left()) / frame.width(), 0.0), 1.0)
            o.y = min(max((center.y() - frame.top()) / frame.height(), 0.0), 1.0)
        else:
            middle, start_distance, start_size = data
            distance = math.hypot(pos.x() - middle.x(), pos.y() - middle.y())
            o.size = min(max(start_size * distance / max(start_distance, 1.0), ov.MIN_SIZE), ov.MAX_SIZE)
        # Keep what's stored where it's really shown (pushed in from the edges)
        image = ov.render(o, w_px, h_px)
        cx, cy = ov.resting_center(o, image.width(), image.height(), w_px, h_px)
        o.x, o.y = cx / w_px, cy / h_px
        self.viewport().update()
        self.overlay_changed.emit(index)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self.clicked.emit()
        pos = self.mapToScene(event.position().toPoint())
        over = self._overlay_hit(pos)
        if over:
            kind, index = over
            self.selected_overlay = index
            self.overlay_pressed.emit(index)
            rect, _ = self.overlay_rect(index, animated=False)
            if kind == "ov_move":
                self._drag = ("ov_move", index, pos - rect.center())
            else:
                middle = rect.center()
                self._drag = ("ov_resize", index, (middle, math.hypot(pos.x() - middle.x(), pos.y() - middle.y()),
                                                   self.overlays[index].size))
            self.viewport().update()
            return
        hit = self._hit(pos)
        if hit is None and self.crop is not None and not self.previewing and self.video_rect().contains(pos):
            # Clicking beside the box moves it there.
            box = cropmath.to_rect(self.crop, self.video_rect())
            self._move_box_to(pos - QPointF(box.width() / 2, box.height() / 2))
            hit = ("move", None)
        if hit and hit[0] == "move":
            box = cropmath.to_rect(self.crop, self.video_rect())
            self._drag = ("move", pos - box.topLeft())
        elif hit:
            self._drag = hit

    def mouseMoveEvent(self, event):
        pos = self.mapToScene(event.position().toPoint())
        if self._drag and self._drag[0].startswith("ov_"):
            self._overlay_drag(pos)
            return
        if self._drag is None:
            over = self._overlay_hit(pos)
            if over:
                self.viewport().setCursor(Qt.SizeFDiagCursor if over[0] == "ov_resize" else Qt.SizeAllCursor)
                return
            hit = self._hit(pos)
            if hit is None:
                self.viewport().unsetCursor()
            elif hit[0] == "move":
                self.viewport().setCursor(Qt.SizeAllCursor)
            else:
                fixed = hit[1]
                box = cropmath.to_rect(self.crop, self.video_rect())
                diagonal = (fixed == box.bottomRight()) or (fixed == box.topLeft())
                self.viewport().setCursor(Qt.SizeFDiagCursor if diagonal else Qt.SizeBDiagCursor)
            return
        kind, data = self._drag
        if kind == "move":
            self._move_box_to(pos - data)
        else:
            self._resize_box(data, pos)

    def mouseReleaseEvent(self, event):
        self._drag = None

    def mouseDoubleClickEvent(self, event):
        # Double-click the box: back to full height, centered where it is.
        pos = self.mapToScene(event.position().toPoint())
        if self._overlay_hit(pos) is None and self._hit(pos) is not None:
            c = self.crop
            aspect = self.aspect()
            h = cropmath.max_height(aspect)
            cx = c.x + cropmath.box_width(c.h, aspect) / 2
            self._emit(Crop(cx - cropmath.box_width(h, aspect) / 2, (1 - h) / 2, h))

    def wheelEvent(self, event):
        over = self._overlay_hit(self.mapToScene(event.position().toPoint()))
        if over and event.angleDelta().y():
            # Mouse wheel over a card or text makes it bigger or smaller
            o = self.overlays[over[1]]
            factor = 1.06 if event.angleDelta().y() > 0 else 1 / 1.06
            o.size = min(max(o.size * factor, ov.MIN_SIZE), ov.MAX_SIZE)
            self.viewport().update()
            self.overlay_changed.emit(over[1])
            return
        if self.crop is None or self.previewing:
            return
        # Mouse wheel resizes the box around its middle.
        c = self.crop
        aspect = self.aspect()
        factor = 0.95 if event.angleDelta().y() > 0 else 1.05
        h = min(max(c.h * factor, cropmath.MIN_HEIGHT), cropmath.max_height(aspect))
        cx = c.x + cropmath.box_width(c.h, aspect) / 2
        cy = c.y + c.h / 2
        self._emit(Crop(cx - cropmath.box_width(h, aspect) / 2, cy - h / 2, h))

    def _move_box_to(self, top_left: QPointF):
        video = self.video_rect()
        self._emit(Crop((top_left.x() - video.left()) / video.width(),
                        (top_left.y() - video.top()) / video.height(), self.crop.h))

    def _resize_box(self, fixed: QPointF, pos: QPointF):
        """Resizes from a corner, keeping the 9:16 shape and the opposite corner still."""
        video = self.video_rect()
        aspect = self.aspect()
        # Height follows whichever way the mouse moved further, keeping the shape.
        height_px = max(abs(pos.y() - fixed.y()), abs(pos.x() - fixed.x()) / cropmath.TALL)
        h = min(max(height_px / video.height(), cropmath.MIN_HEIGHT), cropmath.max_height(aspect))
        w = cropmath.box_width(h, aspect)
        fx = (fixed.x() - video.left()) / video.width()
        fy = (fixed.y() - video.top()) / video.height()
        x = fx - w if pos.x() < fixed.x() else fx
        y = fy - h if pos.y() < fixed.y() else fy
        # Don't let a resize push the box off the picture: shrink instead.
        if x < 0 or y < 0 or x + w > 1 or y + h > 1:
            room_w = fx if pos.x() < fixed.x() else 1 - fx
            room_h = fy if pos.y() < fixed.y() else 1 - fy
            h = max(min(h, room_h, room_w * aspect / cropmath.TALL), cropmath.MIN_HEIGHT)
            w = cropmath.box_width(h, aspect)
            x = fx - w if pos.x() < fixed.x() else fx
            y = fy - h if pos.y() < fixed.y() else fy
        self._emit(Crop(x, y, h))

    def _emit(self, crop: Crop):
        self.crop = cropmath.clamp(crop, self.aspect())
        self.crop_is_set = True
        self.viewport().update()
        self.crop_changed.emit(self.crop)
