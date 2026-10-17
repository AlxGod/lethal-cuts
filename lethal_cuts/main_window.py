"""The main window: video, play controls, timeline and the clip list."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QImage, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QSplitter, QStyle, QTabWidget, QVBoxLayout, QWidget,
)

from . import crop as cropmath
from . import updater
from . import settings as settings_mod
from .clip_list import ClipList
from .cut_list import CutList
from .folders import default_save_folder, long_videos_folder, save_folder, shorts_folder
from . import __version__
from .export_dialog import ExportDialog
from .guide import GuidePage
from .long_export import LongExportWorker, kept_length
from .help import HELP, HelpButton, with_help
from .library import Library
from .settings import QUALITIES, Settings
from .post_page import PostPage
from .settings_page import SettingsPage
from .project import Clip, Project, format_time, open_project
from .thumbnails import ThumbnailMaker, thumbnail_time
from .timeline import Timeline
from .video_view import VideoView
from .walkthrough import Walkthrough

VIDEO_FILTER = "Videos (*.mov *.mp4 *.m4v *.mkv);;All files (*.*)"
VIDEO_SUFFIXES = {".mov", ".mp4", ".m4v", ".mkv"}
MIN_CLIP_SECONDS = 0.5
SMALL_STEP_SECONDS = 1.0  # Shift + arrow keys (the normal jump is in Settings)
NUDGE_SECONDS = 0.1       # fine-tune buttons
SPEEDS = [1, 2, 3, 4]
LONG_CLIP_SECONDS = 60    # past this, a tip says most strong Shorts are shorter


def _precise(seconds: float) -> str:
    """A time to the hundredth of a second, e.g. 1:02.35, for fine-tuning."""
    seconds = round(seconds, 2)
    return f"{format_time(seconds, tenths=False)}.{int(round(seconds * 100)) % 100:02d}"


class MainWindow(QMainWindow):
    def __init__(self, s: Settings | None = None):
        super().__init__()
        self.settings = s or settings_mod.load()
        if not self.settings.save_folder:  # first start: use the folder picked while installing
            self.settings.save_folder = str(default_save_folder())
            try:
                settings_mod.save(self.settings)
            except OSError:
                pass
        self.setWindowTitle("Lethal Cuts")
        self.resize(1400, 860)
        self.setAcceptDrops(True)

        self.project: Project | None = None
        self.library = Library.load()
        self.pending_start: float | None = None
        self.last_deleted: tuple[bool, Clip] | None = None  # (was it a cut, the clip or cut)
        self.long_mode = False      # Editor is making a long video (marks are cuts) instead of Shorts
        self.long_preview = False   # playing the long video with the cuts skipped
        self._restore_position: float | None = None

        # Player
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = VideoView()
        self.player.setVideoOutput(self.video.video_item)
        self.video.crop_changed.connect(self._on_crop_changed)
        self.preview_clip: Clip | None = None  # the clip shown in vertical preview, if on
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

        self.mark_in_btn = QPushButton()
        self.mark_in_btn.setObjectName("markIn")
        self.mark_in_btn.setToolTip("Mark where a clip starts. The video keeps playing.")
        self.mark_in_btn.clicked.connect(self.mark_start)
        self.mark_out_btn = QPushButton()
        self.mark_out_btn.setObjectName("markOut")
        self.mark_out_btn.setToolTip("Mark where the clip ends. This saves the clip.")
        self.mark_out_btn.clicked.connect(self.mark_end)

        speed_box.addWidget(HelpButton(HELP["speed"]))
        controls = QHBoxLayout()
        controls.addLayout(with_help(self.open_btn, "open"))
        controls.addSpacing(12)
        controls.addLayout(with_help(self.play_btn, "play"))
        controls.addWidget(self.time_label)
        controls.addSpacing(12)
        controls.addLayout(speed_box)
        controls.addStretch(1)
        controls.addWidget(self.mark_in_btn)
        controls.addLayout(with_help(self.mark_out_btn, "mark"))

        self.timeline = Timeline()
        self.timeline.seek_requested.connect(self.seek)
        self.timeline.clip_clicked.connect(self._select_clip)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        video_row = QHBoxLayout()
        video_row.addWidget(self.video, 1)
        video_help = QVBoxLayout()
        video_help.addWidget(HelpButton(HELP["crop"]))
        video_help.addStretch(1)
        video_row.addLayout(video_help)
        left_layout.addLayout(video_row, 1)
        left_layout.addLayout(controls)
        timeline_row = QHBoxLayout()
        timeline_row.addWidget(self.timeline, 1)
        timeline_row.addWidget(HelpButton(HELP["timeline"]))
        left_layout.addLayout(timeline_row)

        # Clip list
        self.clip_list = ClipList()
        self.clip_list.clip_selected.connect(self._on_list_selection)
        self.clip_list.clip_activated.connect(self._jump_to_clip)
        self.clip_list.name_changed.connect(self._on_name_changed)
        self.cut_list = CutList()
        self.cut_list.cut_selected.connect(self._on_list_selection)
        self.cut_list.cut_activated.connect(self._jump_to_clip)
        self.cut_list.hide()
        self.delete_btn = QPushButton("Delete clip")
        self.delete_btn.setToolTip("Delete the selected one (Delete key). Ctrl+Z brings it back.")
        self.delete_btn.clicked.connect(self.delete_selected)
        self.preview_btn = QPushButton()
        self.preview_btn.setObjectName("previewButton")
        self.preview_btn.setCheckable(True)
        self.preview_btn.setToolTip("Play the selected clip exactly as the tall phone video will look")
        self.preview_btn.clicked.connect(self.toggle_preview)
        self.export_btn = QPushButton("Export all clips")
        self.export_btn.setObjectName("exportButton")
        self.export_btn.setToolTip("Make every clip into a tall 1080x1920 video, ready for Shorts and TikTok (Ctrl+E)")
        self.export_btn.clicked.connect(self.export_all)
        self.post_btn = QPushButton("Post clips")
        self.post_btn.setToolTip("Opens the Post tab: every finished clip, ready to watch and post one at a time")
        self.post_btn.clicked.connect(self.show_post)

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
        grid.addWidget(HelpButton(HELP["nudge"]), 0, 4)
        grid.setColumnStretch(1, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        # What's being made: Shorts from clips, or one long video with the dead parts cut out
        self.mode_group = QButtonGroup(self)
        self.shorts_mode_btn = QPushButton("Shorts")
        self.shorts_mode_btn.setToolTip("Mark the best moments: each one becomes a tall clip for Shorts and TikTok")
        self.long_mode_btn = QPushButton("Long video")
        self.long_mode_btn.setToolTip("Make one widescreen video of the whole game, with the dead stretches cut out")
        for i, b in enumerate((self.shorts_mode_btn, self.long_mode_btn)):
            b.setObjectName("speedButton")
            b.setCheckable(True)
            self.mode_group.addButton(b, i)
        self.shorts_mode_btn.setChecked(True)
        self.mode_group.idClicked.connect(lambda i: self.set_mode(i == 1))
        making = QLabel("Making:")
        making.setObjectName("dimLabel")
        mode_row = QHBoxLayout()
        mode_row.addWidget(making)
        mode_row.addWidget(self.shorts_mode_btn)
        mode_row.addWidget(self.long_mode_btn)
        mode_row.addWidget(HelpButton(HELP["mode"]))
        mode_row.addStretch(1)
        right_layout.addLayout(mode_row)
        right_layout.addSpacing(4)
        self.list_title = QLabel("Clips")
        self.list_title.setObjectName("panelTitle")
        self.list_help = HelpButton(HELP["clips"])
        title_row = QHBoxLayout()
        title_row.addWidget(self.list_title)
        title_row.addStretch(1)
        title_row.addWidget(self.list_help)
        right_layout.addLayout(title_row)
        # Friendly tips about the picked clip (can be turned off in Settings)
        self.tip_label = QLabel()
        self.tip_label.setObjectName("tipLabel")
        self.tip_label.setWordWrap(True)
        self.tip_label.hide()
        right_layout.addWidget(self.tip_label)
        self.long_note = QLabel("Mark the parts to cut out: press I where a dead stretch starts and O where it ends. "
                                "Everything else stays in the long video.")
        self.long_note.setObjectName("dimLabel")
        self.long_note.setWordWrap(True)
        self.long_note.hide()
        right_layout.addWidget(self.long_note)
        right_layout.addWidget(self.clip_list, 1)
        right_layout.addWidget(self.cut_list, 1)
        self.long_summary = QLabel()
        self.long_summary.setObjectName("timeLabel")
        self.long_summary.setWordWrap(True)
        self.long_summary.hide()
        right_layout.addWidget(self.long_summary)
        right_layout.addWidget(self.nudge_box)
        self.preview_help = HelpButton(HELP["preview"])
        self.export_help = HelpButton(HELP["export"])
        clip_buttons = QHBoxLayout()
        clip_buttons.addWidget(self.preview_btn, 1)
        clip_buttons.addWidget(self.preview_help)
        clip_buttons.addLayout(with_help(self.delete_btn, "delete"))
        right_layout.addLayout(clip_buttons)
        right_layout.addSpacing(6)
        export_buttons = QHBoxLayout()
        export_buttons.addWidget(self.export_btn, 1)
        export_buttons.addWidget(self.export_help)
        export_buttons.addLayout(with_help(self.post_btn, "post_clips"))
        right_layout.addLayout(export_buttons)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([1000, 400])
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(10, 10, 10, 6)
        outer.addWidget(splitter)

        self.guide = GuidePage(self.settings)
        self.guide.replay_walkthrough.connect(self.start_walkthrough)
        self.settings_page = SettingsPage(self.settings)
        self.settings_page.changed.connect(self.apply_settings)
        self.tabs = QTabWidget()
        self.post_page = PostPage(self.library)
        self.post_page.open_folder.connect(lambda: self.settings_page.open_folder())
        self.post_page.change_folder.connect(lambda: self.settings_page.choose_folder())
        self.tabs.addTab(container, "Editor")
        self.tabs.addTab(self.post_page, "Post")
        self.tabs.addTab(self.guide, "Guide")
        self.tabs.addTab(self.settings_page, "Settings")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        # The bar that appears when a newer version is out
        self.update_bar = QFrame()
        self.update_bar.setObjectName("updateBar")
        self.update_label = QLabel()
        self.update_now_btn = QPushButton("Update now")
        self.update_now_btn.setObjectName("exportButton")
        self.update_now_btn.clicked.connect(self.start_update)
        later = QPushButton("Not now")
        later.clicked.connect(self.update_bar.hide)
        bar = QHBoxLayout(self.update_bar)
        bar.setContentsMargins(14, 6, 14, 6)
        bar.addWidget(self.update_label, 1)
        bar.addWidget(self.update_now_btn)
        bar.addWidget(later)
        self.update_bar.hide()
        self.available_update: updater.Update | None = None
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.update_bar)
        central_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        # Menu and keys
        file_menu = self.menuBar().addMenu("&File")
        self.open_action = QAction("&Open video...", self, triggered=self.choose_video)
        file_menu.addAction(self.open_action)
        self.export_action = QAction("&Export all clips", self, triggered=self.export_all)
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        file_menu.addAction(QAction("E&xit", self, triggered=self.close))
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(QAction("&Guide", self, triggered=lambda: self.tabs.setCurrentWidget(self.guide)))
        help_menu.addAction(QAction("&Replay the walkthrough", self, triggered=self.start_walkthrough))
        help_menu.addAction(QAction("&Check for updates", self, triggered=lambda: self.check_for_updates(manual=True)))
        help_menu.addAction(QAction(f"Version {__version__}", self, enabled=False))
        self.shortcuts: list[QShortcut] = []
        self.walkthrough: Walkthrough | None = None

        # A quick timer keeps the playhead moving smoothly while playing.
        self.tick = QTimer(self, interval=40, timeout=self._refresh_position)
        self.tick.start()
        # Saves are bunched together: half a second after the last change.
        self.save_timer = QTimer(self, singleShot=True, interval=500, timeout=self.save_now)
        # Preview pictures are made once clips stop changing (e.g. after a held nudge button).
        self.thumb_timer = QTimer(self, singleShot=True, interval=400, timeout=self._request_thumbnails)

        self.apply_settings(self.settings)
        self._refresh_play_button()
        self._update_enabled()
        self.statusBar().showMessage("Open a game video to start.")
        if not self.settings.walkthrough_done:
            QTimer.singleShot(600, self.start_walkthrough)
        if updater.should_check():
            updater.clean_old_download()
            QTimer.singleShot(1500, self.check_for_updates)

    # --- updates ---
    def check_for_updates(self, manual: bool = False):
        """Asks GitHub once whether a newer version is out (in the background)."""
        if getattr(self, "_update_thread", None) and self._update_thread.isRunning():
            return
        self._checker = updater.Checker()
        self._update_thread = QThread(self)
        self._checker.moveToThread(self._update_thread)
        self._update_thread.started.connect(self._checker.run)
        self._checker.found.connect(lambda update: self._on_update_found(update, manual))
        self._checker.failed.connect(lambda error: self._on_update_failed(error, manual))
        self._checker.found.connect(self._update_thread.quit)
        self._checker.failed.connect(self._update_thread.quit)
        self._update_thread.start()

    def _on_update_found(self, update, manual: bool):
        self.available_update = update
        if update:
            self.update_label.setText(f"Lethal Cuts {update.version} is out (you have {__version__}). "
                                      "Updating takes about a minute and keeps your settings and clips.")
            self.update_bar.show()
        elif manual:
            QMessageBox.information(self, "Lethal Cuts", f"You have the newest version ({__version__}).")

    def _on_update_failed(self, error: str, manual: bool):
        if manual:
            QMessageBox.warning(self, "Lethal Cuts", f"Couldn't check for updates right now:\n{error}\n\n"
                                                     "Check the internet connection and try again later.")

    def start_update(self):
        if not self.available_update:
            return
        self.save_now()
        dialog = updater.UpdateDialog(self.available_update, self)
        if dialog.exec() and dialog.installer:
            updater.run_installer(dialog.installer)
            self.close()
            QApplication.quit()

    # --- settings ---
    def apply_settings(self, s: Settings):
        """Puts Settings into effect: hotkeys, button labels, colors, the Guide and tips."""
        self.settings = s
        for sc in self.shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        actions = {
            "play_pause": self.toggle_play,
            "mark_start": self.mark_start,
            "mark_end": self.mark_end,
            "cancel": self.escape,
            "preview": self.toggle_preview,
            "delete": self.delete_selected,
            "undo": self.undo_delete,
            "step_back": lambda: self.step(-self.settings.step_seconds),
            "step_forward": lambda: self.step(self.settings.step_seconds),
            "small_back": lambda: self.step(-SMALL_STEP_SECONDS),
            "small_forward": lambda: self.step(SMALL_STEP_SECONDS),
        }
        actions.update({f"speed_{n}": (lambda n=n: self.set_speed(n)) for n in SPEEDS})
        self.shortcuts = []
        for action, handler in actions.items():
            sc = QShortcut(QKeySequence(s.key(action)), self)
            sc.activated.connect(lambda h=handler: self._editor_key(h))
            self.shortcuts.append(sc)
        self.open_action.setShortcut(QKeySequence(s.key("open")))
        self.export_action.setShortcut(QKeySequence(s.key("export")))
        self.mark_in_btn.setText(f"Mark start  ({s.key('mark_start')})")
        self.mark_out_btn.setText(f"Mark end  ({s.key('mark_end')})")
        self._refresh_mode_labels()
        self.play_btn.setToolTip(f"Play or pause ({s.key('play_pause')})")
        for n in SPEEDS:
            self.speed_group.button(n).setToolTip(f"Play at {n}x speed for skimming (key {s.key(f'speed_{n}')})")
        self.timeline.set_colors(s.clip_color_a, s.clip_color_b)
        self.video.box_color = QColor(s.crop_color)
        self.video.viewport().update()
        self.guide.refresh(s)
        self.post_page.show_folder(save_folder(s))
        self._refresh_tips()

    def _editor_key(self, handler):
        """Hotkeys only work on the Editor tab, so typing in Settings or reading the Guide is safe."""
        if self.tabs.currentIndex() == 0 and not (self.walkthrough and self.walkthrough.active):
            handler()

    def _on_tab_changed(self, index: int):
        if index != 0:
            self.player.pause()
        if self.tabs.widget(index) is self.post_page:
            self.post_page.refresh()
        else:
            self.post_page.player.pause()

    # --- first-time walkthrough ---
    def start_walkthrough(self):
        self.tabs.setCurrentIndex(0)
        s = self.settings
        steps = [
            (None, "Welcome to Lethal Cuts",
             "This turns a long game recording into short vertical clips for YouTube Shorts and TikTok. "
             "Here's a quick look around. It takes about a minute."),
            (self.open_btn, "1. Open a game video",
             "Click Open video, or drag the file onto the window. iPhone videos work as they are."),
            (self.speed_group.button(4), "2. Skim through the game",
             f"Play at 2x, 3x or 4x speed to get through a long game fast. The arrow keys jump {s.step_seconds:g} seconds."),
            (self.mark_out_btn, "3. Mark the good moments",
             f"Press {s.key('mark_start')} when something great starts and {s.key('mark_end')} when it ends. "
             "The video keeps playing, so you can mark clips without stopping."),
            (self.timeline, "4. Your clips on the timeline",
             "Each clip shows up as a numbered bar. Click anywhere to jump there."),
            (self.clip_list, "5. Name and fine-tune clips",
             "Click a clip's name to rename it. The fine-tune buttons below move its start or end a tenth of a second at a time."),
            (self.video, "6. Pick what's in the phone video",
             "With a clip picked, a tall box appears on the video. Drag it over the cards and players. "
             f"Press {s.key('preview')} to see exactly how the phone video will look."),
            (self.export_btn, "7. Export",
             "Export all clips makes each one a ready-to-post vertical video with the volume evened out."),
            (self.long_mode_btn, "8. Long videos too",
             "Switch to Long video to make one normal widescreen video of the whole game instead. "
             "I and O then mark the dead stretches to cut out, and everything else stays in."),
            (self.tabs.tabBar(), "9. Post them one at a time",
             "The Post tab keeps every finished clip from every game. Watch them, post the best one to YouTube or "
             "TikTok, and tick it off. Posted clips move to their own list, so you always know what's left."),
            (self.tabs.tabBar(), "Need help later?",
             'The Guide tab has recording tips, the hotkey list and tips for strong Shorts. Every "?" button explains '
             "the control next to it."),
        ]
        if self.walkthrough:
            self.walkthrough.finish()
            self.walkthrough.deleteLater()
        self.walkthrough = Walkthrough(self, steps)
        self.walkthrough.finished.connect(self._walkthrough_done)
        self.walkthrough.start()

    def _walkthrough_done(self):
        if not self.settings.walkthrough_done:
            self.settings.walkthrough_done = True
            try:
                settings_mod.save(self.settings)
            except OSError:
                pass

    # --- friendly tips ---
    def _clip_tips(self, index: int) -> list[str]:
        clip = self.project.clips[index]
        n = index + 1
        tips = []
        if clip.length > LONG_CLIP_SECONDS:
            tips.append(f"Clip {n} is {clip.length:.0f} seconds long. Most strong Shorts are under 45 seconds.")
        if clip.crop is None:
            tips.append(f"Clip {n} has no crop box placed yet. Drag the box on the video over the part of the table to keep.")
        if not clip.name:
            tips.append(f"Clip {n} doesn't have a name yet. Click its name in the list to add one. It becomes the file name.")
        return tips

    def _refresh_tips(self):
        index = self.clip_list.selected_index()
        if not self.settings.nudges or not self.project or index < 0 or self.long_mode:
            self.tip_label.hide()
            return
        tips = self._clip_tips(index)
        self.tip_label.setText("\n".join(tips))
        self.tip_label.setVisible(bool(tips))

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
        self.stop_preview()
        self.pending_start = None
        self.last_deleted = None
        self._restore_position = self.project.position
        self.thumbs.set_video(path)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.set_speed(1)
        self.video.set_has_video(True)
        self.setWindowTitle(f"Lethal Cuts - {path.name}")
        self._refresh_clips()
        n, cuts = len(self.project.clips), len(self.project.cuts)
        saved = [f"{n} clip{'s' if n != 1 else ''}"] if n else []
        saved += [f"{cuts} cut{'s' if cuts != 1 else ''}"] if cuts else []
        self.statusBar().showMessage(
            f"Opened {path.name}. " + (f"Loaded {' and '.join(saved)}." if saved else "Press I at the start of a good moment.")
        )

    def _on_media_status(self, status):
        if status == QMediaPlayer.LoadedMedia and self._restore_position is not None:
            # Run just after this signal finishes: pausing inside it crashes Qt's player.
            QTimer.singleShot(0, self._show_first_frame)

    def _show_first_frame(self):
        """A stopped player shows no picture when seeking; a paused one shows the frame."""
        if self._restore_position is None:
            return
        self.player.pause()
        self.seek(self._restore_position)
        self._restore_position = None

    def _on_duration(self, ms: int):
        self.timeline.set_duration(ms / 1000)
        self._refresh_position()
        self._refresh_long_summary()

    def _on_player_error(self, error, message):
        QMessageBox.warning(self, "Lethal Cuts", f"This video couldn't be played.\n\n{message}")

    # --- playback ---
    def toggle_play(self):
        if not self.project:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            if self.preview_clip and self.current_time() >= self.preview_clip.end - 0.05:
                self.seek(self.preview_clip.start)  # watch the preview again
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
        if self.long_preview and self.project and self.player.playbackState() == QMediaPlayer.PlayingState:
            for cut in self.project.cuts:
                if cut.start <= pos < cut.end - 0.05:
                    if cut.end >= self.player.duration() / 1000 - 0.1:
                        self.stop_preview()
                        self.statusBar().showMessage("That's the end of the long video.")
                    else:
                        self.player.setPosition(int(cut.end * 1000))  # jump over the cut
                    break
        if self.preview_clip and pos >= self.preview_clip.end and self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.statusBar().showMessage("End of the clip. Space watches it again; P or Esc goes back.")
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
            self.statusBar().showMessage(
                f"That clip is too short. Let the video play past the start mark, then press {self.settings.key('mark_end')}.")
            return
        if self.long_mode:
            self._add_cut(start, end)
            return
        # Extra lead-in and lead-out from Settings, since it's easy to press a key a little late.
        duration = self.player.duration() / 1000 or end + self.settings.pad_after
        start = max(0.0, start - self.settings.pad_before)
        end = min(duration, end + self.settings.pad_after)
        overlaps = self.project.overlapping(start, end)
        if overlaps and not self._confirm_overlap(overlaps):
            self.statusBar().showMessage("Clip not saved. Your start mark is still set: press O again, or Esc to cancel.")
            return
        # The camera usually doesn't move, so the new clip gets the last crop box used.
        clip = Clip(start, end, crop=replace(self.project.last_crop) if self.project.last_crop else None)
        index = self.project.add_clip(clip)
        self.pending_start = None
        self.timeline.set_pending_start(None)
        self._refresh_clips(select=index)
        self._changed()
        message = f"Clip {index + 1} saved ({clip.length:.1f} seconds). Click its name in the list to rename it."
        if self.settings.nudges and clip.length > LONG_CLIP_SECONDS:
            message = f"Clip {index + 1} saved. It's {clip.length:.0f} seconds long: most strong Shorts are under 45 seconds."
        self.statusBar().showMessage(message)

    def _add_cut(self, start: float, end: float):
        """Long video: a dead stretch to leave out. Overlapping cuts are joined into one."""
        cut = Clip(start, end)
        for other in [c for c in self.project.cuts if c.start <= end and start <= c.end]:
            cut.start, cut.end = min(cut.start, other.start), max(cut.end, other.end)
            self.project.cuts.remove(other)
        self.project.cuts.append(cut)
        self.project.cuts.sort(key=lambda c: c.start)
        index = next(i for i, c in enumerate(self.project.cuts) if c is cut)
        self.pending_start = None
        self.timeline.set_pending_start(None)
        self._refresh_clips(select=index)
        self._changed()
        self.statusBar().showMessage(f"Cut {index + 1} marked ({format_time(cut.length)} left out). "
                                     f"Press P to watch the long video with the cuts skipped.")

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

    def escape(self):
        if self.preview_clip or self.long_preview:
            self.stop_preview()
        else:
            self.cancel_mark()

    def cancel_mark(self):
        if self.pending_start is not None:
            self.pending_start = None
            self.timeline.set_pending_start(None)
            self.statusBar().showMessage("Start mark cancelled.")

    # --- crop box and vertical preview ---
    def _show_selected_crop(self):
        index = self.clip_list.selected_index()
        if not self.project or index < 0 or self.long_mode:
            self.video.show_crop(None)
            return
        clip = self.project.clips[index]
        if clip.crop:
            self.video.show_crop(clip.crop, is_set=True)
        else:
            self.video.show_crop(cropmath.default_crop(self.video.aspect()), is_set=False)

    def _on_crop_changed(self, crop):
        index = self.clip_list.selected_index()
        if not self.project or index < 0 or self.long_mode:
            return
        self.project.clips[index].crop = crop
        self.project.last_crop = replace(crop)
        self._changed()
        self._refresh_tips()

    def toggle_preview(self):
        if self.preview_clip or self.long_preview:
            self.stop_preview()
            return
        if self.long_mode:
            self._start_long_preview()
            return
        index = self.clip_list.selected_index()
        if not self.project or index < 0:
            self.preview_btn.setChecked(False)
            self.statusBar().showMessage("Pick a clip in the list first, then press P to preview it.")
            return
        self.preview_clip = self.project.clips[index]
        self.preview_btn.setChecked(True)
        self.video.set_preview(True)
        self.seek(self.preview_clip.start)
        self.player.play()
        self.statusBar().showMessage(f"Previewing clip {index + 1} as a phone video. P or Esc goes back.")

    def _start_long_preview(self):
        if not self.project:
            return
        duration = self.player.duration() / 1000
        if duration and self.current_time() >= duration - 0.2:
            self.seek(0)  # at the end: watch from the start
        self.long_preview = True
        self.preview_btn.setChecked(True)
        self.player.play()
        self.statusBar().showMessage("Playing the long video with the cuts skipped. P or Esc stops.")

    def stop_preview(self):
        if self.long_preview:
            self.long_preview = False
            self.preview_btn.setChecked(False)
            self.player.pause()
            self.statusBar().showMessage("Stopped the long video preview.")
            return
        if self.preview_clip is None:
            return
        self.preview_clip = None
        self.preview_btn.setChecked(False)
        self.video.set_preview(False)
        self.player.pause()
        self.statusBar().showMessage("Back to the full picture.")

    # --- export and upload ---
    def export_folder(self) -> Path | None:
        if not self.project:
            return None
        return shorts_folder(self.settings, self.project.video_path)

    def export_all(self):
        if not self.project:
            return
        if self.long_mode:
            self.export_long()
            return
        clips = self.project.clips
        if not clips:
            self.statusBar().showMessage("There are no clips to export yet. Mark one with I and O first.")
            return
        self.stop_preview()
        self.player.pause()
        if self.settings.nudges and not self._confirm_export_tips():
            return
        self.save_now()
        _, crf, cq = QUALITIES[self.settings.quality]
        dialog = ExportDialog(self.project.video_path, clips, self.export_folder(), self, crf=crf, cq=cq)
        dialog.exec()
        for i, file in enumerate(dialog.files):  # the files come back in clip order
            clip = dialog.clips[i]
            self.library.add(file, clip.name or f"Clip {i + 1}", self.project.video_path, clip.length)
        if dialog.files:
            try:
                self.library.save()
            except OSError as e:
                QMessageBox.warning(self, "Lethal Cuts", f"The clips were exported, but the Post list couldn't be saved:\n{e}")
        if dialog.files and not dialog.error and not dialog.cancelled:
            self.statusBar().showMessage(f"{len(dialog.files)} clips exported to {self.export_folder()}. They're in the Post tab.")
        if dialog.go_to_post:
            self.show_post()

    def export_long(self):
        """Makes one widescreen video of everything that isn't cut out."""
        duration = self.player.duration() / 1000
        if duration <= 0:
            self.statusBar().showMessage("The video is still loading. Try again in a moment.")
            return
        self.stop_preview()
        self.player.pause()
        self.save_now()
        video = self.project.video_path
        cuts = [replace(c) for c in self.project.cuts]
        length = kept_length(cuts, duration)
        _, crf, cq = QUALITIES[self.settings.quality]
        folder = long_videos_folder(self.settings)
        worker = LongExportWorker(video, cuts, duration, folder, self.settings.long_size, crf, cq)
        dialog = ExportDialog(video, [], folder, self, worker=worker,
                              title=f"Making the long video ({format_time(length, tenths=False)})...")
        dialog.exec()
        for file in dialog.files:
            self.library.add(file, video.stem, video, length, kind="long")
        if dialog.files:
            try:
                self.library.save()
            except OSError as e:
                QMessageBox.warning(self, "Lethal Cuts", f"The video was made, but the Post list couldn't be saved:\n{e}")
            if not dialog.error and not dialog.cancelled:
                self.statusBar().showMessage(f"Long video saved in {folder}. It's in the Post tab.")
        if dialog.go_to_post:
            self.show_post()

    def _confirm_export_tips(self) -> bool:
        tips = [t for i in range(len(self.project.clips)) for t in self._clip_tips(i)]
        if not tips:
            return True
        shown = tips[:8] + ([f"...and {len(tips) - 8} more."] if len(tips) > 8 else [])
        box = QMessageBox(self)
        box.setWindowTitle("Before you export")
        box.setText("A few things you might want to fix first:")
        box.setInformativeText("\n\n".join(shown))
        export_btn = box.addButton("Export anyway", QMessageBox.AcceptRole)
        box.addButton("Go back", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is export_btn

    def show_post(self):
        self.tabs.setCurrentWidget(self.post_page)

    # --- fine-tuning ---
    def nudge(self, edge: str, delta: float):
        index = self.active_list().selected_index()
        if not self.project or index < 0:
            return
        clip = self.items()[index]
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
        if self.long_mode:
            self.project.cuts.sort(key=lambda c: c.start)
            index = next(i for i, c in enumerate(self.project.cuts) if c is clip)
        else:
            self.project.sort()
            index = self.project.index_of(clip)
        self._refresh_clips(select=index)
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

    def items(self) -> list[Clip]:
        """What the Editor is working on: Shorts clips, or a long video's cuts."""
        if not self.project:
            return []
        return self.project.cuts if self.long_mode else self.project.clips

    def active_list(self):
        return self.cut_list if self.long_mode else self.clip_list

    def set_mode(self, long: bool):
        """Switches the Editor between making Shorts and making a long video."""
        self.mode_group.button(1 if long else 0).setChecked(True)
        if long == self.long_mode:
            return
        self.stop_preview()
        self.cancel_mark()
        self.long_mode = long
        self.timeline.cut_style = long
        self.list_title.setText("Cuts" if long else "Clips")
        self.list_help.help_text = HELP["cuts" if long else "clips"]
        self.clip_list.setVisible(not long)
        self.cut_list.setVisible(long)
        self.long_note.setVisible(long)
        self.long_summary.setVisible(long)
        self.nudge_box.setTitle("Fine-tune the selected cut" if long else "Fine-tune the selected clip")
        self.delete_btn.setText("Delete cut" if long else "Delete clip")
        self.export_btn.setText("Export long video" if long else "Export all clips")
        self.export_help.help_text = HELP["export_long" if long else "export"]
        self.preview_help.help_text = HELP["preview_long" if long else "preview"]
        self._refresh_mode_labels()
        self._refresh_clips()
        self.statusBar().showMessage(
            "Making a long video: press I and O around the dead stretches to cut them out." if long
            else "Making Shorts: press I and O around the best moments.")

    def _refresh_mode_labels(self):
        key = self.settings.key("preview")
        self.preview_btn.setText(f"Preview long video  ({key})" if self.long_mode else f"Preview vertical  ({key})")
        self.preview_btn.setToolTip("Play the long video with the cuts skipped" if self.long_mode
                                    else "Play the selected clip exactly as the tall phone video will look")

    def _refresh_long_summary(self):
        duration = self.player.duration() / 1000
        if not self.project or duration <= 0:
            self.long_summary.setText("")
            return
        kept = kept_length(self.project.cuts, duration)
        self.long_summary.setText(f"Long video: {format_time(kept, tenths=False)}   "
                                  f"(cutting {format_time(duration - kept, tenths=False)} "
                                  f"of {format_time(duration, tenths=False)})")

    def _refresh_clips(self, select: int = -1):
        items = self.items()
        if self.long_mode:
            self.cut_list.set_cuts(items, select)
        else:
            self.clip_list.set_clips(items, select, self._thumb_for)
        self.timeline.set_clips(items, select)
        self.timeline.set_pending_start(self.pending_start)
        self._refresh_long_summary()
        self._update_enabled()

    def _select_clip(self, index: int):
        self.active_list().selectRow(index)

    def _on_list_selection(self, index: int):
        self.timeline.set_clips(self.items(), index)
        self._update_enabled()
        if self.preview_clip and index >= 0 and self.project.clips[index] is not self.preview_clip:
            # Picking another clip during preview previews that one instead.
            self.preview_clip = self.project.clips[index]
            self.seek(self.preview_clip.start)
            self.player.play()

    def _jump_to_clip(self, index: int):
        items = self.items()
        if 0 <= index < len(items):
            self.seek(items[index].start)

    def _on_name_changed(self, index: int, name: str):
        if self.project and 0 <= index < len(self.project.clips):
            self.project.clips[index].name = name
            self._changed()
            self._refresh_tips()

    def delete_selected(self):
        index = self.active_list().selected_index()
        if not self.project or index < 0:
            return
        self.stop_preview()
        self.last_deleted = (self.long_mode, self.items().pop(index))
        self._refresh_clips()
        self._changed()
        word = "Cut" if self.long_mode else "Clip"
        self.statusBar().showMessage(f"{word} {index + 1} deleted. Press Ctrl+Z to bring it back.")

    def undo_delete(self):
        if not self.project or self.last_deleted is None:
            return
        was_cut, item = self.last_deleted
        self.last_deleted = None
        self.set_mode(was_cut)
        if was_cut:
            self.project.cuts.append(item)
            self.project.cuts.sort(key=lambda c: c.start)
            index = next(i for i, c in enumerate(self.project.cuts) if c is item)
        else:
            index = self.project.add_clip(item)
        self._refresh_clips(select=index)
        self._changed()
        self.statusBar().showMessage(f"{'Cut' if was_cut else 'Clip'} {index + 1} restored.")

    def _update_enabled(self):
        has = self.project is not None
        for w in [self.play_btn, self.mark_in_btn, self.mark_out_btn, *self.speed_group.buttons()]:
            w.setEnabled(has)
        self.export_btn.setEnabled(has and (self.long_mode or bool(self.project.clips)))
        index = self.active_list().selected_index()
        selected = has and 0 <= index < len(self.items())
        self.delete_btn.setEnabled(selected)
        self.preview_btn.setEnabled(has if self.long_mode else selected)
        self._show_selected_crop()
        self.nudge_box.setEnabled(selected)
        if selected:
            clip = self.items()[index]
            self.start_value.setText(_precise(clip.start))
            self.end_value.setText(_precise(clip.end))
        else:
            self.start_value.setText("-")
            self.end_value.setText("-")
        self._refresh_tips()

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
        self.thumbs.stop()
        self.post_page.shutdown()
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
