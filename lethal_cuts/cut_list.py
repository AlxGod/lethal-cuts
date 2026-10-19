"""The side list of cuts for a long video: the dead stretches that get left out."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from .long_export import TRANSITIONS
from .project import Clip, format_time


class CutList(QTableWidget):
    cut_selected = Signal(int)   # row, or -1 for none
    cut_activated = Signal(int)  # double-clicked: jump there

    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels(["#", "Cut from", "To", "Cuts", "Join"])
        self.default_join = "cut"  # Settings' choice, for cuts that don't pick their own
        self.verticalHeader().hide()
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._filling = False
        self.itemSelectionChanged.connect(self._on_selection)
        self.cellDoubleClicked.connect(lambda row, _col: self.cut_activated.emit(row))

    def set_cuts(self, cuts: list[Clip], selected: int = -1) -> None:
        self._filling = True
        self.setRowCount(len(cuts))
        for row, cut in enumerate(cuts):
            join = TRANSITIONS.get(cut.transition or self.default_join, TRANSITIONS["cut"])[0]
            for col, text in enumerate([str(row + 1), format_time(cut.start), format_time(cut.end),
                                        format_time(cut.length), join]):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.setItem(row, col, item)
        self.clearSelection()
        if 0 <= selected < len(cuts):
            self.selectRow(selected)
        self._filling = False

    def selected_index(self) -> int:
        rows = self.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _on_selection(self):
        if not self._filling:
            self.cut_selected.emit(self.selected_index())
