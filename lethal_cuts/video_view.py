"""The video picture, with the tall 9:16 crop box drawn on top.

The video is drawn inside a QGraphicsView (a canvas). The crop box is drawn in
this view's foreground, so the vertical preview can zoom the same canvas into
the box without the box's outline showing up in it.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsTextItem, QGraphicsView

from . import crop as cropmath
from .project import Crop

HANDLE = 12          # corner handle size in pixels
BOX_COLOR = QColor("#f0b840")
UNSET_COLOR = QColor("#ffffff")


class VideoView(QGraphicsView):
    clicked = Signal()
    crop_changed = Signal(object)  # Crop, while the user drags or resizes the box

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
        self._drag: tuple | None = None  # ("move", grab offset) or ("resize", fixed corner)

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
            return
        if self.crop is None:
            return
        video = self.video_rect()
        box = cropmath.to_rect(self.crop, video)
        painter.setRenderHint(QPainter.Antialiasing)

        # Darken everything outside the box
        outside = QPainterPath()
        outside.addRect(video)
        inner = QPainterPath()
        inner.addRect(box)
        painter.fillPath(outside.subtracted(inner), QColor(0, 0, 0, 150))

        color = BOX_COLOR if self.crop_is_set else UNSET_COLOR
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

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self.clicked.emit()
        pos = self.mapToScene(event.position().toPoint())
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
        if self._drag is None:
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
        if self._hit(self.mapToScene(event.position().toPoint())) is not None:
            c = self.crop
            aspect = self.aspect()
            h = cropmath.max_height(aspect)
            cx = c.x + cropmath.box_width(c.h, aspect) / 2
            self._emit(Crop(cx - cropmath.box_width(h, aspect) / 2, (1 - h) / 2, h))

    def wheelEvent(self, event):
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
