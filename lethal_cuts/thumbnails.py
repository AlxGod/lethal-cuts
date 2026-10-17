"""Small preview pictures for the clip list, made by FFmpeg in the background
so the video never stutters while they're being made."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from .tools import ffmpeg_path, run_hidden

THUMB_WIDTH = 192  # drawn at half size, so it stays sharp on high-resolution screens


def thumbnail_time(start: float, length: float) -> float:
    """A moment just after the clip starts, past any blur from pressing I."""
    return start + min(1.0, length / 2)


class _Signals(QObject):
    done = Signal(str, float, QImage)  # video path, seconds, picture


class _Job(QRunnable):
    def __init__(self, ffmpeg: str, video: str, seconds: float, signals: _Signals):
        super().__init__()
        self.ffmpeg, self.video, self.seconds, self.signals = ffmpeg, video, seconds, signals

    def run(self):
        args = [
            self.ffmpeg, "-v", "error", "-ss", f"{self.seconds:.3f}", "-i", self.video,
            "-frames:v", "1", "-vf", f"scale={THUMB_WIDTH}:-2", "-f", "image2pipe", "-c:v", "png", "-",
        ]
        try:
            result = run_hidden(args, timeout=30)
        except Exception:
            return
        image = QImage()
        if result.returncode == 0 and image.loadFromData(result.stdout, "PNG"):
            try:
                self.signals.done.emit(self.video, self.seconds, image)
            except RuntimeError:
                pass  # the window closed while this picture was being made


class ThumbnailMaker(QObject):
    """Ask for a picture with request(); ready() fires when it's made."""
    ready = Signal(float, QImage)  # seconds, picture

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ffmpeg = ffmpeg_path()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.cache: dict[float, QImage] = {}
        self.video: str | None = None
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)
        self._waiting: set[float] = set()

    def set_video(self, video: Path) -> None:
        self.video = str(video)
        self.cache.clear()
        self._waiting.clear()

    def get(self, seconds: float) -> QImage | None:
        return self.cache.get(round(seconds, 2))

    def request_only(self, times: list[float]) -> None:
        """Makes pictures for these moments, dropping any older requests not started yet
        (for example the in-between spots while a nudge button is held down)."""
        self.pool.clear()
        self._waiting.clear()
        for seconds in times:
            key = round(seconds, 2)
            if not self.ffmpeg or not self.video or key in self.cache or key in self._waiting:
                continue
            self._waiting.add(key)
            self.pool.start(_Job(self.ffmpeg, self.video, key, self._signals))

    def stop(self) -> None:
        """Drops waiting requests and lets running ones finish (used when closing)."""
        self.pool.clear()
        self.pool.waitForDone(3000)

    def _on_done(self, video: str, seconds: float, image: QImage):
        if video != self.video:
            return  # a different video was opened while this one was being made
        self._waiting.discard(seconds)
        self.cache[seconds] = image
        self.ready.emit(seconds, image)
