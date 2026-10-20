"""The Speech window: download the speech model, listen to a video, and the optional graphics card pack."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)

from . import settings as settings_mod
from . import speech
from .settings import Settings


class SpeechDialog(QDialog):
    listen_now = Signal()  # "listen to this video now" (the main window runs it)

    def __init__(self, s: Settings, has_video: bool, listened: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Speech: captions and \"clip that\"")
        self.setMinimumWidth(540)
        self.s = s
        self._thread: QThread | None = None
        self._job: speech.Download | None = None
        intro = QLabel(
            "Lethal Cuts listens to the game (on this PC, nothing is uploaded) and writes down every word with its "
            "time. That gives Shorts their captions, and every time someone says \"clip that\" it puts a pink flag "
            "on the timeline and keeps those words out of the video.\n\n"
            "It needs a speech model, downloaded once. Each video is then listened to in the background when you "
            "open it: about half an hour for a 3-hour game on the processor, much less with the graphics card pack.")
        intro.setWordWrap(True)
        self.model = QComboBox()
        for key, (label, _) in speech.MODELS.items():
            self.model.addItem(label, key)
        self.model.setCurrentIndex(max(self.model.findData(s.speech_model), 0))
        self.model.currentIndexChanged.connect(self._on_model)
        self.download_btn = QPushButton()
        self.download_btn.clicked.connect(self.download_model)
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Speech model"))
        model_row.addWidget(self.model, 1)
        model_row.addWidget(self.download_btn)
        self.auto = QCheckBox("Listen to each video I open, in the background")
        self.auto.setChecked(s.auto_listen)
        self.auto.toggled.connect(self._on_auto)
        self.listen_btn = QPushButton("Listen to this video now" if not listened else "Listen to this video again")
        self.listen_btn.setObjectName("exportButton")
        self.listen_btn.setEnabled(has_video)
        self.listen_btn.clicked.connect(self._listen)
        gpu_title = QLabel("Graphics card (NVIDIA only)")
        gpu_title.setObjectName("panelTitle")
        self.gpu_note = QLabel()
        self.gpu_note.setWordWrap(True)
        self.gpu_note.setObjectName("dimLabel")
        self.gpu_btn = QPushButton(f"Download the graphics card pack ({speech.GPU_SIZE_MB / 1000:.1f} GB)")
        self.gpu_btn.setToolTip("NVIDIA's own libraries for running the speech model on the graphics card")
        self.gpu_btn.clicked.connect(self.download_gpu)
        self.use_gpu = QCheckBox("Use the graphics card for listening")
        self.use_gpu.setChecked(s.speech_gpu)
        self.use_gpu.toggled.connect(self._on_use_gpu)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("dimLabel")
        self.cancel_btn = QPushButton("Stop download")
        self.cancel_btn.hide()
        self.cancel_btn.clicked.connect(self._cancel)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.cancel_btn)
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(model_row)
        layout.addWidget(self.auto)
        layout.addWidget(self.listen_btn, 0, Qt.AlignLeft)
        layout.addSpacing(8)
        layout.addWidget(gpu_title)
        layout.addWidget(self.gpu_note)
        gpu_row = QHBoxLayout()
        gpu_row.addWidget(self.gpu_btn)
        gpu_row.addWidget(self.use_gpu)
        gpu_row.addStretch(1)
        layout.addLayout(gpu_row)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addLayout(bottom)
        self._refresh()

    def _save(self):
        try:
            settings_mod.save(self.s)
        except OSError:
            pass

    def _refresh(self):
        name = self.model.currentData()
        installed = speech.model_installed(name)
        busy = self._thread is not None
        self.download_btn.setText("Downloaded" if installed else f"Download ({speech.MODELS[name][1]} MB)")
        self.download_btn.setEnabled(not installed and not busy)
        self.listen_btn.setVisible(installed)
        gpu = speech.gpu_pack_installed()
        self.gpu_btn.setVisible(not gpu)
        self.gpu_btn.setEnabled(not busy)
        self.use_gpu.setVisible(gpu)
        self.gpu_note.setText(
            "The graphics card pack is downloaded. If the card can't run it, listening uses the processor instead."
            if gpu else
            "Optional: on an NVIDIA graphics card, listening is several times faster. This downloads NVIDIA's own "
            "libraries once. If the card turns out not to work with them, the processor is used as usual.")

    def _on_model(self):
        self.s.speech_model = self.model.currentData()
        self._save()
        self._refresh()

    def _on_auto(self, on: bool):
        self.s.auto_listen = on
        self._save()

    def _on_use_gpu(self, on: bool):
        self.s.speech_gpu = on
        self._save()

    def _listen(self):
        self.listen_now.emit()
        self.status.setText("Listening in the background: the progress shows at the bottom of the window. "
                            "You can close this and keep editing.")

    def download_model(self):
        self._start(speech.Download(self.model.currentData()))

    def download_gpu(self):
        self._start(speech.Download("gpu"))

    def _start(self, job: speech.Download):
        if self._thread:
            return
        self._job, self._kind = job, job.what
        self._thread = QThread(self)
        job.moveToThread(self._thread)
        self._thread.started.connect(job.run)
        job.progress.connect(self._on_progress)
        job.finished.connect(self._on_finished)
        job.finished.connect(self._thread.quit)
        self.bar.show()
        self.bar.setValue(0)
        self.cancel_btn.show()
        self.status.setText("Starting the download...")
        self._thread.start()
        self._refresh()

    def _on_progress(self, fraction: float, text: str):
        self.bar.setValue(int(fraction * 1000))
        self.status.setText(text)

    def _on_finished(self, error: str):
        self._thread.wait(5000)
        self._thread, self._job = None, None
        self.bar.hide()
        self.cancel_btn.hide()
        if error:
            self.status.setText(error)
        elif self._kind == "gpu":
            self.status.setText("Graphics card pack downloaded. The next listen uses the graphics card if it can.")
        else:
            self.status.setText("Speech model downloaded." + (" Each video you open is now listened to in the "
                                                              "background." if self.s.auto_listen else ""))
        self._refresh()

    def _cancel(self):
        if self._job:
            self._job.cancel()

    def done(self, result):
        if self._job:
            self._job.cancel()
        if self._thread:
            self._thread.quit()
            self._thread.wait(10000)
        super().done(result)
