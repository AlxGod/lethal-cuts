"""The Editor's "On screen" tab: the cards and text shown on top of the video.

Adding one puts it at the playhead. It's then placed by dragging it on the video, and
timed by dragging its bar on the timeline. This panel lists them and edits the picked one.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit, QPushButton, QSlider, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from . import overlays as ov
from . import pause_title, text_look
from .help import HELP, HelpButton
from .project import Overlay, format_time

KIND_NAMES = {"text": "Text", "card": "Card", "pause": "Pause card"}
OUTLINES = [("None", 0.0), ("Thin", 0.08), ("Medium", 0.14), ("Thick", 0.2)]


class ColorButton(QPushButton):
    """A small square showing a color; clicking it opens the color picker."""
    picked = Signal(str)

    def __init__(self, tip: str, alpha: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 24)
        self.setToolTip(tip)
        self.alpha = alpha
        self.color = "#ffffff"
        self.clicked.connect(self._choose)

    def set_color(self, color: str):
        self.color = color or "#000000"
        c = QColor(self.color)
        self.setStyleSheet(f"QPushButton {{ background: rgba({c.red()},{c.green()},{c.blue()},{c.alpha()}); "
                           f"border: 2px solid #8a80a0; border-radius: 4px; }}")

    def _choose(self):
        options = QColorDialog.ShowAlphaChannel if self.alpha else QColorDialog.ColorDialogOption(0)
        c = QColorDialog.getColor(QColor(self.color), self, self.toolTip(), options)
        if c.isValid():
            self.set_color(c.name(QColor.HexArgb) if self.alpha and c.alpha() < 255 else c.name())
            self.picked.emit(self.color)


class OverlayPanel(QWidget):
    add_text = Signal()
    add_card = Signal()
    add_pause = Signal()
    edit_title = Signal()
    change_card = Signal(int)
    selected = Signal(int)    # row picked in the list, or -1
    edited = Signal(int)      # the picked overlay was changed here (in place)
    delete_requested = Signal(int)
    jump_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.overlays: list[Overlay] = []
        self._filling = False
        self.long_mode = False  # set by the main window: styles sit in different places on long videos

        self.add_text_btn = QPushButton("+ Text")
        self.add_text_btn.setToolTip("Put text on the video at the playhead")
        self.add_text_btn.clicked.connect(self.add_text.emit)
        self.add_card_btn = QPushButton("+ Card")
        self.add_card_btn.setToolTip("Search every Magic card and put one on the video at the playhead")
        self.add_card_btn.clicked.connect(self.add_card.emit)
        self.add_pause_btn = QPushButton("+ Pause")
        self.add_pause_btn.setToolTip("A \"What's your play?\" pause card: the Short freezes here and counts down")
        self.add_pause_btn.clicked.connect(self.add_pause.emit)
        self.title_btn = QPushButton("+ Title card")
        self.title_btn.setToolTip("A series title card at the start of the long video")
        self.title_btn.clicked.connect(self.edit_title.emit)
        add_row = QHBoxLayout()
        add_row.addWidget(self.add_card_btn)
        add_row.addWidget(self.add_text_btn)
        add_row.addStretch(1)
        add_row.addWidget(HelpButton(HELP["overlays"]))
        extra_row = QHBoxLayout()  # on its own row so the side panel stays narrow
        extra_row.addWidget(self.add_pause_btn)
        extra_row.addWidget(self.title_btn)
        extra_row.addStretch(1)

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
        self.text_tip = QLabel("Put *stars* around words to make them stand out in the highlight color.")
        self.text_tip.setObjectName("dimLabel")
        self.text_tip.setWordWrap(True)
        form.addRow(self.text_tip)
        # How the text looks: a ready-made style, and the details if he wants to change them
        self.style_combo = QComboBox()
        for key, s in text_look.STYLES.items():
            self.style_combo.addItem(s["name"], key)
            self.style_combo.setItemData(self.style_combo.count() - 1, s["tip"], Qt.ToolTipRole)
        self.style_combo.setToolTip("A ready-made look. It also moves the text to where that style usually goes.")
        self.style_combo.activated.connect(self._on_style)
        self.custom_btn = QPushButton("Edit look")
        self.custom_btn.setCheckable(True)
        self.custom_btn.setToolTip("Change the font, colors, outline, box and shadow")
        self.custom_btn.toggled.connect(lambda on: self.custom_box.setVisible(on and self._is_text()))
        style_row = QHBoxLayout()
        style_row.addWidget(self.style_combo, 1)
        style_row.addWidget(self.custom_btn)
        self.style_label = QLabel("Style")
        form.addRow(self.style_label, style_row)
        self.custom_box = QWidget()
        grid = QGridLayout(self.custom_box)
        grid.setContentsMargins(0, 0, 0, 0)
        self.font_combo = QComboBox()
        for label, family, weight in text_look.FONTS:
            self.font_combo.addItem(label, (family, weight))
        self.font_combo.insertSeparator(self.font_combo.count())
        known = {f for _, f, _ in text_look.FONTS}
        for family in QFontDatabase.families():
            if family not in known and not family.startswith("@"):
                self.font_combo.addItem(family, (family, 700))
        self.font_combo.setMaxVisibleItems(16)
        for combo in (self.font_combo, self.style_combo):
            # Long names mustn't make the side panel (and the window) wider
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(3 if combo is self.style_combo else 6)
        self.font_combo.activated.connect(self._on_look)
        grid.addWidget(QLabel("Font"), 0, 0)
        grid.addWidget(self.font_combo, 0, 1, 1, 4)
        self.color_btn = ColorButton("Text color")
        self.accent_btn = ColorButton("Highlight color (for *starred* words)")
        self.outline_btn = ColorButton("Outline color")
        self.box_btn = ColorButton("Box color (can be see-through)", alpha=True)
        for b in (self.color_btn, self.accent_btn, self.outline_btn, self.box_btn):
            b.picked.connect(self._on_look)
        grid.addWidget(QLabel("Colors"), 1, 0)
        grid.addWidget(self.color_btn, 1, 1)
        grid.addWidget(QLabel("Highlight"), 1, 2)
        grid.addWidget(self.accent_btn, 1, 3)
        self.outline_combo = QComboBox()
        for label, value in OUTLINES:
            self.outline_combo.addItem(label, value)
        self.outline_combo.activated.connect(self._on_look)
        grid.addWidget(QLabel("Outline"), 2, 0)
        grid.addWidget(self.outline_combo, 2, 1, 1, 2)
        grid.addWidget(self.outline_btn, 2, 3)
        self.box_check = QCheckBox("Box")
        self.box_check.setToolTip("A colored box behind the text")
        self.box_check.toggled.connect(self._on_look)
        self.shadow_check = QCheckBox("Shadow")
        self.shadow_check.toggled.connect(self._on_look)
        self.caps_check = QCheckBox("CAPS")
        self.caps_check.setToolTip("Show it all in capital letters")
        self.caps_check.toggled.connect(self._on_look)
        grid.addWidget(self.box_check, 3, 0)
        grid.addWidget(self.box_btn, 3, 1)
        grid.addWidget(self.shadow_check, 3, 2, 1, 2)
        grid.addWidget(self.caps_check, 4, 0, 1, 2)
        grid.setColumnStretch(4, 1)
        self.custom_box.hide()
        form.addRow(self.custom_box)
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
        self.length_label = QLabel("Shows for")
        form.addRow(self.length_label, self.length_spin)
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(int(ov.MIN_SIZE * 100), int(ov.MAX_SIZE * 100))
        self.size_slider.setToolTip("Or scroll the mouse wheel over it on the video, or drag its corner")
        self.size_slider.valueChanged.connect(self._on_size)
        form.addRow("Size", self.size_slider)
        self.in_combo = QComboBox()
        for key, name in ov.ANIMS.items():
            self.in_combo.addItem(name, key)
        self.in_combo.currentIndexChanged.connect(self._on_anim)
        self.in_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.in_combo.setMinimumContentsLength(6)
        self.in_label = QLabel("Comes in")
        form.addRow(self.in_label, self.in_combo)
        self.out_combo = QComboBox()
        for key, name in ov.ANIMS_OUT.items():
            self.out_combo.addItem(name, key)
        self.out_combo.currentIndexChanged.connect(self._on_anim)
        self.out_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.out_combo.setMinimumContentsLength(6)
        self.out_label = QLabel("Goes away")
        form.addRow(self.out_label, self.out_combo)
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
        layout.addLayout(extra_row)
        self.title_note = QLabel()
        self.title_note.setObjectName("dimLabel")
        self.title_note.setWordWrap(True)
        self.title_note.hide()
        layout.addWidget(self.title_note)
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

    def set_mode(self, long: bool, title: dict | None) -> None:
        """Pause cards are for Shorts; the title card is for the long video."""
        self.long_mode = long
        self.add_pause_btn.setVisible(not long)
        self.title_btn.setVisible(long)
        self.title_btn.setText("Title card..." if title else "+ Title card")
        if long and title:
            self.title_note.setText(f"Title card: {title.get('series', '')}, episode {title.get('episode', 1)} "
                                    f"({pause_title.title_seconds(title):g} s at the start)")
        self.title_note.setVisible(bool(long and title))

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
        is_text = o is None or o.kind in ("text", "pause")
        is_pause = o is not None and o.kind == "pause"
        for w in (self.in_combo, self.out_combo, self.in_label, self.out_label):
            w.setVisible(not is_pause)  # a pause card just appears and goes
        self.length_spin.setDecimals(0 if is_pause else 1)
        self.length_spin.setSingleStep(1 if is_pause else 0.5)
        self.length_spin.setRange(pause_title.PAUSE_MIN if is_pause else ov.MIN_SECONDS,
                                  pause_title.PAUSE_MAX if is_pause else 3600)
        self.length_label.setText("Countdown" if is_pause else "Shows for")
        for w in (self.text_label, self.text_edit, self.text_tip, self.style_label, self.style_combo, self.custom_btn):
            w.setVisible(is_text)
        self.custom_box.setVisible(is_text and self.custom_btn.isChecked())
        for w in (self.card_label, self.card_name, self.change_card_btn):
            w.setVisible(not is_text)
        typewriter = self.in_combo.findData("type")
        self.in_combo.model().item(typewriter).setEnabled(is_text)  # only text can type itself out
        if o is not None and is_text:
            self.style_combo.setCurrentIndex(max(self.style_combo.findData(o.style), 0))
            index = self.font_combo.findData((o.font, o.weight))
            if index < 0:
                index = next((i for i in range(self.font_combo.count())
                              if (self.font_combo.itemData(i) or ("",))[0] == o.font), 0)
            self.font_combo.setCurrentIndex(index)
            self.color_btn.set_color(o.color)
            self.accent_btn.set_color(o.accent)
            self.outline_btn.set_color(o.outline_color)
            self.box_btn.set_color(o.box or "#f0b840")
            self.outline_combo.setCurrentIndex(min(range(len(OUTLINES)), key=lambda i: abs(OUTLINES[i][1] - o.outline)))
            self.box_check.setChecked(bool(o.box))
            self.shadow_check.setChecked(o.shadow)
            self.caps_check.setChecked(o.caps)
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

    def _is_text(self) -> bool:
        row = self.selected_index()
        return not (0 <= row < len(self.overlays)) or self.overlays[row].kind in ("text", "pause")

    def _on_style(self):
        row, o = self._current()
        if o and o.kind in ("text", "pause"):
            text_look.apply_style(o, self.style_combo.currentData(), self.long_mode, place=o.kind == "text")
            self._show_selected(keep_text=True)
            self.edited.emit(row)

    def _on_look(self, *_):
        row, o = self._current()
        if not o or o.kind not in ("text", "pause"):
            return
        family, weight = self.font_combo.currentData() or (o.font, o.weight)
        o.font, o.weight = family, weight
        o.color, o.accent, o.outline_color = self.color_btn.color, self.accent_btn.color, self.outline_btn.color
        o.outline = self.outline_combo.currentData()
        o.box = self.box_btn.color if self.box_check.isChecked() else ""
        o.shadow = self.shadow_check.isChecked()
        o.caps = self.caps_check.isChecked()
        self.edited.emit(row)

    def _on_anim(self):
        row, o = self._current()
        if o:
            o.anim_in = self.in_combo.currentData()
            o.anim_out = self.out_combo.currentData()
            self.edited.emit(row)
