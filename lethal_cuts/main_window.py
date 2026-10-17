"""The main window: video, play controls, timeline and the clip list."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QStyle, QVBoxLayout, QWidget,
)

from .clip_list import ClipList
from .project import Clip, Project, format_time, open_project
from .timeline import Timeline
from .video_view import VideoView

VIDEO_FILTER = "Videos (*.mov *.mp4 *.m4v *.mkv);;All files (*.*)"
VIDEO_SUFFIXES = {".mov", ".mp4", ".m4v", ".mkv"}
MIN_CLIP_SECONDS = 0.5


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lethal Cuts")
        self.resize(1400, 860)
        self.setAcceptDrops(True)

        self.project: Project | None = None
        self.pending_start: float | None = None
        self.last_deleted: Clip | None = None
        self._restore_position: float | None = None

        # Player
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = VideoView()
        self.player.setVideoOutput(self.video.video_item)
        self.player.durationChanged.connect(self._on_duration)
        self.player.positionChanged.connect(lambda _: self._refresh_position())
        self.player.playbackStateChanged.connect(lambda _: self._refresh_play_button())
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.errorOccurred.connect(self._on_player_error)

        # Controls row
        self.open_btn = QPushButton("Open video")
        self.open_btn.setToolTip("Open a game recording (Ctrl+O)")
        self.open_btn.clicked.connect(self.choose_video)
        self.play_btn = QPushButton()
        self.play_btn.setToolTip("Play or pause (Space)")
        self.play_btn.clicked.connect(self.toggle_play)
        self.time_label = QLabel("0:00.0 / 0:00.0")
        self.time_label.setObjectName("timeLabel")
        self.mark_in_btn = QPushButton("Mark start  (I)")
        self.mark_in_btn.setObjectName("markIn")
        self.mark_in_btn.setToolTip("Mark where a clip starts. The video keeps playing.")
        self.mark_in_btn.clicked.connect(self.mark_start)
        self.mark_out_btn = QPushButton("Mark end  (O)")
        self.mark_out_btn.setObjectName("markOut")
        self.mark_out_btn.setToolTip("Mark where the clip ends. This saves the clip.")
        self.mark_out_btn.clicked.connect(self.mark_end)

        controls = QHBoxLayout()
        controls.addWidget(self.open_btn)
        controls.addSpacing(12)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.time_label)
        controls.addStretch(1)
        controls.addWidget(self.mark_in_btn)
        controls.addWidget(self.mark_out_btn)

        self.timeline = Timeline()
        self.timeline.seek_requested.connect(self.seek)
        self.timeline.clip_clicked.connect(self._select_clip)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.video, 1)
        left_layout.addLayout(controls)
        left_layout.addWidget(self.timeline)

        # Clip list
        self.clip_list = ClipList()
        self.clip_list.clip_selected.connect(self._on_list_selection)
        self.clip_list.clip_activated.connect(self._jump_to_clip)
        self.clip_list.name_changed.connect(self._on_name_changed)
        self.delete_btn = QPushButton("Delete clip")
        self.delete_btn.setToolTip("Delete the selected clip (Delete key). Ctrl+Z brings it back.")
        self.delete_btn.clicked.connect(self.delete_selected)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        clips_title = QLabel("Clips")
        clips_title.setObjectName("panelTitle")
        right_layout.addWidget(clips_title)
        right_layout.addWidget(self.clip_list, 1)
        right_layout.addWidget(self.delete_btn)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([1040, 360])
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(10, 10, 10, 6)
        outer.addWidget(splitter)
        self.setCentralWidget(container)

        # Menu and keys
        file_menu = self.menuBar().addMenu("&File")
        open_action = QAction("&Open video...", self, shortcut=QKeySequence.Open, triggered=self.choose_video)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        file_menu.addAction(QAction("E&xit", self, triggered=self.close))
        for key, handler in [
            ("Space", self.toggle_play),
            ("I", self.mark_start),
            ("O", self.mark_end),
            ("Escape", self.cancel_mark),
            ("Delete", self.delete_selected),
            ("Ctrl+Z", self.undo_delete),
        ]:
            QShortcut(QKeySequence(key), self, activated=handler)

        # A quick timer keeps the playhead moving smoothly while playing.
        self.tick = QTimer(self, interval=40, timeout=self._refresh_position)
        self.tick.start()
        # Saves are bunched together: half a second after the last change.
        self.save_timer = QTimer(self, singleShot=True, interval=500, timeout=self.save_now)

        self._refresh_play_button()
        self._update_enabled()
        self.statusBar().showMessage("Open a game video to start.")

    # --- opening videos ---
    def choose_video(self):
        start_dir = str(self.project.video_path.parent) if self.project else ""
        path, _ = QFileDialog.getOpenFileName(self, "Open game video", start_dir, VIDEO_FILTER)
        if path:
            self.open_video(Path(path))

    def open_video(self, path: Path):
        self.save_now()
        try:
            self.project = open_project(path)
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.warning(self, "Lethal Cuts", f"Couldn't read the saved progress for this video:\n{e}\n\nStarting fresh.")
            self.project = Project(path)
        self.pending_start = None
        self.last_deleted = None
        self._restore_position = self.project.position
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.video.set_has_video(True)
        self.setWindowTitle(f"Lethal Cuts - {path.name}")
        self._refresh_clips()
        self._update_enabled()
        n = len(self.project.clips)
        self.statusBar().showMessage(
            f"Opened {path.name}. " + (f"{n} saved clip{'s' if n != 1 else ''} loaded." if n else "Press I at the start of a good moment.")
        )

    def _on_media_status(self, status):
        if status == QMediaPlayer.LoadedMedia and self._restore_position is not None:
            self.seek(self._restore_position)
            self._restore_position = None

    def _on_duration(self, ms: int):
        self.timeline.set_duration(ms / 1000)
        self._refresh_position()

    def _on_player_error(self, error, message):
        QMessageBox.warning(self, "Lethal Cuts", f"This video couldn't be played.\n\n{message}")

    # --- playback ---
    def toggle_play(self):
        if not self.project:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek(self, seconds: float):
        self.player.setPosition(int(seconds * 1000))
        self._refresh_position()

    def current_time(self) -> float:
        return self.player.position() / 1000

    def _refresh_position(self):
        pos = self.current_time()
        self.timeline.set_position(pos)
        self.time_label.setText(f"{format_time(pos)} / {format_time(self.player.duration() / 1000)}")

    def _refresh_play_button(self):
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        icon = QStyle.SP_MediaPause if playing else QStyle.SP_MediaPlay
        self.play_btn.setIcon(self.style().standardIcon(icon))
        self.play_btn.setText("Pause" if playing else "Play")

    # --- marking clips ---
    def mark_start(self):
        if not self.project:
            return
        self.pending_start = self.current_time()
        self.timeline.set_pending_start(self.pending_start)
        self.statusBar().showMessage(f"Start marked at {format_time(self.pending_start)}. Press O when the moment ends (Esc cancels).")

    def mark_end(self):
        if not self.project:
            return
        if self.pending_start is None:
            self.statusBar().showMessage("Press I (Mark start) first, then O at the end of the moment.")
            return
        end = self.current_time()
        if end - self.pending_start < MIN_CLIP_SECONDS:
            self.statusBar().showMessage("That clip is too short. Let the video play past the start mark, then press O.")
            return
        clip = Clip(self.pending_start, end)
        index = self.project.add_clip(clip)
        self.pending_start = None
        self.timeline.set_pending_start(None)
        self._refresh_clips(select=index)
        self._changed()
        self.statusBar().showMessage(f"Clip {index + 1} saved ({clip.length:.1f} seconds). Click its name in the list to rename it.")

    def cancel_mark(self):
        if self.pending_start is not None:
            self.pending_start = None
            self.timeline.set_pending_start(None)
            self.statusBar().showMessage("Start mark cancelled.")

    # --- clip list ---
    def _refresh_clips(self, select: int = -1):
        clips = self.project.clips if self.project else []
        self.clip_list.set_clips(clips, select)
        self.timeline.set_clips(clips, select)
        self.timeline.set_pending_start(self.pending_start)
        self._update_enabled()

    def _select_clip(self, index: int):
        self.clip_list.selectRow(index)

    def _on_list_selection(self, index: int):
        self.timeline.set_clips(self.project.clips if self.project else [], index)
        self._update_enabled()

    def _jump_to_clip(self, index: int):
        if self.project and 0 <= index < len(self.project.clips):
            self.seek(self.project.clips[index].start)

    def _on_name_changed(self, index: int, name: str):
        if self.project and 0 <= index < len(self.project.clips):
            self.project.clips[index].name = name
            self._changed()

    def delete_selected(self):
        index = self.clip_list.selected_index()
        if not self.project or index < 0:
            return
        self.last_deleted = self.project.clips.pop(index)
        self._refresh_clips()
        self._changed()
        self.statusBar().showMessage(f"Clip {index + 1} deleted. Press Ctrl+Z to bring it back.")

    def undo_delete(self):
        if not self.project or self.last_deleted is None:
            return
        index = self.project.add_clip(self.last_deleted)
        self.last_deleted = None
        self._refresh_clips(select=index)
        self._changed()
        self.statusBar().showMessage(f"Clip {index + 1} restored.")

    def _update_enabled(self):
        has = self.project is not None
        for w in (self.play_btn, self.mark_in_btn, self.mark_out_btn):
            w.setEnabled(has)
        self.delete_btn.setEnabled(has and self.clip_list.selected_index() >= 0)

    # --- saving ---
    def _changed(self):
        self.save_timer.start()

    def save_now(self):
        if not self.project:
            return
        self.project.position = self.current_time()
        try:
            self.project.save()
        except OSError as e:
            self.statusBar().showMessage(f"Couldn't save progress: {e}")

    def closeEvent(self, event):
        self.save_now()
        super().closeEvent(event)

    # --- drag and drop ---
    def dragEnterEvent(self, event):
        if any(Path(u.toLocalFile()).suffix.lower() in VIDEO_SUFFIXES for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in VIDEO_SUFFIXES:
                self.open_video(path)
                break
