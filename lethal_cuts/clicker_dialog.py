"""The Clicker window: teach Lethal Cuts the clicker's sound once, then find every click in a game."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSlider, QVBoxLayout,
)

from . import clicker
from .project import format_time


class ClickerDialog(QDialog):
    found = Signal(list)   # click times, once a scan finishes
    removed = Signal()     # "remove the click markers from this video"

    def __init__(self, video: Path, duration: float, playhead: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clicker")
        self.setMinimumWidth(500)
        self.video, self.duration, self.playhead = video, duration, playhead
        self._thread: QThread | None = None
        self._scan: clicker.ClickScan | None = None
        steps = QLabel(
            "Press a clicker during an in-person game when something great happens, and Lethal Cuts puts a "
            "marker there, like the F8 moment key.\n\n"
            "Teach it your clicker once: put the playhead right on one click in a recording (play at 1x and listen), "
            "then click Learn. After that, every video you open is checked for clicks by itself.")
        steps.setWordWrap(True)
        self.learn_btn = QPushButton(f"Learn the click at {format_time(playhead)}")
        self.learn_btn.clicked.connect(self.learn)
        self.find_btn = QPushButton("Find clicks in this video")
        self.find_btn.setObjectName("exportButton")
        self.find_btn.clicked.connect(self.find)
        self.remove_btn = QPushButton("Remove click markers")
        self.remove_btn.setToolTip("Takes this video's click markers off the timeline")
        self.remove_btn.clicked.connect(self._remove)
        self.match = QSlider(Qt.Horizontal)
        self.match.setRange(50, 90)
        self.match.setToolTip("Lower finds more clicks (and maybe a few other sounds); higher is stricter")
        template = clicker.load_template()
        self.match.setValue(int(round((template or {}).get("match", clicker.DEFAULT_MATCH) * 100)))
        self.match.valueChanged.connect(lambda v: clicker.set_match(v / 100))
        match_row = QHBoxLayout()
        match_row.addWidget(QLabel("Finds more"))
        match_row.addWidget(self.match, 1)
        match_row.addWidget(QLabel("Stricter"))
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        self.status = QLabel("")
        self.status.setObjectName("dimLabel")
        self.status.setWordWrap(True)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.learn_btn)
        buttons.addWidget(self.find_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.remove_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(steps)
        layout.addLayout(buttons)
        layout.addLayout(match_row)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addWidget(close, 0, Qt.AlignRight)
        self._refresh()

    def _refresh(self):
        learned = clicker.load_template() is not None
        self.find_btn.setEnabled(learned and self._thread is None)
        self.match.setEnabled(learned)
        if not learned and not self.status.text():
            self.status.setText("Not learned yet.")

    def learn(self):
        try:
            spectrum = clicker.learn(self.video, self.playhead)
        except clicker.ClickerError as e:
            self.status.setText(str(e))
            return
        clicker.save_template(spectrum, self.match.value() / 100)
        self.status.setText("Learned your clicker. Now click Find clicks in this video.")
        self._refresh()

    def find(self):
        template = clicker.load_template()
        if not template or self._thread:
            return
        self._scan = clicker.ClickScan(self.video, self.duration, template["spectrum"], template["match"])
        self._thread = QThread(self)
        self._scan.moveToThread(self._thread)
        self._thread.started.connect(self._scan.run)
        self._scan.progress.connect(self._on_progress)
        self._scan.finished.connect(self._on_finished)
        self._scan.finished.connect(self._thread.quit)
        self.bar.show()
        self.bar.setValue(0)
        self.status.setText("Listening to the whole game for clicks...")
        self._thread.start()
        self._refresh()

    def _on_progress(self, fraction: float):
        self.bar.setValue(int(fraction * 1000))

    def _on_finished(self, times: list, error: str):
        self._thread.wait(2000)
        self._thread = None
        self.bar.hide()
        if error:
            self.status.setText(error)
        else:
            n = len(times)
            self.status.setText(f"Found {n} click{'s' if n != 1 else ''}. They're cyan flags on the timeline." if n else
                                "No clicks found. Try moving the slider towards Finds more, or learn the click again.")
            self.found.emit(times)
        self._refresh()

    def _remove(self):
        self.removed.emit()
        self.status.setText("Click markers removed from this video.")

    def done(self, result):
        if self._scan:
            self._scan.cancel()
        if self._thread:
            self._thread.quit()
            self._thread.wait(5000)
        super().done(result)
