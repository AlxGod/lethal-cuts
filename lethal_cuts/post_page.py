"""The Post tab: every exported Short in one place, to watch and post one at a time."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QFile, QSize, QSizeF, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFrame, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QSlider, QStackedWidget, QStyle, QVBoxLayout, QWidget)

from .help import HELP, HelpButton
from .library import SITES, Library, Short, nice_date
from .project import format_time
from .thumbnails import _Job, _Signals
from .tools import ffmpeg_path

ICON = QSize(135, 240)            # list pictures, phone-shaped
PLAYER = QSize(270, 480)          # the tall player


def show_in_folder(path: Path) -> None:
    """Opens the clip's folder with the clip already highlighted, ready to drag."""
    subprocess.Popen(f'explorer /select,"{path}"')


class _TallVideo(QGraphicsView):
    """The phone-shaped player picture (drawn the same way as the Editor's). Clicking it plays or pauses."""

    def __init__(self, on_click):
        super().__init__()
        self.on_click = on_click
        self.setFixedSize(PLAYER)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QBrush(QColor("#000000")))
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.NoFocus)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setToolTip("Click to play or pause")
        self.item = QGraphicsVideoItem()
        self.item.setAspectRatioMode(Qt.KeepAspectRatio)
        self.scene().addItem(self.item)
        self._fit()

    def _fit(self):
        size = self.viewport().size()
        self.scene().setSceneRect(0, 0, size.width(), size.height())
        self.item.setSize(QSizeF(size))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def mousePressEvent(self, event):
        self.on_click()


class PostPage(QWidget):
    open_folder = Signal()
    change_folder = Signal()

    def __init__(self, library: Library, parent=None):
        super().__init__(parent)
        self.library = library
        self.current: Short | None = None
        self.showing_posted = False
        self.pictures: dict[str, QImage] = {}
        self.ffmpeg = ffmpeg_path()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._signals = _Signals()
        self._signals.done.connect(self._on_picture)
        self._asked: set[str] = set()

        title = QLabel("Post")
        title.setObjectName("panelTitle")
        self.filter = QButtonGroup(self)
        self.new_btn = QPushButton("New")
        self.posted_btn = QPushButton("Posted")
        for i, b in enumerate((self.new_btn, self.posted_btn)):
            b.setObjectName("speedButton")
            b.setCheckable(True)
            self.filter.addButton(b, i)
        self.new_btn.setToolTip("Clips you haven't posted anywhere yet")
        self.posted_btn.setToolTip("Clips you've marked as posted on YouTube or TikTok")
        self.new_btn.setChecked(True)
        self.filter.idClicked.connect(self._on_filter)
        top = QHBoxLayout()
        top.addWidget(title)
        top.addSpacing(16)
        top.addWidget(self.new_btn)
        top.addWidget(self.posted_btn)
        top.addStretch(1)
        self.folder_label = QLabel()
        self.folder_label.setObjectName("dimLabel")
        self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        open_btn = QPushButton("Open folder")
        open_btn.setToolTip("Open the folder your videos are saved in")
        open_btn.clicked.connect(self.open_folder.emit)
        change_btn = QPushButton("Change...")
        change_btn.setToolTip("Save new videos somewhere else (videos already made stay where they are)")
        change_btn.clicked.connect(self.change_folder.emit)
        top.addWidget(self.folder_label)
        top.addWidget(open_btn)
        top.addWidget(change_btn)
        top.addSpacing(8)
        top.addWidget(HelpButton(HELP["post"]))

        # The clip pictures, or a note when there are none
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(ICON)
        self.list.setGridSize(QSize(ICON.width() + 36, ICON.height() + 64))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setWordWrap(True)
        self.list.setSpacing(4)
        self.list.currentItemChanged.connect(self._on_pick)
        self.list.itemClicked.connect(lambda item: self.current and item.data(Qt.UserRole) == self.current.file and self.toggle_play())
        self.empty = QLabel()
        self.empty.setObjectName("dimLabel")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.list)
        self.stack.addWidget(self.empty)

        # The player and what to do with the picked clip
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = _TallVideo(self.toggle_play)
        self.player.setVideoOutput(self.video.item)
        self.play_btn = QPushButton()
        self.play_btn.clicked.connect(self.toggle_play)
        self.seek_bar = QSlider(Qt.Horizontal)
        self.seek_bar.sliderMoved.connect(lambda ms: self.player.setPosition(ms))
        self.time_label = QLabel("0:00.0")
        self.time_label.setObjectName("timeLabel")
        self.player.durationChanged.connect(lambda ms: self.seek_bar.setRange(0, ms))
        self.player.positionChanged.connect(self._on_position)
        self.player.playbackStateChanged.connect(lambda _: self._refresh_play_button())
        self.player.mediaStatusChanged.connect(self._on_media_status)
        controls = QHBoxLayout()
        controls.addWidget(self.play_btn)
        controls.addWidget(self.seek_bar, 1)
        controls.addWidget(self.time_label)

        self.name_label = QLabel()
        self.name_label.setObjectName("panelTitle")
        self.name_label.setWordWrap(True)
        self.detail = QLabel()
        self.detail.setObjectName("dimLabel")
        self.detail.setWordWrap(True)

        self.post_buttons: dict[str, QPushButton] = {}
        self.posted_boxes: dict[str, QCheckBox] = {}
        sites = QVBoxLayout()
        for key, (site, _) in SITES.items():
            btn = QPushButton(f"Post to {site}")
            btn.setObjectName("exportButton")
            btn.setToolTip(f"Opens {site}'s upload page and shows this clip in its folder, ready to drag in. "
                           "Its name is copied, so you can paste it as the title.")
            btn.clicked.connect(lambda _=False, k=key: self.post_to(k))
            box = QCheckBox(f"Posted on {site}")
            box.setToolTip(f"Tick this once it's up on {site}. Posted clips move to the Posted list.")
            box.toggled.connect(lambda on, k=key: self._on_posted(k, on))
            row = QHBoxLayout()
            row.addWidget(btn, 1)
            row.addWidget(box)
            sites.addLayout(row)
            self.post_buttons[key], self.posted_boxes[key] = btn, box
        self.note = QLabel()
        self.note.setObjectName("dimLabel")
        self.note.setWordWrap(True)
        self.folder_btn = QPushButton("Show in folder")
        self.folder_btn.clicked.connect(lambda: self.current and show_in_folder(self.current.path))
        self.delete_btn = QPushButton("Delete clip")
        self.delete_btn.setToolTip("Moves the video file to the Recycle Bin")
        self.delete_btn.clicked.connect(self.delete_current)
        bottom = QHBoxLayout()
        bottom.addWidget(self.folder_btn)
        bottom.addStretch(1)
        bottom.addWidget(self.delete_btn)

        side = QWidget()
        side.setFixedWidth(PLAYER.width() + 150)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(12, 0, 0, 0)
        side_layout.addWidget(self.video, 0, Qt.AlignHCenter)
        side_layout.addLayout(controls)
        side_layout.addSpacing(6)
        side_layout.addWidget(self.name_label)
        side_layout.addWidget(self.detail)
        side_layout.addSpacing(6)
        side_layout.addLayout(sites)
        side_layout.addWidget(self.note)
        side_layout.addStretch(1)
        side_layout.addLayout(bottom)
        self.side = side

        body = QHBoxLayout()
        body.addWidget(self.stack, 1)
        body.addWidget(side)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 10)
        layout.addLayout(top)
        layout.addLayout(body, 1)
        self._refresh_play_button()
        self.refresh()

    def show_folder(self, folder: Path):
        self.folder_label.setText(f"Saved in: {folder}")

    # --- the list ---
    def refresh(self):
        """Rebuilds the list from the library (after an export, or when the tab is opened)."""
        shorts = self.library.existing()
        new = [s for s in shorts if not s.is_posted]
        posted = [s for s in shorts if s.is_posted]
        self.new_btn.setText(f"New ({len(new)})")
        self.posted_btn.setText(f"Posted ({len(posted)})")
        shown = posted if self.showing_posted else new
        self.list.blockSignals(True)
        self.list.clear()
        for short in shown:
            item = QListWidgetItem(self._icon(short), self._caption(short))
            item.setData(Qt.UserRole, short.file)
            item.setToolTip(short.file)
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self.list.addItem(item)
            if self.current is not None and short.file == self.current.file:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if not shown:
            nothing = ("No clips yet.\n\nMark some moments in the Editor tab and click Export all clips. "
                       "They'll show up here, ready to watch and post one at a time.")
            if self.showing_posted:
                text = ("Nothing posted yet. Tick \"Posted on YouTube\" or \"Posted on TikTok\" once a clip is up."
                        if shorts else nothing)
            else:
                text = "Everything you've exported has been posted. Nice!" if posted else nothing
            self.empty.setText(text)
            self.stack.setCurrentWidget(self.empty)
        else:
            self.stack.setCurrentWidget(self.list)
        if self.current is not None and not self.current.path.exists():
            self.show_short(None)
        elif self.current is None and shown:
            self.list.setCurrentRow(0)  # picks the newest clip, without playing it
        elif self.current is None:
            self.show_short(None)

    def _caption(self, short: Short) -> str:
        sites = ", ".join(SITES[k][0] for k in SITES if k in short.posted)
        return f"{short.name}\n{format_time(short.length, tenths=False)}" + (f"  •  {sites}" if sites else "")

    def _icon(self, short: Short) -> QIcon:
        image = self.pictures.get(short.file)
        if image is None:
            self._ask_picture(short)
            blank = QPixmap(ICON)
            blank.fill(QColor("#1d1828"))
            return QIcon(blank)
        return QIcon(QPixmap.fromImage(image).scaled(ICON, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _ask_picture(self, short: Short):
        if self.ffmpeg and short.file not in self._asked:
            self._asked.add(short.file)
            self.pool.start(_Job(self.ffmpeg, short.file, min(1.0, short.length / 2), self._signals))

    def _on_picture(self, file: str, seconds: float, image: QImage):
        self.pictures[file] = image
        for row in range(self.list.count()):
            item = self.list.item(row)
            short = self.library.find(item.data(Qt.UserRole))
            if short and short.file == file:
                item.setIcon(self._icon(short))

    def _on_filter(self, index: int):
        self.showing_posted = index == 1
        self.stop()
        self.current = None
        self.refresh()

    def _on_pick(self, item, _previous=None):
        self.show_short(self.library.find(item.data(Qt.UserRole)) if item else None)

    # --- the picked clip ---
    def show_short(self, short: Short | None):
        self.current = short
        self.stop()
        has = short is not None
        for w in (self.play_btn, self.seek_bar, self.folder_btn, self.delete_btn, *self.post_buttons.values(),
                  *self.posted_boxes.values()):
            w.setEnabled(has)
        self.note.clear()
        if not has:
            self.name_label.setText("No clip picked")
            self.detail.setText("Click a clip on the left to watch it here.")
            for box in self.posted_boxes.values():
                box.blockSignals(True)
                box.setChecked(False)
                box.blockSignals(False)
            return
        self.name_label.setText(short.name)
        bits = [f"{format_time(short.length, tenths=False)} long"]
        if short.video:
            bits.append(f"from {Path(short.video).name}")
        if short.exported:
            bits.append(f"exported {nice_date(short.exported)}")
        self.detail.setText("  •  ".join(bits))
        self._refresh_posted()
        self.player.setSource(QUrl.fromLocalFile(short.file))

    def _refresh_posted(self):
        for key, box in self.posted_boxes.items():
            site = SITES[key][0]
            when = self.current.posted.get(key) if self.current else None
            box.blockSignals(True)
            box.setChecked(bool(when))
            box.setText(f"Posted on {site} ({nice_date(when)})" if when else f"Posted on {site}")
            box.blockSignals(False)

    def _on_posted(self, key: str, on: bool):
        if not self.current:
            return
        try:
            self.library.set_posted(self.current, key, on)
        except OSError as e:
            QMessageBox.warning(self, "Lethal Cuts", f"Couldn't save that:\n{e}")
            return
        self._refresh_posted()
        short = self.current
        self.refresh()  # it may move between New and Posted; it stays shown on the right
        self.current = short
        self._refresh_posted()

    def post_to(self, key: str):
        if not self.current:
            return
        site, page = SITES[key]
        self.player.pause()
        QGuiApplication.clipboard().setText(self.current.name)
        QDesktopServices.openUrl(QUrl(page))
        show_in_folder(self.current.path)
        self.note.setText(f"{site} is opening in your browser, and the clip is highlighted in its folder: drag it in. "
                          f"Its name is copied, so you can paste it as the title (Ctrl+V). "
                          f"Tick \"Posted on {site}\" once it's up.")

    def delete_current(self):
        short = self.current
        if not short:
            return
        answer = QMessageBox.question(self, "Delete clip",
                                      f"Move \"{short.name}\" to the Recycle Bin?\n\nThe clip in the Editor isn't touched, "
                                      "so you can export it again any time.")
        if answer != QMessageBox.Yes:
            return
        self.release()  # the player keeps the file open otherwise, and Windows won't move it
        if short.path.exists() and not QFile.moveToTrash(str(short.path)):
            QMessageBox.warning(self, "Lethal Cuts", f"Couldn't move this file to the Recycle Bin:\n{short.file}")
            self.player.setSource(QUrl.fromLocalFile(short.file))
            return
        self.library.remove(short)
        self.current = None
        self.refresh()

    # --- playback ---
    def _on_media_status(self, status):
        if status == QMediaPlayer.LoadedMedia and self.player.playbackState() == QMediaPlayer.StoppedState:
            # A paused player shows the first frame; a stopped one shows nothing. Pausing inside
            # this signal crashes Qt's player, so it's done just after.
            QTimer.singleShot(0, self._show_first_frame)

    def _show_first_frame(self):
        if self.current and self.player.playbackState() == QMediaPlayer.StoppedState:
            self.player.pause()
            self.player.setPosition(0)

    def toggle_play(self):
        if not self.current:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            if self.player.duration() and self.player.position() >= self.player.duration() - 100:
                self.player.setPosition(0)  # watch it again
            self.player.play()

    def stop(self):
        self.player.stop()

    def release(self):
        """Stops and lets go of the video file."""
        self.player.stop()
        self.player.setSource(QUrl())

    def _on_position(self, ms: int):
        if not self.seek_bar.isSliderDown():
            self.seek_bar.setValue(ms)
        self.time_label.setText(format_time(ms / 1000))

    def _refresh_play_button(self):
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause if playing else QStyle.SP_MediaPlay))
        self.play_btn.setText("Pause" if playing else "Play")

    def shutdown(self):
        self.release()
        self.pool.clear()
        self.pool.waitForDone(3000)
