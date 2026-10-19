"""The export window: runs the batch export in the background with a progress bar."""
from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from . import export
from .project import Clip


class ExportWorker(QObject):
    progress = Signal(float, str)        # overall 0..1, what's happening
    finished = Signal(list, str, bool)   # finished file paths, error message, cancelled

    def __init__(self, video: Path, clips: list[Clip], folder: Path, crf: int = export.X264_QUALITY,
                 cq: int = export.NVENC_QUALITY, placed: list[list] | None = None, freezes: list[list] | None = None):
        super().__init__()
        self.video, self.clips, self.folder = video, clips, folder
        self.placed = placed or [[] for _ in clips]  # each clip's overlays (overlays.Placed)
        self.freezes = freezes or [[] for _ in clips]  # each clip's pause cards: (seconds in, seconds long)
        self.crf, self.cq = crf, cq
        self.encoder_label = ""
        self._cancelled = False
        self._proc = None

    def cancel(self):
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.kill()

    def _register(self, proc):
        self._proc = proc
        if self._cancelled:
            proc.kill()

    def run(self):
        done_files: list[str] = []
        try:
            info = export.probe(self.video)
            self.folder.mkdir(parents=True, exist_ok=True)
            gpu = export.gpu_encoder_works()
            total = sum(c.length for c in self.clips) or 1.0
            done = 0.0
            for i, clip in enumerate(self.clips):
                if self._cancelled:
                    break
                label = f"Clip {i + 1} of {len(self.clips)}" + (f": {clip.name}" if clip.name else "")
                self.progress.emit(done / total, f"{label}  (measuring volume)")
                measured = export.measure_loudness(self.video, clip, lambda: self._cancelled) if info.has_audio else None
                final = self.folder / export.output_name(i + 1, clip)
                temp = final.with_name(final.stem + ".partial.mp4")  # never mistaken for a finished clip
                length = clip.length + sum(s for _, s in self.freezes[i])
                report = lambda p, d=done, c=clip, l=label: self.progress.emit((d + p * c.length) / total, l)
                code, log = self._encode(clip, info, measured, temp, gpu, report, self.placed[i], self.freezes[i], length)
                if code != 0 and gpu and not self._cancelled:
                    gpu = False  # the graphics card failed: switch to the processor for the rest
                    code, log = self._encode(clip, info, measured, temp, gpu, report, self.placed[i], self.freezes[i],
                                             length)
                if self._cancelled:
                    break
                if code != 0:
                    raise export.ExportError(f"FFmpeg stopped on clip {i + 1}:\n\n{log}")
                os.replace(temp, final)
                done_files.append(str(final))
                done += clip.length
            if not self._cancelled:
                self.progress.emit(1.0, "Done")
            self.finished.emit(done_files, "", self._cancelled)
        except Exception as e:  # shown to the user rather than crashing the program
            self.finished.emit(done_files, str(e), self._cancelled)
        finally:
            for leftover in self.folder.glob("*.partial.mp4") if self.folder.exists() else []:
                try:
                    leftover.unlink()
                except OSError:
                    pass

    def _encode(self, clip, info, measured, out, gpu, report, placed=None, freezes=None, length=None):
        self.encoder_label = "graphics card" if gpu else "processor"
        args = export.encode_args(self.video, clip, info, measured, out, gpu, self.crf, self.cq, placed, freezes)
        return export.run_encode(args, length or clip.length, report, self._register)


class ExportDialog(QDialog):
    def __init__(self, video: Path, clips: list[Clip], folder: Path, parent=None,
                 crf: int = export.X264_QUALITY, cq: int = export.NVENC_QUALITY, worker=None, title: str = "",
                 placed: list[list] | None = None, freezes: list[list] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Exporting clips")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.folder = folder
        self.files: list[str] = []
        self.error = ""
        self.cancelled = False
        self.go_to_post = False
        self._started = time.monotonic()

        self.long = worker is not None
        self.title = QLabel(title or f"Making {len(clips)} vertical clip{'s' if len(clips) != 1 else ''}...")
        self.title.setObjectName("panelTitle")
        self.step = QLabel("Starting")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.detail = QLabel("")
        self.detail.setObjectName("dimLabel")
        self.detail.setWordWrap(True)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel)
        self.folder_btn = QPushButton("Open folder")
        self.folder_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder))))
        self.post_btn = QPushButton("See them in the Post tab")
        self.post_btn.setObjectName("exportButton")
        self.post_btn.setToolTip("Watch the finished clips and post them one at a time")
        self.post_btn.clicked.connect(self._go_to_post)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        for b in (self.folder_btn, self.post_btn, self.close_btn):
            b.hide()

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for b in (self.cancel_btn, self.folder_btn, self.post_btn, self.close_btn):
            buttons.addWidget(b)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.step)
        layout.addWidget(self.bar)
        layout.addWidget(self.detail)
        layout.addSpacing(8)
        layout.addLayout(buttons)

        # Each clip is its own copy, so nothing changes under the export while it runs.
        self.clips = [replace(c) for c in clips]
        self.worker = worker or ExportWorker(video, self.clips, folder, crf, cq, placed, freezes)
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.start()

    def _on_progress(self, fraction: float, text: str):
        self.bar.setValue(int(fraction * 1000))
        self.step.setText(text)
        elapsed = time.monotonic() - self._started
        parts = [f"Using the {self.worker.encoder_label}"] if self.worker.encoder_label else []
        if fraction > 0.03:
            left = elapsed / fraction - elapsed
            parts.append(f"about {int(left // 60)} min {int(left % 60):02d} s left" if left >= 60 else f"about {int(left)} s left")
        self.detail.setText("  -  ".join(parts))

    def _on_finished(self, files: list, error: str, cancelled: bool):
        self.files, self.error, self.cancelled = files, error, cancelled
        self.cancel_btn.hide()
        self.close_btn.show()
        if files:
            self.folder_btn.show()
            self.post_btn.show()
        n = len(files)
        if error:
            self.title.setText("Export stopped")
            self.step.setText(f"{n} clip{'s' if n != 1 else ''} finished before the problem." if n else "No clips were finished.")
            self.detail.setText(error)
        elif cancelled:
            self.title.setText("Export cancelled")
            self.step.setText(f"{n} clip{'s' if n != 1 else ''} finished before you cancelled.")
        else:
            self.title.setText("Long video ready to post" if self.long else f"{n} clip{'s' if n != 1 else ''} ready to post")
            self.step.setText(f"Saved in {self.folder}")
            self.detail.setText("It's waiting in the Post tab." if self.long else
                                "They're waiting in the Post tab, where you can watch them and post one at a time.")

    def _go_to_post(self):
        self.go_to_post = True
        self.accept()

    def _cancel(self):
        self.cancel_btn.setEnabled(False)
        self.step.setText("Cancelling...")
        self.worker.cancel()

    def reject(self):
        # Closing the window (or pressing Esc) while exporting cancels first.
        if self.thread.isRunning():
            self._cancel()
            return
        super().reject()

    def done(self, result):
        if self.thread.isRunning():
            self.worker.cancel()
            self.thread.quit()
            self.thread.wait(10000)
        super().done(result)
