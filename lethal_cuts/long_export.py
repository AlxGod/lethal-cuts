"""Making a long (normal widescreen) video: the whole recording with the marked dead stretches cut out.

FFmpeg reads the recording once and keeps only the frames and sound outside the cuts
(select/aselect), so even a 2-hour game needs no extra memory or temporary files.
The volume is evened out over the whole video, the same way as the Shorts.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import export
from .folders import safe_name
from .project import Clip, format_time
from .tools import ffmpeg_path, run_hidden

MIN_PIECE = 0.05  # seconds: slivers shorter than this between cuts are dropped


def merge_cuts(cuts: list[Clip]) -> list[tuple[float, float]]:
    """Overlapping or touching cuts become one."""
    merged: list[list[float]] = []
    for c in sorted(cuts, key=lambda c: c.start):
        if merged and c.start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], c.end)
        else:
            merged.append([c.start, c.end])
    return [(a, b) for a, b in merged]


def kept_pieces(cuts: list[Clip], duration: float) -> list[tuple[float, float]]:
    """The parts of the video that stay: everything between the cuts."""
    pieces, at = [], 0.0
    for a, b in merge_cuts(cuts):
        if a - at >= MIN_PIECE:
            pieces.append((at, min(a, duration)))
        at = max(at, b)
    if duration - at >= MIN_PIECE:
        pieces.append((at, duration))
    return [(a, b) for a, b in pieces if b - a >= MIN_PIECE]


def kept_length(cuts: list[Clip], duration: float) -> float:
    return sum(b - a for a, b in kept_pieces(cuts, duration))


def snap(pieces: list[tuple[float, float]], fps: int) -> list[tuple[float, float]]:
    """Moves every cut onto a frame boundary. The sound is cut in frame-sized chunks on the same
    boundaries, so picture and sound always lose exactly the same time and never drift apart,
    however many cuts there are."""
    snapped = [(round(a * fps) / fps, round(b * fps) / fps) for a, b in pieces]
    return [(a, b) for a, b in snapped if b > a]


def keep_expression(pieces: list[tuple[float, float]], fps: int) -> str:
    """True for every frame that stays: frames sit at t = n/fps, so each test is half a frame early to be safe."""
    half = 0.5 / fps
    return "+".join(f"gte(t,{a - half:.6f})*lt(t,{b - half:.6f})" for a, b in pieces)


def output_height(info: export.VideoInfo, size: str) -> int:
    """'1080' makes a 1080p video (faster to make and upload); 'source' keeps the recording's size."""
    return info.height if size == "source" or info.height <= 1080 else 1080


def video_filter(info: export.VideoInfo, pieces, size: str) -> str:
    steps = [f"fps={info.fps}", f"select='{keep_expression(pieces, info.fps)}'", "setpts=N/FRAME_RATE/TB"]
    height = output_height(info, size)
    if height != info.height:
        steps.append(f"scale=-2:{height}:flags=lanczos")
    if info.hdr:
        steps += ["zscale=t=linear:npl=100", "format=gbrpf32le", "zscale=p=bt709",
                  "tonemap=hable:desat=0", "zscale=t=bt709:m=bt709:r=tv"]
    steps += ["format=yuv420p", "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709", "setsar=1"]
    return ",".join(steps)


def audio_select(pieces, fps: int) -> str:
    """Sound in chunks exactly one video frame long (1600 samples at 30 fps), kept or dropped with the frames."""
    return (f"aresample=48000,asetnsamples=n={48000 // fps}:p=0,"
            f"aselect='{keep_expression(pieces, fps)}',asetpts=N/SR/TB")


def measure_loudness(video: Path, pieces, fps: int) -> dict | None:
    """Listens to everything that stays and reports how loud it is (first of two volume passes)."""
    args = [ffmpeg_path(), "-hide_banner", "-nostats", "-i", str(video), "-vn",
            "-af", audio_select(pieces, fps) + f",loudnorm=I={export.LOUDNESS}:TP={export.TRUE_PEAK}"
                                          f":LRA={export.LOUDNESS_RANGE}:print_format=json",
            "-f", "null", "-"]
    result = run_hidden(args, timeout=4 * 3600)
    if result.returncode != 0:
        return None
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", result.stderr.decode(errors="replace"), re.S)
    if not match:
        return None
    data = json.loads(match.group(0))
    return None if data.get("input_i") in ("-inf", None) else data


def encode_args(video: Path, info: export.VideoInfo, pieces, measured, out: Path, gpu: bool, size: str,
                crf: int, cq: int) -> list[str]:
    args = [ffmpeg_path(), "-hide_banner", "-nostats", "-y", "-progress", "pipe:1", "-i", str(video),
            "-map", "0:v:0", "-vf", video_filter(info, pieces, size), "-fps_mode", "cfr"]
    if gpu:
        args += ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-b:v", "0"]
    else:
        args += ["-c:v", "libx264", "-preset", "fast", "-crf", str(crf)]
    args += ["-profile:v", "high", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    if info.has_audio:
        args += ["-map", "0:a:0", "-af", audio_select(pieces, info.fps) + "," + export.audio_filter(measured) + ",aresample=48000",
                 "-c:a", "aac", "-b:a", export.AUDIO_BITRATE, "-ar", "48000"]
    args += ["-movflags", "+faststart", str(out)]
    return args


def output_path(folder: Path, video: Path) -> Path:
    return folder / f"{safe_name(video.stem)}.mp4"


class LongExportWorker(QObject):
    """Same signals as export_dialog.ExportWorker, so the export window can show either."""
    progress = Signal(float, str)
    finished = Signal(list, str, bool)

    def __init__(self, video: Path, cuts: list[Clip], duration: float, folder: Path, size: str,
                 crf: int = export.X264_QUALITY, cq: int = export.NVENC_QUALITY):
        super().__init__()
        self.video, self.cuts, self.duration, self.folder, self.size = video, cuts, duration, folder, size
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
        final = output_path(self.folder, self.video)
        temp = final.with_name(final.stem + ".partial.mp4")
        try:
            info = export.probe(self.video)
            pieces = snap(kept_pieces(self.cuts, self.duration), info.fps)
            if not pieces:
                raise export.ExportError("Everything is cut out, so there's nothing left to export.")
            length = sum(b - a for a, b in pieces)
            self.folder.mkdir(parents=True, exist_ok=True)
            gpu = export.gpu_encoder_works()
            self.progress.emit(0.0, "Measuring the volume of the whole video (this takes a minute)")
            measured = measure_loudness(self.video, pieces, info.fps) if info.has_audio else None
            if self._cancelled:
                self.finished.emit([], "", True)
                return
            report = lambda p: self.progress.emit(p, f"Making the long video ({format_time(length, tenths=False)} long)")
            self.encoder_label = "graphics card" if gpu else "processor"
            code, log = export.run_encode(encode_args(self.video, info, pieces, measured, temp, gpu, self.size,
                                                      self.crf, self.cq), length, report, self._register)
            if code != 0 and gpu and not self._cancelled:
                self.encoder_label = "processor"  # the graphics card failed: use the processor instead
                code, log = export.run_encode(encode_args(self.video, info, pieces, measured, temp, False,
                                                          self.size, self.crf, self.cq), length, report, self._register)
            if self._cancelled:
                self.finished.emit([], "", True)
                return
            if code != 0:
                raise export.ExportError(f"FFmpeg stopped while making the long video:\n\n{log}")
            os.replace(temp, final)
            self.progress.emit(1.0, "Done")
            self.finished.emit([str(final)], "", False)
        except Exception as e:
            self.finished.emit([], str(e), self._cancelled)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
