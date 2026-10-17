"""The video picture.

Drawn inside a QGraphicsView (a canvas) rather than a plain video widget, so the
9:16 crop box can be drawn on top of the video in a later step.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSizeF, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import QGraphicsScene, QGraphicsTextItem, QGraphicsView, QFrame


class VideoView(QGraphicsView):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QBrush(QColor("#000000")))
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.NoFocus)

        self.video_item = QGraphicsVideoItem()
        self.video_item.setAspectRatioMode(Qt.KeepAspectRatio)
        self.scene().addItem(self.video_item)

        self.hint = QGraphicsTextItem("Open a game video (Ctrl+O), or drag one onto this window")
        self.hint.setDefaultTextColor(QColor("#9a8fb0"))
        self.hint.setFont(QFont("Segoe UI", 14))
        self.scene().addItem(self.hint)

    def set_has_video(self, has_video: bool) -> None:
        self.hint.setVisible(not has_video)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.viewport().width(), self.viewport().height()
        self.scene().setSceneRect(0, 0, w, h)
        self.video_item.setSize(QSizeF(w, h))
        r = self.hint.boundingRect()
        self.hint.setPos((w - r.width()) / 2, (h - r.height()) / 2)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
