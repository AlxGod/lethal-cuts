"""The side list of finished clips: number, editable name, start time and length."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from .project import Clip, format_time

COL_NUMBER, COL_NAME, COL_START, COL_LENGTH = range(4)


class ClipList(QTableWidget):
    clip_selected = Signal(int)          # user picked a clip
    clip_activated = Signal(int)         # user double-clicked: jump to it
    name_changed = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(["#", "Name", "Start", "Length"])
        self.verticalHeader().hide()
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditKeyPressed | QAbstractItemView.SelectedClicked)
        header = self.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for col in (COL_NUMBER, COL_START, COL_LENGTH):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self._filling = False
        self.itemSelectionChanged.connect(self._on_selection)
        self.itemChanged.connect(self._on_item_changed)
        self.cellDoubleClicked.connect(self._on_double_click)

    def set_clips(self, clips: list[Clip], selected: int = -1) -> None:
        self._filling = True
        self.setRowCount(len(clips))
        for row, clip in enumerate(clips):
            self._set(row, COL_NUMBER, str(row + 1), editable=False, align=Qt.AlignCenter)
            self._set(row, COL_NAME, clip.name, editable=True)
            self._set(row, COL_START, format_time(clip.start), editable=False)
            self._set(row, COL_LENGTH, f"{clip.length:.1f}s", editable=False)
        if 0 <= selected < len(clips):
            self.selectRow(selected)
        else:
            self.clearSelection()
        self._filling = False

    def selected_index(self) -> int:
        rows = self.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _set(self, row, col, text, editable, align=None):
        item = QTableWidgetItem(text)
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if editable:
            flags |= Qt.ItemIsEditable
            item.setToolTip("Click again or press F2 to rename this clip")
        item.setFlags(flags)
        if align is not None:
            item.setTextAlignment(align)
        self.setItem(row, col, item)

    def _on_selection(self):
        if not self._filling:
            self.clip_selected.emit(self.selected_index())

    def _on_item_changed(self, item):
        if not self._filling and item.column() == COL_NAME:
            self.name_changed.emit(item.row(), item.text().strip())

    def _on_double_click(self, row, col):
        if col != COL_NAME:
            self.clip_activated.emit(row)
