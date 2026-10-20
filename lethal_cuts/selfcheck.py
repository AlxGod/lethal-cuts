"""A self-test: "Lethal Cuts.exe --check" confirms the program can play and export video on this PC.

It makes a tiny HEVC test video (like an iPhone's), plays it with the built-in
player, exports a 1-second vertical clip, and writes what it found to a text
file. Useful after installing, and when something isn't working.
Add --quiet to skip the pop-up at the end (for automated tests).
"""
from __future__ import annotations

import json
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__, export
from .project import Clip
from .settings import settings_path
from .tools import app_dir, ffmpeg_path, ffprobe_path, run_hidden


def default_log() -> Path:
    return Path(tempfile.gettempdir()) / "Lethal Cuts check.txt"


def run_check(log_path: Path, quiet: bool) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    lines = [f"Lethal Cuts {__version__} self-check, {time.strftime('%Y-%m-%d %H:%M')}",
             f"Windows: {platform.platform()}", f"Program folder: {app_dir()}", f"Settings file: {settings_path()}", ""]
    ok = True

    def report(passed: bool, text: str):
        nonlocal ok
        ok = ok and passed
        lines.append(("OK      " if passed else "PROBLEM ") + text)

    work = Path(tempfile.mkdtemp(prefix="lethalcuts-check-"))
    try:
        ffmpeg, ffprobe = ffmpeg_path(), ffprobe_path()
        report(bool(ffmpeg), f"FFmpeg found: {ffmpeg}")
        report(bool(ffprobe), f"FFprobe found: {ffprobe}")
        if not (ffmpeg and ffprobe):
            raise RuntimeError("FFmpeg is missing, so nothing else can be checked. Reinstalling Lethal Cuts should fix this.")
        version = run_hidden([ffmpeg, "-hide_banner", "-version"], timeout=30).stdout.decode(errors="replace").splitlines()
        lines.append(f"        {version[0] if version else 'unknown version'}")

        # A 3-second HEVC test video with sound, like a small iPhone recording
        video = work / "test.mov"
        made = run_hidden([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=3",
                           "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx265", "-preset", "ultrafast",
                           "-tag:v", "hvc1", "-c:a", "aac", str(video)], timeout=120)
        report(made.returncode == 0 and video.exists(), "Made a test HEVC video")

        info = export.probe(video)
        report((info.width, info.height, info.has_audio) == (1920, 1080, True), f"Read the video: {info.width}x{info.height}, {info.fps} fps")

        # The built-in player
        player, sink, audio = QMediaPlayer(), QVideoSink(), QAudioOutput()
        audio.setVolume(0)
        player.setAudioOutput(audio)
        player.setVideoSink(sink)
        player.setSource(QUrl.fromLocalFile(str(video)))
        player.play()
        deadline = time.time() + 15
        while time.time() < deadline and sink.videoSize().isEmpty():
            app.processEvents()
            time.sleep(0.02)
        size = sink.videoSize()
        report(not size.isEmpty(), f"Played the video in the built-in player ({size.width()}x{size.height()})")
        player.stop()
        player.setSource(QUrl())  # lets go of the file, or Windows won't let the test folder be deleted

        # A real 1-second export
        gpu = export.gpu_encoder_works()
        lines.append(f"        Exports will use the {'NVIDIA graphics card' if gpu else 'processor'}")
        from .export_dialog import ExportWorker  # needs the app object made above
        worker = ExportWorker(video, [Clip(0.5, 1.5, "check")], work / "out")
        result = []
        worker.finished.connect(lambda files, error, cancelled: result.append((files, error)))
        worker.run()
        files, error = result[0] if result else ([], "no result")
        good = bool(files) and not error
        if good:
            streams = json.loads(run_hidden([ffprobe, "-v", "error", "-show_streams", "-of", "json", files[0]], timeout=60).stdout)["streams"]
            v = next(s for s in streams if s["codec_type"] == "video")
            good = (v["width"], v["height"]) == (1080, 1920)
        report(good, "Exported a vertical 1080x1920 test clip" + (f": {error[-300:]}" if error else ""))

        # The same clip with text on it and a pause card (the overlay, freeze and countdown parts of the export)
        from . import overlays, pause_title
        from .project import Overlay
        clip = Clip(0.2, 2.2, "check overlays")
        text = Overlay("text", 0.5, 1.5, text="Check *this*", anim_in="type")
        pause = pause_title.new_pause(1.0)
        pause.end = pause.start + 2
        timed = overlays.times_in_clip([text, pause], clip)
        placed = overlays.prepare(timed, 1080, 1920, work / "pictures")
        worker = ExportWorker(video, [clip], work / "out2", placed=[placed],
                              freezes=[overlays.freezes_in_clip([text, pause], clip)])
        result = []
        worker.finished.connect(lambda files, error, cancelled: result.append((files, error)))
        worker.run()
        files, error = result[0] if result else ([], "no result")
        length = 0.0
        if files and not error:
            streams = json.loads(run_hidden([ffprobe, "-v", "error", "-show_streams", "-of", "json", files[0]], timeout=60).stdout)["streams"]
            length = float(next(s for s in streams if s["codec_type"] == "video")["duration"])
        report(abs(length - 4.0) < 0.1, "Exported a clip with text and a pause card" + (f": {error[-300:]}" if error else ""))

        # The speech engine (captions and "clip that"): it loads, and its voice detector runs
        try:
            import numpy as np
            from faster_whisper.vad import get_speech_timestamps
            import ctranslate2
            get_speech_timestamps(np.zeros(16000, dtype=np.float32))
            report(True, f"Speech engine loads (CTranslate2 {ctranslate2.__version__})")
        except Exception as e:
            report(False, f"Speech engine didn't load: {e}")
        from . import speech
        from .settings import load as load_settings
        model = load_settings().speech_model
        lines.append(f"        Speech model {model}: {'downloaded' if speech.model_installed(model) else 'not downloaded yet'}; "
                     f"graphics card pack: {'downloaded' if speech.gpu_pack_installed() else 'not downloaded'}")
    except Exception as e:
        report(False, str(e))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    lines += ["", "Everything works." if ok else "Something isn't working. Send this file to whoever set up Lethal Cuts."]
    text = "\n".join(lines)
    try:
        log_path.write_text(text, encoding="utf-8")
    except OSError:
        pass
    if sys.stdout:
        print(text)
    if not quiet:
        box = QMessageBox(QMessageBox.Information if ok else QMessageBox.Warning, "Lethal Cuts check",
                          ("Everything works." if ok else "Something isn't working.") + f"\n\nDetails saved to:\n{log_path}")
        box.setDetailedText(text)
        box.exec()
    return 0 if ok else 1
