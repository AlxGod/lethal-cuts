"""The Record tab: records a Tabletop Simulator game with OBS, then opens it in the Editor."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from . import obs
from . import settings as settings_mod
from .folders import free_space, recordings_folder
from .help import HELP, HelpButton
from .hotkey import GlobalHotkey
from .project import format_time, open_project

NO_FILE_WARNING = 20  # seconds: if OBS hasn't started a file by then, say so
GUESS_GB_PER_HOUR = 8.0  # until a real recording shows how big they are (1080p at 30 frames a second)
GAME_HOURS = 3           # warn before starting if there isn't room for a game this long
NEARLY_FULL_GB = 3       # warn while recording once the drive gets down to this
GB = 1024 ** 3


def hours_text(hours: float) -> str:
    """'2 hours 30 minutes', rounded to keep it readable."""
    minutes = int(hours * 60)
    if minutes < 60:
        return f"{minutes} minutes"
    h, m = divmod(minutes, 60)
    if h >= 10:
        return f"{h} hours"
    m = m // 10 * 10
    return f"{h} hour{'s' if h != 1 else ''}" + (f" {m} minutes" if m else "")


class RecordPage(QWidget):
    finished = Signal(object)     # the new recording's Path, or None
    status = Signal(str)          # a line for the window's status bar
    _closed = Signal(bool)        # from the closing thread: did OBS close

    def __init__(self, s, parent=None):
        super().__init__(parent)
        self.s = s
        self.proc = None
        self.started_at = 0.0
        self.stopping = False
        self._warned = False
        self._space_warned = False
        self.moments: list[float] = []  # when the moment key was pressed (time.time())
        self.hotkey: GlobalHotkey | None = None
        self._closed.connect(self._on_closed)

        title = QLabel("Record")
        title.setObjectName("panelTitle")
        top = QHBoxLayout()
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(HelpButton(HELP["record"]))
        intro = QLabel("Records your Tabletop Simulator games with OBS, the free recorder. Lethal Cuts starts it for you, "
                       "records the game window, your computer's sound (the game and everyone on Discord) and your "
                       "microphone, and opens the recording in the Editor when you stop.")
        intro.setWordWrap(True)

        self.big_btn = QPushButton("Start recording")
        self.big_btn.setObjectName("exportButton")
        self.big_btn.setMinimumHeight(56)
        self.big_btn.clicked.connect(self.toggle)
        self.state = QLabel("Not recording.")
        self.state.setObjectName("panelTitle")
        self.state.setAlignment(Qt.AlignCenter)
        self.note = QLabel()
        self.note.setObjectName("dimLabel")
        self.note.setWordWrap(True)
        self.note.setAlignment(Qt.AlignCenter)
        self.moment_btn = QPushButton()
        self.moment_btn.setObjectName("markIn")
        self.moment_btn.setToolTip("Marks the last few minutes, so you can find this moment in seconds later")
        self.moment_btn.clicked.connect(self.mark_moment)
        self.moment_btn.hide()
        self.moment_label = QLabel()
        self.moment_label.setObjectName("dimLabel")
        self.moment_label.setAlignment(Qt.AlignCenter)
        self.moment_label.setWordWrap(True)
        self.open_after = QCheckBox("Open the recording in the Editor when I stop")
        self.open_after.setChecked(s.open_after_record)
        self.open_after.toggled.connect(self._save_choice)

        self.obs_label = QLabel()
        self.obs_label.setWordWrap(True)
        self.obs_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        find = QPushButton("Find OBS...")
        find.setToolTip("Point Lethal Cuts at OBS's program file (obs64.exe) if it's installed somewhere unusual")
        find.clicked.connect(self.choose_obs)
        get = QPushButton("Get OBS")
        get.setToolTip("Opens OBS's download page in your browser (it's free)")
        get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(obs.GET_OBS)))
        obs_row = QHBoxLayout()
        obs_row.addWidget(self.obs_label, 1)
        obs_row.addWidget(find)
        obs_row.addWidget(get)
        self.folder_label = QLabel()
        self.folder_label.setObjectName("dimLabel")
        self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        open_folder = QPushButton("Open folder")
        open_folder.clicked.connect(self.open_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_label, 1)
        folder_row.addWidget(open_folder)
        self.space_label = QLabel()
        self.space_label.setObjectName("dimLabel")
        self.space_label.setWordWrap(True)

        tips = QLabel(
            "<b>Tips</b><ul>"
            "<li>Start Tabletop Simulator first, then click Start recording. Windowed or fullscreen both work.</li>"
            "<li>Something great just happened? Press the moment key (F8 unless you changed it in Settings), even "
            "with the game in front. Nothing pops up, so keep playing. In the Editor, N jumps to a few minutes "
            "before each press, so you don't have to watch the whole game to find the best bits.</li>"
            "<li>Everything you hear gets recorded, so turn off music and keep other noisy apps quiet.</li>"
            "<li>OBS sits by the clock while it records. Don't close it from there: click Stop recording here, so the "
            "file is finished properly.</li>"
            "<li>Want a different microphone? Open OBS from the Start menu, pick the <i>Lethal Cuts</i> profile and "
            "scene collection, and change it there. Lethal Cuts keeps your change.</li></ul>")
        tips.setObjectName("dimLabel")
        tips.setWordWrap(True)

        card = QFrame()
        card.setObjectName("walkCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 18, 24, 18)
        card_layout.addWidget(self.state)
        card_layout.addWidget(self.big_btn)
        card_layout.addWidget(self.note)
        card_layout.addWidget(self.moment_btn)
        card_layout.addWidget(self.moment_label)
        card_layout.addWidget(self.open_after, 0, Qt.AlignHCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.addLayout(top)
        layout.addWidget(intro)
        layout.addSpacing(10)
        layout.addWidget(card)
        layout.addSpacing(10)
        layout.addLayout(obs_row)
        layout.addLayout(folder_row)
        layout.addWidget(self.space_label)
        layout.addSpacing(6)
        layout.addWidget(tips)
        layout.addStretch(1)

        self.clock = QTimer(self, interval=500, timeout=self._tick)
        self.refresh()

    # --- showing where things are ---
    def refresh(self, s=None):
        if s is not None:
            self.s = s
        exe = obs.find_exe(self.s.obs_exe)
        self.obs_label.setText(f"OBS: {exe}" if exe else
                               "OBS isn't installed (or Lethal Cuts can't find it). Click Get OBS to download it "
                               "for free, install it, then come back here.")
        self.folder_label.setText(f"Recordings are saved in: {recordings_folder(self.s)}")
        self.moment_btn.setText(f"Mark a moment  ({self.s.moment_key})")
        self.refresh_space()
        if not self.recording:
            self.big_btn.setEnabled(exe is not None)

    # --- disk space ---
    def gb_per_hour(self) -> float:
        return self.s.record_gb_per_hour or GUESS_GB_PER_HOUR

    def hours_left(self) -> float | None:
        free = free_space(recordings_folder(self.s))
        return None if free is None else free / GB / self.gb_per_hour()

    def refresh_space(self) -> None:
        free = free_space(recordings_folder(self.s))
        if free is None:
            self.space_label.setText("")
            return
        guess = "" if self.s.record_gb_per_hour else " (a guess until your first long recording)"
        self.space_label.setText(
            f"Free space: {free / GB:.0f} GB, room for about {hours_text(free / GB / self.gb_per_hour())} of "
            f"recording. Recordings use about {self.gb_per_hour():.0f} GB an hour{guess}.")
        low = free / GB / self.gb_per_hour() < GAME_HOURS
        self.space_label.setStyleSheet("color: #ff8a6a;" if low else "")

    def _room_for_a_game(self) -> bool:
        hours = self.hours_left()
        if hours is None or hours >= GAME_HOURS:
            return True
        answer = QMessageBox.question(
            self, "Not much space left",
            f"There's only room for about {hours_text(hours)} of recording on that drive. A {GAME_HOURS}-hour game "
            f"needs about {GAME_HOURS * self.gb_per_hour():.0f} GB.\n\nFree up some space (old recordings you've "
            "already made videos from are the big ones), or pick a bigger drive in Settings > Your videos.\n\n"
            "Record anyway?")
        return answer == QMessageBox.Yes

    @property
    def recording(self) -> bool:
        return self.proc is not None

    def open_folder(self):
        folder = recordings_folder(self.s)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def choose_obs(self):
        path, _ = QFileDialog.getOpenFileName(self, "Find OBS (obs64.exe)", "", "OBS (obs64.exe)")
        if path:
            self.s.obs_exe = path
            self._save()
            self.refresh()

    def _save_choice(self, on: bool):
        self.s.open_after_record = on
        self._save()

    def _save(self):
        try:
            settings_mod.save(self.s)
        except OSError:
            pass

    # --- recording ---
    def toggle(self):
        if self.recording:
            self.stop()
        else:
            self.start()

    def start(self):
        exe = obs.find_exe(self.s.obs_exe)
        if exe is None:
            self.refresh()
            return
        if obs.is_running():
            QMessageBox.information(self, "Close OBS first",
                                    "OBS is already open. Close it first (Lethal Cuts starts it with its own settings), "
                                    "then click Start recording again.")
            return
        if not self._room_for_a_game():
            return
        folder = recordings_folder(self.s)
        try:
            obs.set_up(folder)
            self.proc = obs.start(exe)
        except OSError as e:
            QMessageBox.warning(self, "Lethal Cuts", f"OBS couldn't be started:\n{e}")
            self.proc = None
            return
        self.started_at = time.time()
        self.stopping = False
        self._warned = False
        self._space_warned = False
        self.moments = []
        self._start_hotkey()
        self.big_btn.setText("Stop recording")
        self.state.setText("●  Recording  0:00")
        self.state.setStyleSheet("color: #ff5a6a;")
        self.note.setText("OBS is starting by the clock. Play your game: Lethal Cuts keeps an eye on it.")
        self.clock.start()
        self.status.emit("Recording with OBS.")

    def stop(self):
        if not self.recording or self.stopping:
            return
        self.stopping = True
        self.big_btn.setEnabled(False)
        self.note.setText("Stopping and finishing the file. This can take a few seconds...")
        proc = self.proc
        threading.Thread(target=lambda: self._closed.emit(obs.close(proc)), daemon=True).start()

    def _on_closed(self, ok: bool):
        if not ok:
            self.stopping = False
            self.big_btn.setEnabled(True)
            QMessageBox.warning(self, "Lethal Cuts",
                                "OBS didn't close by itself. Right-click its icon by the clock and choose Exit, "
                                "and the recording will still be picked up here.")
            return
        self._finish()

    # --- marking moments ---
    def _start_hotkey(self):
        self.hotkey = GlobalHotkey(self.s.moment_key, self)
        self.hotkey.pressed.connect(self.mark_moment)
        self.moment_btn.show()
        if self.hotkey.start():
            self.moment_label.setText(f"Press {self.s.moment_key} any time, even in the game, when something great "
                                      f"happens. It marks the {self.s.moment_minutes:g} minutes before.")
        else:
            self.hotkey = None
            self.moment_label.setText(f"Another program is using {self.s.moment_key}, so the key won't work this "
                                      "time. Click the button instead, or pick another key in Settings > Recording.")

    def _stop_hotkey(self):
        if self.hotkey:
            self.hotkey.stop()
            self.hotkey = None
        self.moment_btn.hide()

    def mark_moment(self):
        if not self.recording or self.stopping:
            return
        now = time.time()
        if self.moments and now - self.moments[-1] < 2:
            return  # a double press
        self.moments.append(now)
        n = len(self.moments)
        at = format_time(now - self.started_at, tenths=False)
        self.moment_label.setText(f"{n} moment{'s' if n != 1 else ''} marked (the last one at {at}).")
        self.status.emit(f"Moment {n} marked at {at}.")

    def _save_moments(self, video: Path | None):
        """Puts the marked moments on the recording's timeline, measured from when OBS started the file."""
        if not video or not self.moments:
            return
        try:
            began = video.stat().st_ctime  # when the file was made, which is when recording began
            project = open_project(video)
            project.moments = sorted(set(project.moments) | {round(max(0.0, m - began), 3) for m in self.moments})
            project.save()
        except (OSError, ValueError, KeyError) as e:
            self.status.emit(f"Couldn't save the marked moments: {e}")

    def _learn_size(self, video: Path, seconds: float):
        """Remembers how big recordings really are, so the free-space guess gets better."""
        if seconds < 5 * 60:
            return
        try:
            rate = video.stat().st_size / GB / (seconds / 3600)
        except OSError:
            return
        old = self.s.record_gb_per_hour
        self.s.record_gb_per_hour = round((old + rate) / 2 if old else rate, 2)
        self._save()

    def _tick(self):
        if not self.recording:
            return
        elapsed = time.time() - self.started_at
        self._space_ticks = getattr(self, "_space_ticks", 0) + 1
        if self._space_ticks % 20 == 0:  # every 10 seconds
            self.refresh_space()
            free = free_space(recordings_folder(self.s))
            if not self._space_warned and free is not None and free < NEARLY_FULL_GB * GB:
                self._space_warned = True
                self.note.setText(f"The drive is nearly full ({free / GB:.1f} GB left). Stop the recording soon, "
                                  "or OBS will stop by itself when the drive is full.")
                self.note.setStyleSheet("color: #ff8a6a;")
        self.state.setText(f"●  Recording  {format_time(elapsed, tenths=False)}")
        folder = recordings_folder(self.s)
        if not self._warned and elapsed > NO_FILE_WARNING and not obs.recording_started(folder, self.started_at):
            self._warned = True
            self.note.setText("OBS hasn't started a recording file yet. Click the OBS icon by the clock to check it, "
                              "or click Stop recording and try again.")
        if self.proc.poll() is not None and not self.stopping:
            self._finish()  # OBS was closed some other way: still pick up the recording

    def _finish(self):
        self.clock.stop()
        self._stop_hotkey()
        folder = recordings_folder(self.s)
        video = obs.newest_recording(folder, self.started_at)
        if video:
            obs.wait_for_file_settled(video)
            self._save_moments(video)
            self._learn_size(video, time.time() - self.started_at)
        self.proc = None
        self.stopping = False
        self.big_btn.setText("Start recording")
        self.state.setStyleSheet("")
        self.note.setStyleSheet("")
        self.moment_label.setText("")
        if video:
            self.state.setText("Recording saved.")
            n = len(self.moments)
            marked = f", {n} moment{'s' if n != 1 else ''} marked" if n else ""
            self.note.setText(f"{video.name}  ({format_time(time.time() - self.started_at, tenths=False)}{marked})")
            self.status.emit(f"Recording saved: {video}")
        else:
            self.state.setText("No recording was made.")
            self.note.setText(f"OBS closed without saving a video in {folder}. Open OBS from the Start menu to check "
                              "its settings, then try again.")
        self.refresh()
        self.finished.emit(video if video and self.s.open_after_record else None)

    def shutdown(self) -> None:
        """When Lethal Cuts closes mid-recording, stop OBS properly first."""
        if self.recording:
            self._stop_hotkey()
            obs.close(self.proc)
            self.proc = None
            video = obs.newest_recording(recordings_folder(self.s), self.started_at)
            if video:
                obs.wait_for_file_settled(video)
                self._save_moments(video)
