"""The Editor's "On screen" tab: the cards and text shown on top of the video.

Adding one puts it at the playhead. It's then placed by dragging it on the video, and
timed by dragging its bar on the timeline. This panel lists them and edits the picked one.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QPlainTextEdit, QPushButton, QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import overlays as ov
from .help import HELP, HelpButton
from .project import Overlay, format_time

KIND_NAMES = {"text": "Text", "card": "Card"}


class OverlayPanel(QWidget):
    add_text = Signal()
    add_card = Signal()
    change_card = Signal(int)
    selected = Signal(int)    # row picked in the list, or -1
    edited = Signal(int)      # the picked overlay was changed here (in place)
    delete_requested = Signal(int)
    jump_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.overlays: list[Overlay] = []
        self._filling = False

        self.add_text_btn = QPushButton("+ Text")
        self.add_text_btn.setToolTip("Put text on the video at the playhead")
        self.add_text_btn.clicked.connect(self.add_text.emit)
        self.add_card_btn = QPushButton("+ Card")
        self.add_card_btn.setToolTip("Search every Magic card and put one on the video at the playhead")
        self.add_card_btn.clicked.connect(self.add_card.emit)
        add_row = QHBoxLayout()
        add_row.addWidget(self.add_card_btn)
        add_row.addWidget(self.add_text_btn)
        add_row.addStretch(1)
        add_row.addWidget(HelpButton(HELP["overlays"]))

        self.empty_note = QLabel("Add a card or text at the playhead, then drag it on the video to place it. "
                                 "Its bar under the timeline sets when it shows.")
        self.empty_note.setObjectName("dimLabel")
        self.empty_note.setWordWrap(True)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["What", "At", "For"])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.cellDoubleClicked.connect(lambda row, _c: self.jump_requested.emit(row))

        # The picked one's settings
        self.edit_box = QGroupBox("Selected")
        form = QFormLayout(self.edit_box)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFixedHeight(54)
        self.text_edit.setPlaceholderText("Type the words to show")
        self.text_edit.textChanged.connect(self._on_text)
        self.text_label = QLabel("Text")
        form.addRow(self.text_label, self.text_edit)
        self.card_name = QLabel()
        self.card_name.setWordWrap(True)
        self.change_card_btn = QPushButton("Change card...")
        self.change_card_btn.setToolTip("Pick another card or another printing of this one")
        self.change_card_btn.clicked.connect(lambda: self.change_card.emit(self.selected_index()))
        card_row = QHBoxLayout()
        card_row.addWidget(self.card_name, 1)
        card_row.addWidget(self.change_card_btn)
        self.card_label = QLabel("Card")
        form.addRow(self.card_label, card_row)
        self.length_spin = QDoubleSpinBox()
        self.length_spin.setRange(ov.MIN_SECONDS, 3600)
        self.length_spin.setSingleStep(0.5)
        self.length_spin.setDecimals(1)
        self.length_spin.setSuffix(" seconds")
        self.length_spin.valueChanged.connect(self._on_length)
        form.addRow("Shows for", self.length_spin)
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(int(ov.MIN_SIZE * 100), int(ov.MAX_SIZE * 100))
        self.size_slider.setToolTip("Or scroll the mouse wheel over it on the video, or drag its corner")
        self.size_slider.valueChanged.connect(self._on_size)
        form.addRow("Size", self.size_slider)
        self.in_combo = QComboBox()
        for key, name in ov.ANIMS.items():
            self.in_combo.addItem(name, key)
        self.in_combo.currentIndexChanged.connect(self._on_anim)
        form.addRow("Comes in", self.in_combo)
        self.out_combo = QComboBox()
        for key, name in ov.ANIMS_OUT.items():
            self.out_combo.addItem(name, key)
        self.out_combo.currentIndexChanged.connect(self._on_anim)
        form.addRow("Goes away", self.out_combo)
        self.jump_btn = QPushButton("Jump to it")
        self.jump_btn.clicked.connect(lambda: self.jump_requested.emit(self.selected_index()))
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setToolTip("Delete it (Delete key). Ctrl+Z brings it back.")
        self.delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.selected_index()))
        buttons = QHBoxLayout()
        buttons.addWidget(self.jump_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.delete_btn)
        form.addRow(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.addLayout(add_row)
        layout.addWidget(self.empty_note)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.edit_box)
        self._show_selected()

    # --- the list ---
    def set_overlays(self, overlays: list[Overlay], selected: int = -1) -> None:
        self.overlays = overlays
        self._filling = True
        self.table.setRowCount(len(overlays))
        for row in range(len(overlays)):
            self._fill_row(row)
        self.table.clearSelection()
        if 0 <= selected < len(overlays):
            self.table.selectRow(selected)
        self._filling = False
        self.empty_note.setVisible(not overlays)
        self._show_selected()

    def _fill_row(self, row: int) -> None:
        o = self.overlays[row]
        cells = [f"{KIND_NAMES.get(o.kind, o.kind)}: {ov.describe(o)}", format_time(o.start), f"{o.length:.1f} s"]
        for col, text in enumerate(cells):
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)
            item.setText(text)

    def refresh_row(self, row: int) -> None:
        """Shows changes made elsewhere (dragged on the video or the timeline)."""
        if 0 <= row < len(self.overlays):
            self._fill_row(row)
            if row == self.selected_index():
                self._show_selected(keep_text=True)

    def selected_index(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def select(self, row: int) -> None:
        if row != self.selected_index():
            self.table.selectRow(row) if row >= 0 else self.table.clearSelection()

    def _on_selection(self):
        if self._filling:
            return
        self._show_selected()
        self.selected.emit(self.selected_index())

    def focus_text(self):
        self.text_edit.setFocus()
        self.text_edit.selectAll()

    # --- the picked one ---
    def _show_selected(self, keep_text: bool = False):
        row = self.selected_index()
        o = self.overlays[row] if 0 <= row < len(self.overlays) else None
        self.edit_box.setEnabled(o is not None)
        self._filling = True
        is_text = o is None or o.kind == "text"
        self.text_label.setVisible(is_text)
        self.text_edit.setVisible(is_text)
        for w in (self.card_label, self.card_name, self.change_card_btn):
            w.setVisible(not is_text)
        if o is not None and not is_text:
            card = o.card or {}
            self.card_name.setText(f"{card.get('name', 'Card')}\n{card.get('set_name', '')} #{card.get('number', '')}")
        if o is None:
            self.text_edit.setPlainText("")
        else:
            if is_text and not keep_text and self.text_edit.toPlainText() != o.text:
                self.text_edit.setPlainText(o.text)
            self.length_spin.setValue(o.length)
            self.size_slider.setValue(round(o.size * 100))
            self.in_combo.setCurrentIndex(max(self.in_combo.findData(o.anim_in), 0))
            self.out_combo.setCurrentIndex(max(self.out_combo.findData(o.anim_out), 0))
        self._filling = False

    def _current(self) -> tuple[int, Overlay | None]:
        row = self.selected_index()
        if self._filling or not 0 <= row < len(self.overlays):
            return row, None
        return row, self.overlays[row]

    def _on_text(self):
        row, o = self._current()
        if o:
            o.text = self.text_edit.toPlainText()
            self._fill_row(row)
            self.edited.emit(row)

    def _on_length(self, value: float):
        row, o = self._current()
        if o:
            o.end = round(o.start + value, 3)
            self._fill_row(row)
            self.edited.emit(row)

    def _on_size(self, value: int):
        row, o = self._current()
        if o:
            o.size = value / 100
            self.edited.emit(row)

    def _on_anim(self):
        row, o = self._current()
        if o:
            o.anim_in = self.in_combo.currentData()
            o.anim_out = self.out_combo.currentData()
            self.edited.emit(row)
