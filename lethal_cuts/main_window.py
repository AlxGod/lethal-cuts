"""The main window: video, play controls, timeline and the clip list."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QImage, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QSplitter, QStyle, QVBoxLayout, QWidget,
)

from .clip_list import ClipList
from .project import Clip, Project, format_time, open_project
from .thumbnails import ThumbnailMaker, thumbnail_time
from .timeline import Timeline
from .video_view import VideoView

VIDEO_FILTER = "Videos (*.mov *.mp4 *.m4v *.mkv);;All files (*.*)"
VIDEO_SUFFIXES = {".mov", ".mp4", ".m4v", ".mkv"}
MIN_CLIP_SECONDS = 0.5
STEP_SECONDS = 5.0        # arrow keys
SMALL_STEP_SECONDS = 1.0  # Shift + arrow keys
NUDGE_SECONDS = 0.1       # fine-tune buttons
SPEEDS = [1, 2, 3, 4]


def _precise(seconds: float) -> str:
    """A time to the hundredth of a second, e.g. 1:02.35, for fine-tuning."""
    seconds = round(seconds, 2)
    return f"{format_time(seconds, tenths=False)}.{int(round(seconds * 100)) % 100:02d}"


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

        self.thumbs = ThumbnailMaker(self)
        self.thumbs.ready.connect(self._on_thumbnail)

        # Controls row
        self.open_btn = QPushButton("Open video")
        self.open_btn.setToolTip("Open a game recording (Ctrl+O)")
        self.open_btn.clicked.connect(self.choose_video)
        self.play_btn = QPushButton()
        self.play_btn.setToolTip("Play or pause (Space)")
        self.play_btn.clicked.connect(self.toggle_play)
        self.time_label = QLabel("0:00.0 / 0:00.0")
        self.time_label.setObjectName("timeLabel")

        self.speed_group = QButtonGroup(self)
        speed_box = QHBoxLayout()
        speed_box.setSpacing(2)
        speed_label = QLabel("Speed")
        speed_label.setObjectName("dimLabel")
        speed_box.addWidget(speed_label)
        for speed in SPEEDS:
            btn = QPushButton(f"{speed}x")
            btn.setObjectName("speedButton")
            btn.setCheckable(True)
            btn.setToolTip(f"Play at {speed}x speed for skimming (key {speed})")
            self.speed_group.addButton(btn, speed)
            speed_box.addWidget(btn)
        self.speed_group.button(1).setChecked(True)
        self.speed_group.idClicked.connect(self.set_speed)

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
        controls.addSpacing(12)
        controls.addLayout(speed_box)
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

        # Fine-tune: move the selected clip's start or end by a tenth of a second
        self.nudge_box = QGroupBox("Fine-tune the selected clip")
        grid = QGridLayout(self.nudge_box)
        self.start_value = QLabel("-")
        self.end_value = QLabel("-")
        self.nudge_buttons = []
        for row, (label, value, edge) in enumerate([("Start", self.start_value, "start"), ("End", self.end_value, "end")]):
            grid.addWidget(QLabel(label), row, 0)
            value.setObjectName("timeLabel")
            grid.addWidget(value, row, 1)
            for col, delta in [(2, -NUDGE_SECONDS), (3, NUDGE_SECONDS)]:
                btn = QPushButton(f"{'-' if delta < 0 else '+'}{NUDGE_SECONDS:g}s")
                btn.setToolTip(f"Move the clip's {edge} {'earlier' if delta < 0 else 'later'} by {NUDGE_SECONDS:g} second")
                btn.setAutoRepeat(True)  # hold the button to keep nudging
                btn.clicked.connect(lambda _=False, e=edge, d=delta: self.nudge(e, d))
                grid.addWidget(btn, row, col)
                self.nudge_buttons.append(btn)
        grid.setColumnStretch(1, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        clips_title = QLabel("Clips")
        clips_title.setObjectName("panelTitle")
        right_layout.addWidget(clips_title)
        right_layout.addWidget(self.clip_list, 1)
        right_layout.addWidget(self.nudge_box)
        right_layout.addWidget(self.delete_btn)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([1000, 400])
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
        keys = [
            ("Space", self.toggle_play),
            ("I", self.mark_start),
            ("O", self.mark_end),
            ("Escape", self.cancel_mark),
            ("Delete", self.delete_selected),
            ("Ctrl+Z", self.undo_delete),
            ("Left", lambda: self.step(-STEP_SECONDS)),
            ("Right", lambda: self.step(STEP_SECONDS)),
            ("Shift+Left", lambda: self.step(-SMALL_STEP_SECONDS)),
            ("Shift+Right", lambda: self.step(SMALL_STEP_SECONDS)),
        ]
        keys += [(str(s), lambda s=s: self.set_speed(s)) for s in SPEEDS]
        for key, handler in keys:
            QShortcut(QKeySequence(key), self, activated=handler)

        # A quick timer keeps the playhead moving smoothly while playing.
        self.tick = QTimer(self, interval=40, timeout=self._refresh_position)
        self.tick.start()
        # Saves are bunched together: half a second after the last change.
        self.save_timer = QTimer(self, singleShot=True, interval=500, timeout=self.save_now)
        # Preview pictures are made once clips stop changing (e.g. after a held nudge button).
        self.thumb_timer = QTimer(self, singleShot=True, interval=400, timeout=self._request_thumbnails)

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
        self.thumbs.set_video(path)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.set_speed(1)
        self.video.set_has_video(True)
        self.setWindowTitle(f"Lethal Cuts - {path.name}")
        self._refresh_clips()
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

    def set_speed(self, speed: int):
        self.player.setPlaybackRate(float(speed))
        self.speed_group.button(speed).setChecked(True)
        if self.project:
            self.statusBar().showMessage(f"Playing at {speed}x speed.")

    def seek(self, seconds: float):
        duration = self.player.duration() / 1000
        if duration > 0:
            seconds = min(seconds, duration)
        self.player.setPosition(int(max(seconds, 0.0) * 1000))
        self._refresh_position()

    def step(self, seconds: float):
        if self.project:
            self.seek(self.current_time() + seconds)

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
        start, end = self.pending_start, self.current_time()
        if end - start < MIN_CLIP_SECONDS:
            self.statusBar().showMessage("That clip is too short. Let the video play past the start mark, then press O.")
            return
        overlaps = self.project.overlapping(start, end)
        if overlaps and not self._confirm_overlap(overlaps):
            self.statusBar().showMessage("Clip not saved. Your start mark is still set: press O again, or Esc to cancel.")
            return
        clip = Clip(start, end)
        index = self.project.add_clip(clip)
        self.pending_start = None
        self.timeline.set_pending_start(None)
        self._refresh_clips(select=index)
        self._changed()
        self.statusBar().showMessage(f"Clip {index + 1} saved ({clip.length:.1f} seconds). Click its name in the list to rename it.")

    def _confirm_overlap(self, overlaps: list[int]) -> bool:
        lines = [
            f"Clip {i + 1}{' (' + self.project.clips[i].name + ')' if self.project.clips[i].name else ''}: "
            f"{format_time(self.project.clips[i].start)} to {format_time(self.project.clips[i].end)}"
            for i in overlaps
        ]
        answer = QMessageBox.question(
            self, "Clips overlap",
            "This clip overlaps a clip you already made:\n\n" + "\n".join(lines) + "\n\nSave it anyway?",
        )
        return answer == QMessageBox.Yes

    def cancel_mark(self):
        if self.pending_start is not None:
            self.pending_start = None
            self.timeline.set_pending_start(None)
            self.statusBar().showMessage("Start mark cancelled.")

    # --- fine-tuning ---
    def nudge(self, edge: str, delta: float):
        index = self.clip_list.selected_index()
        if not self.project or index < 0:
            return
        clip = self.project.clips[index]
        duration = self.player.duration() / 1000 or clip.end
        if edge == "start":
            clip.start = round(min(max(clip.start + delta, 0.0), clip.end - MIN_CLIP_SECONDS), 3)
            shown = clip.start
        else:
            clip.end = round(max(min(clip.end + delta, duration), clip.start + MIN_CLIP_SECONDS), 3)
            shown = clip.end
        # Pause on the edge being moved so the user can see exactly where it lands.
        self.player.pause()
        self.seek(shown)
        self.project.sort()
        self._refresh_clips(select=self.project.index_of(clip))
        self._changed()

    # --- clip list ---
    def _thumb_for(self, clip: Clip) -> QImage | None:
        image = self.thumbs.get(thumbnail_time(clip.start, clip.length))
        if image is None:
            self.thumb_timer.start()  # ask once the clip list has settled
        return image

    def _request_thumbnails(self):
        clips = self.project.clips if self.project else []
        self.thumbs.request_only([thumbnail_time(c.start, c.length) for c in clips])

    def _on_thumbnail(self, seconds: float, image: QImage):
        for row, clip in enumerate(self.project.clips if self.project else []):
            if round(thumbnail_time(clip.start, clip.length), 2) == seconds:
                self.clip_list.set_thumbnail(row, image)

    def _refresh_clips(self, select: int = -1):
        clips = self.project.clips if self.project else []
        self.clip_list.set_clips(clips, select, self._thumb_for)
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
        for w in [self.play_btn, self.mark_in_btn, self.mark_out_btn, *self.speed_group.buttons()]:
            w.setEnabled(has)
        index = self.clip_list.selected_index()
        selected = has and index >= 0
        self.delete_btn.setEnabled(selected)
        self.nudge_box.setEnabled(selected)
        if selected:
            clip = self.project.clips[index]
            self.start_value.setText(_precise(clip.start))
            self.end_value.setText(_precise(clip.end))
        else:
            self.start_value.setText("-")
            self.end_value.setText("-")

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
