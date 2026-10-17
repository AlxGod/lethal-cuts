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
from .settings import ACTIONS, LONG_SIZES, MOMENT_KEYS, MOMENT_MINUTES, QUALITIES, Settings


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

        # Recording
        rec = QGroupBox("Recording")
        form = QFormLayout(rec)
        self.moment_key = QComboBox()
        self.moment_key.addItems(MOMENT_KEYS)
        self.moment_key.setCurrentText(s.moment_key)
        form.addRow("Mark-a-moment key:", self.moment_key)
        self.moment_minutes = QComboBox()
        for m in MOMENT_MINUTES:
            self.moment_minutes.addItem(f"{m} minute{'s' if m != 1 else ''}", float(m))
        self.moment_minutes.setCurrentIndex(MOMENT_MINUTES.index(int(s.moment_minutes)))
        form.addRow("Each moment covers the last:", self.moment_minutes)
        rec_note = QLabel("While recording, press the key when something great happens, even with the game in "
                          "front. In the Editor, N jumps to that many minutes before each press.")
        rec_note.setObjectName("dimLabel")
        rec_note.setWordWrap(True)
        form.addRow(rec_note)
        layout.addWidget(rec)

        # Posting
        posting = QGroupBox("Posting")
        posting_layout = QVBoxLayout(posting)
        self.verified = QCheckBox("My YouTube account is verified (it can take videos over 15 minutes)")
        self.verified.setChecked(s.youtube_verified)
        posting_layout.addWidget(self.verified)
        limits_note = QLabel("YouTube: Shorts up to 3 minutes; normal videos up to 15 minutes, or 12 hours once the "
                             "account has a verified phone number. TikTok: up to 60 minutes.")
        limits_note.setObjectName("dimLabel")
        limits_note.setWordWrap(True)
        posting_layout.addWidget(limits_note)
        layout.addWidget(posting)

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
        self.long_size = QComboBox()
        for key, label in LONG_SIZES.items():
            self.long_size.addItem(label, key)
        self.long_size.setCurrentIndex(list(LONG_SIZES).index(s.long_size))
        form.addRow("Long video size:", self.long_size)
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
        self.long_size.currentIndexChanged.connect(lambda _: self._apply())
        self.nudges.toggled.connect(lambda _: self._apply())
        self.moment_key.currentIndexChanged.connect(lambda _: self._apply())
        self.moment_minutes.currentIndexChanged.connect(lambda _: self._apply())
        self.verified.toggled.connect(lambda _: self._apply())

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

    def refresh_verified(self):
        self.verified.blockSignals(True)
        self.verified.setChecked(self.s.youtube_verified)
        self.verified.blockSignals(False)

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
        # Never moves their videos, and keeps what Lethal Cuts has learned or been told about their accounts
        fresh = Settings(walkthrough_done=walkthrough, save_folder=self.s.save_folder, obs_exe=self.s.obs_exe,
                         record_gb_per_hour=self.s.record_gb_per_hour, youtube_verified=self.s.youtube_verified)
        self.s.__dict__.update(fresh.__dict__)
        self.pad_before.setValue(fresh.pad_before)
        self.pad_after.setValue(fresh.pad_after)
        self.step.setValue(fresh.step_seconds)
        self.quality.setCurrentIndex(list(QUALITIES).index(fresh.quality))
        self.long_size.setCurrentIndex(list(LONG_SIZES).index(fresh.long_size))
        self.nudges.setChecked(True)
        self.moment_key.setCurrentText(fresh.moment_key)
        self.moment_minutes.setCurrentIndex(MOMENT_MINUTES.index(int(fresh.moment_minutes)))
        for action, edit in self.key_edits.items():
            edit.setKeySequence(QKeySequence(fresh.key(action)))
        self._paint_color_buttons()
        self._apply()

    def _apply(self):
        self.s.pad_before = self.pad_before.value()
        self.s.pad_after = self.pad_after.value()
        self.s.step_seconds = self.step.value()
        self.s.quality = self.quality.currentData()
        self.s.long_size = self.long_size.currentData()
        self.s.nudges = self.nudges.isChecked()
        self.s.moment_key = self.moment_key.currentText()
        self.s.moment_minutes = self.moment_minutes.currentData()
        self.s.youtube_verified = self.verified.isChecked()
        try:
            settings_mod.save(self.s)
        except OSError as e:
            QMessageBox.warning(self, "Lethal Cuts", f"Couldn't save settings:\n{e}")
        self.changed.emit(self.s)
