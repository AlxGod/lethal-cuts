"""The short first-time walkthrough: a card that points at each part of the window in turn."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class _Highlight(QWidget):
    """A glowing outline drawn around the part of the window being explained."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#f0b840"), 3))
        p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 8, 8)


class _Card(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("walkCard")
        self.setFixedWidth(360)
        self.counter = QLabel()
        self.counter.setObjectName("dimLabel")
        self.title = QLabel()
        self.title.setObjectName("panelTitle")
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.skip = QPushButton("Skip")
        self.back = QPushButton("Back")
        self.next = QPushButton("Next")
        self.next.setObjectName("exportButton")
        buttons = QHBoxLayout()
        buttons.addWidget(self.skip)
        buttons.addStretch(1)
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(self.counter)
        layout.addWidget(self.title)
        layout.addWidget(self.body)
        layout.addSpacing(6)
        layout.addLayout(buttons)


class Walkthrough(QObject):
    finished = Signal()

    def __init__(self, window: QWidget, steps: list[tuple[QWidget | None, str, str]]):
        """steps: (part of the window to point at, or None for the middle; title; text)."""
        super().__init__(window)
        self.window = window
        self.steps = steps
        self.index = 0
        self.highlight = _Highlight(window)
        self.card = _Card(window)
        self.card.next.clicked.connect(self.next)
        self.card.back.clicked.connect(self.back)
        self.card.skip.clicked.connect(self.finish)

    def start(self):
        self.index = 0
        self._show()

    def next(self):
        if self.index >= len(self.steps) - 1:
            self.finish()
        else:
            self.index += 1
            self._show()

    def back(self):
        if self.index > 0:
            self.index -= 1
            self._show()

    def finish(self):
        self.highlight.hide()
        self.card.hide()
        self.finished.emit()

    @property
    def active(self) -> bool:
        return self.card.isVisible()

    def _show(self):
        target, title, text = self.steps[self.index]
        last = self.index == len(self.steps) - 1
        self.card.counter.setText(f"{self.index + 1} of {len(self.steps)}")
        self.card.title.setText(title)
        self.card.body.setText(text)
        self.card.back.setEnabled(self.index > 0)
        self.card.next.setText("Got it" if last else "Next")
        self.card.skip.setVisible(not last)
        self.card.adjustSize()

        area = self.window.rect()
        if target is not None and target.isVisible():
            top_left = target.mapTo(self.window, QPoint(0, 0))
            rect = QRect(top_left, target.size()).adjusted(-6, -6, 6, 6)
            self.highlight.setGeometry(rect)
            self.highlight.show()
            self.highlight.raise_()
            self.card.move(self._place_card(rect, area))
        else:
            self.highlight.hide()
            self.card.move(area.center() - QPoint(self.card.width() // 2, self.card.height() // 2))
        self.card.show()
        self.card.raise_()

    def _place_card(self, target: QRect, area: QRect) -> QPoint:
        """Next to the highlighted part: to its left, right, above or below, whichever fits."""
        w, h, gap = self.card.width(), self.card.height(), 14
        options = [
            QPoint(target.left() - w - gap, target.top()),
            QPoint(target.right() + gap, target.top()),
            QPoint(target.left(), target.top() - h - gap),
            QPoint(target.left(), target.bottom() + gap),
        ]
        for p in options:
            if area.contains(QRect(p, self.card.size())):
                return p
        # Nothing fits cleanly (a big target): keep the card inside the window.
        p = options[0]
        return QPoint(min(max(p.x(), 10), area.width() - w - 10), min(max(target.center().y() - h // 2, 10), area.height() - h - 10))
