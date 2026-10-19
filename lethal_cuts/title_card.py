"""The window for a long video's series title card: series name, episode number, who's playing,
and up to four commanders (picked from Scryfall), with a live preview."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QSpinBox,
    QVBoxLayout,
)

from . import pause_title
from .card_picker import CardPicker

PREVIEW = (480, 270)


class TitleCardDialog(QDialog):
    def __init__(self, card: dict, parent=None, picker=CardPicker):
        super().__init__(parent)
        self.setWindowTitle("Title card")
        self.card = dict(card, cards=list(card.get("cards", [])))
        self.removed = False
        self._picker = picker
        self.series = QLineEdit(self.card.get("series", ""))
        self.series.setPlaceholderText("Your series or channel name")
        self.episode = QSpinBox()
        self.episode.setRange(1, 9999)
        self.episode.setValue(int(self.card.get("episode", 1)))
        self.episode.setToolTip("Counts up by itself after each long video you export with a title card")
        self.title = QLineEdit(self.card.get("title", ""))
        self.title.setPlaceholderText("Who's playing, e.g. Atraxa vs Krenko vs Yuriko vs Edgar")
        self.seconds = QDoubleSpinBox()
        self.seconds.setRange(2, 10)
        self.seconds.setSingleStep(0.5)
        self.seconds.setDecimals(1)
        self.seconds.setSuffix(" seconds")
        self.seconds.setValue(pause_title.title_seconds(self.card))
        self.commanders = QListWidget()
        self.commanders.setMaximumHeight(110)
        add = QPushButton("Add commander...")
        add.setToolTip("Search Scryfall for a commander: its art and card go on the title card")
        add.clicked.connect(self.add_commander)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self.remove_commander)
        card_buttons = QHBoxLayout()
        card_buttons.addWidget(add)
        card_buttons.addWidget(self.remove_btn)
        card_buttons.addStretch(1)
        form = QFormLayout()
        form.addRow("Series", self.series)
        form.addRow("Episode", self.episode)
        form.addRow("Title", self.title)
        form.addRow("Shows for", self.seconds)
        form.addRow("Commanders", self.commanders)
        form.addRow("", card_buttons)
        self.preview = QLabel()
        self.preview.setFixedSize(*PREVIEW)
        self.preview.setStyleSheet("background: #000; border: 1px solid #3a3150;")
        save = QPushButton("Save")
        save.setObjectName("exportButton")
        save.clicked.connect(self.accept)
        drop = QPushButton("Remove title card")
        drop.clicked.connect(self._remove_card)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(drop)
        buttons.addStretch(1)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        top = QHBoxLayout()
        top.addLayout(form, 1)
        top.addWidget(self.preview, 0, Qt.AlignTop)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(buttons)
        for w in (self.series, self.title):
            w.textChanged.connect(self._refresh)
        self.episode.valueChanged.connect(self._refresh)
        self.seconds.valueChanged.connect(self._refresh)
        self._fill_commanders()

    def _fill_commanders(self):
        self.commanders.clear()
        self.commanders.addItems([c.get("name", "Card") for c in self.card["cards"]])
        self.remove_btn.setEnabled(bool(self.card["cards"]))
        self._refresh()

    def add_commander(self):
        if len(self.card["cards"]) >= pause_title.MAX_COMMANDERS:
            return
        picker = self._picker(self)
        if picker.exec() and picker.card:
            self.card["cards"].append(picker.card)
            self._fill_commanders()

    def remove_commander(self):
        row = self.commanders.currentRow()
        if 0 <= row < len(self.card["cards"]):
            del self.card["cards"][row]
            self._fill_commanders()

    def _refresh(self, *_):
        self.card.update(series=self.series.text().strip(), episode=self.episode.value(), title=self.title.text().strip(),
                         seconds=self.seconds.value())
        image = pause_title.render_title(self.card, 1920, 1080)
        self.preview.setPixmap(QPixmap.fromImage(image).scaled(*PREVIEW, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _remove_card(self):
        self.removed = True
        self.accept()
