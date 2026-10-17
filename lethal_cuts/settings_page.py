"""The Settings tab. Every change is saved right away."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from . import settings as settings_mod
from .folders import is_inside_program, save_folder
from .settings import ACTIONS, QUALITIES, Settings


class SettingsPage(QScrollArea):
    changed = Signal(object)  # Settings

    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.s = s
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        self.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 16, 24, 16)
        title = QLabel("Settings")
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        note = QLabel(f"Saved automatically in {settings_mod.settings_path()}")
        note.setObjectName("dimLabel")
        layout.addWidget(note)

        # Where videos are saved
        saving = QGroupBox("Your videos")
        saving_layout = QVBoxLayout(saving)
        folder_row = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setReadOnly(True)
        open_btn = QPushButton("Open")
        open_btn.setToolTip("Open this folder in File Explorer")
        open_btn.clicked.connect(self.open_folder)
        browse = QPushButton("Change...")
        browse.clicked.connect(self.choose_folder)
        folder_row.addWidget(QLabel("Saved in:"))
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(open_btn)
        folder_row.addWidget(browse)
        saving_layout.addLayout(folder_row)
        folder_note = QLabel("Recordings, Shorts (a folder for each game) and long videos all go in here. "
                             "Uninstalling or updating Lethal Cuts never deletes anything in this folder.")
        folder_note.setObjectName("dimLabel")
        folder_note.setWordWrap(True)
        saving_layout.addWidget(folder_note)
        layout.addWidget(saving)
        self.refresh_folder()

        # Clips
        clips = QGroupBox("Clips")
        form = QFormLayout(clips)
        self.pad_before = self._seconds(s.pad_before, 0, 10)
        self.pad_after = self._seconds(s.pad_after, 0, 10)
        self.step = self._seconds(s.step_seconds, 1, 60)
        form.addRow("Extra time before each clip:", self.pad_before)
        form.addRow("Extra time after each clip:", self.pad_after)
        form.addRow("Arrow keys jump by:", self.step)
        pad_note = QLabel("Extra time gives you a moment of lead-in, since it's easy to press I a little late.")
        pad_note.setObjectName("dimLabel")
        pad_note.setWordWrap(True)
        form.addRow(pad_note)
        layout.addWidget(clips)

        # Export
        exp = QGroupBox("Export")
        form = QFormLayout(exp)
        self.quality = QComboBox()
        for key, (label, _, _) in QUALITIES.items():
            self.quality.addItem(label, key)
        self.quality.setCurrentIndex(list(QUALITIES).index(s.quality))
        form.addRow("Video quality:", self.quality)
        layout.addWidget(exp)

        # Tips
        tips = QGroupBox("Tips")
        tips_layout = QVBoxLayout(tips)
        self.nudges = QCheckBox("Show friendly tips while I work (long clips, missing crop box, unnamed clips)")
        self.nudges.setChecked(s.nudges)
        tips_layout.addWidget(self.nudges)
        layout.addWidget(tips)

        # Colors
        colors = QGroupBox("Colors")
        form = QFormLayout(colors)
        self.color_buttons = {}
        for attr, label in [("clip_color_a", "Clip bars (odd numbers):"), ("clip_color_b", "Clip bars (even numbers):"),
                            ("crop_color", "Crop box:")]:
            btn = QPushButton()
            btn.setFixedWidth(90)
            btn.clicked.connect(lambda _=False, a=attr: self._pick_color(a))
            self.color_buttons[attr] = btn
            form.addRow(label, btn)
        self._paint_color_buttons()
        layout.addWidget(colors)

        # Hotkeys
        keys = QGroupBox("Hotkeys")
        form = QFormLayout(keys)
        key_note = QLabel("Click a box and press the new key. Clear a box to go back to the default key.")
        key_note.setObjectName("dimLabel")
        form.addRow(key_note)
        self.key_edits = {}
        for action, (label, _) in ACTIONS.items():
            edit = QKeySequenceEdit(QKeySequence(s.key(action)))
            edit.setMaximumSequenceLength(1)
            edit.setClearButtonEnabled(True)
            edit.editingFinished.connect(lambda a=action: self._key_changed(a))
            self.key_edits[action] = edit
            form.addRow(label + ":", edit)
        layout.addWidget(keys)

        reset = QPushButton("Put everything back to the defaults")
        reset.clicked.connect(self._reset)
        layout.addWidget(reset, 0, Qt.AlignLeft)
        layout.addStretch(1)

        for w in (self.pad_before, self.pad_after, self.step):
            w.valueChanged.connect(lambda _: self._apply())
        self.quality.currentIndexChanged.connect(lambda _: self._apply())
        self.nudges.toggled.connect(lambda _: self._apply())

    @staticmethod
    def _seconds(value, low, high):
        box = QDoubleSpinBox()
        box.setRange(low, high)
        box.setSingleStep(0.5)
        box.setDecimals(1)
        box.setSuffix(" seconds")
        box.setValue(value)
        box.setMaximumWidth(140)
        return box

    def _paint_color_buttons(self):
        for attr, btn in self.color_buttons.items():
            color = getattr(self.s, attr)
            btn.setStyleSheet(f"background: {color}; border: 1px solid #ffffff40;")
            btn.setText(color)

    def _pick_color(self, attr):
        color = QColorDialog.getColor(QColor(getattr(self.s, attr)), self, "Pick a color")
        if color.isValid():
            setattr(self.s, attr, color.name())
            self._paint_color_buttons()
            self._apply()

    def refresh_folder(self):
        self.folder.setText(str(save_folder(self.s)))

    def open_folder(self):
        folder = save_folder(self.s)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Save your videos in", str(save_folder(self.s)))
        if not path:
            return
        if is_inside_program(Path(path)):
            QMessageBox.warning(self, "Pick another folder",
                                "That folder holds the program's own files, which get replaced on every update. "
                                "Pick a different folder for your videos.")
            return
        self.s.save_folder = path
        self.refresh_folder()
        self._apply()

    def _key_changed(self, action):
        edit = self.key_edits[action]
        text = edit.keySequence().toString()
        if not text:
            text = ACTIONS[action][1]
            edit.setKeySequence(QKeySequence(text))
        same = lambda k: QKeySequence(k).toString().lower() == text.lower()  # "Escape" and "Esc" are one key
        clash = next((a for a, k in self.s.hotkeys.items() if a != action and same(k)), None)
        if clash:
            QMessageBox.information(self, "Key already used",
                                    f'"{text}" is already used for "{ACTIONS[clash][0]}". Pick a different key.')
            edit.setKeySequence(QKeySequence(self.s.key(action)))
            return
        self.s.hotkeys[action] = text
        self._apply()

    def _reset(self):
        walkthrough = self.s.walkthrough_done
        fresh = Settings(walkthrough_done=walkthrough, save_folder=self.s.save_folder)  # never moves their videos
        self.s.__dict__.update(fresh.__dict__)
        self.pad_before.setValue(fresh.pad_before)
        self.pad_after.setValue(fresh.pad_after)
        self.step.setValue(fresh.step_seconds)
        self.quality.setCurrentIndex(list(QUALITIES).index(fresh.quality))
        self.nudges.setChecked(True)
        for action, edit in self.key_edits.items():
            edit.setKeySequence(QKeySequence(fresh.key(action)))
        self._paint_color_buttons()
        self._apply()

    def _apply(self):
        self.s.pad_before = self.pad_before.value()
        self.s.pad_after = self.pad_after.value()
        self.s.step_seconds = self.step.value()
        self.s.quality = self.quality.currentData()
        self.s.nudges = self.nudges.isChecked()
        try:
            settings_mod.save(self.s)
        except OSError as e:
            QMessageBox.warning(self, "Lethal Cuts", f"Couldn't save settings:\n{e}")
        self.changed.emit(self.s)
