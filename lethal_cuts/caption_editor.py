"""The "Fix words" window: correct what Lethal Cuts heard in a clip, or fix a word everywhere in the game
(handy for card names it keeps getting wrong)."""
from __future__ import annotations

import re

from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from . import captions
from .project import Clip, format_time


def replace_chunk(words: list, chunk: tuple, new_text: str) -> list:
    """The words with one caption's words swapped for new ones, spread evenly over the same time."""
    t0, _, group = chunk
    start, end = group[0][1], group[-1][2]
    first = next(i for i, w in enumerate(words) if abs(float(w[1]) - start) < 1e-6)
    last = next(i for i, w in enumerate(words) if abs(float(w[2]) - end) < 1e-6 and i >= first)
    tokens = new_text.split()
    step = (end - start) / max(len(tokens), 1)
    fresh = [[t, round(start + k * step, 2), round(start + (k + 1) * step, 2)] for k, t in enumerate(tokens)]
    return words[:first] + fresh + words[last + 1:]


def replace_everywhere(words: list, old: str, new: str) -> tuple[list, int]:
    """Swaps a word (or a few words in a row) for another all through the game, ignoring capitals and punctuation."""
    old_tokens = [re.sub(r"[^\w']", "", t.lower()) for t in old.split()]
    if not old_tokens or not new.strip():
        return words, 0
    out, i, count = [], 0, 0
    while i < len(words):
        window = [re.sub(r"[^\w']", "", w[0].lower()) for w in words[i:i + len(old_tokens)]]
        if window == old_tokens:
            group = words[i:i + len(old_tokens)]
            tail = re.sub(r"^.*?([.,!?]*)$", r"\1", group[-1][0])  # keep the punctuation that followed
            tokens = new.split()
            start, end = float(group[0][1]), float(group[-1][2])
            step = (end - start) / len(tokens)
            for k, t in enumerate(tokens):
                out.append([t + (tail if k == len(tokens) - 1 else ""), round(start + k * step, 2),
                            round(start + (k + 1) * step, 2)])
            i += len(old_tokens)
            count += 1
        else:
            out.append(words[i])
            i += 1
    return out, count


class CaptionEditor(QDialog):
    def __init__(self, words: list, clip: Clip, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fix words")
        self.resize(620, 520)
        self.words = [list(w) for w in words]
        self.clip = clip
        note = QLabel("Click a caption to fix it. Card names wrong all game? Fix them everywhere at once below.")
        note.setWordWrap(True)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["At", "Caption"])
        self.table.verticalHeader().hide()
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_edit)
        self.old = QLineEdit()
        self.old.setPlaceholderText("Heard as, e.g. Soul Ring")
        self.new = QLineEdit()
        self.new.setPlaceholderText("Should be, e.g. Sol Ring")
        replace = QPushButton("Fix everywhere")
        replace.clicked.connect(self._replace)
        row = QHBoxLayout()
        row.addWidget(self.old)
        row.addWidget(QLabel("→"))
        row.addWidget(self.new)
        row.addWidget(replace)
        self.status = QLabel("")
        self.status.setObjectName("dimLabel")
        save = QPushButton("Save")
        save.setObjectName("exportButton")
        save.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.status, 1)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(note)
        layout.addWidget(self.table, 1)
        layout.addLayout(row)
        layout.addLayout(buttons)
        self._fill()

    def _fill(self):
        self._chunks = captions.chunks(self.words, self.clip.start, self.clip.end)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._chunks))
        for row, (t0, _, group) in enumerate(self._chunks):
            at = QTableWidgetItem(format_time(t0 - self.clip.start))
            at.setFlags(at.flags() & ~at.flags().ItemIsEditable)
            self.table.setItem(row, 0, at)
            self.table.setItem(row, 1, QTableWidgetItem(" ".join(w for w, _, _ in group)))
        self.table.blockSignals(False)

    def _on_edit(self, item):
        if item.column() != 1:
            return
        text = item.text().strip()
        chunk = self._chunks[item.row()]
        if text and text != " ".join(w for w, _, _ in chunk[2]):
            self.words = replace_chunk(self.words, chunk, text)
            self._fill()
            self.status.setText("Fixed.")

    def _replace(self):
        self.words, n = replace_everywhere(self.words, self.old.text(), self.new.text())
        self._fill()
        self.status.setText(f"Fixed {n} time{'s' if n != 1 else ''} in the whole game." if n else
                            f'"{self.old.text()}" wasn\'t heard anywhere.')
