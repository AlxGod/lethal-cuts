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
from . import overlays as overlay_mod
from . import pause_title
from .folders import safe_name
from .project import Clip, format_time
from .tools import ffmpeg_path, run_hidden

MIN_PIECE = 0.05  # seconds: slivers shorter than this between cuts are dropped

# How the video joins up where a dead stretch was cut out: (name, FFmpeg xfade transition, seconds)
TRANSITIONS = {
    "cut": ("Hard cut", "", 0.0),
    "fade": ("Crossfade", "fade", 0.5),
    "dip": ("Dip to black", "fadeblack", 0.6),
    "whip": ("Whip", "hblur", 0.3),
}


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


def joins(cuts: list[Clip], pieces: list[tuple[float, float]], default: str) -> list[str]:
    """The transition at each join between kept pieces: the cut(s) in that gap decide, else the default."""
    found = []
    for (_, end), (start, _) in zip(pieces, pieces[1:]):
        chosen = [c.transition for c in cuts if c.start < start and c.end > end and c.transition]
        kind = chosen[0] if chosen else default
        found.append(kind if kind in TRANSITIONS else "cut")
    return found


def plan(pieces: list[tuple[float, float]], kinds: list[str], fps: int):
    """Groups pieces joined by hard cuts, and lists the transitions between the groups.
    Returns (groups, [(xfade name, seconds)], overlap per join). A transition longer than half
    of either side becomes a hard cut, so short bits are never swallowed."""
    groups, transitions, overlaps = [[pieces[0]]], [], []
    for piece, kind in zip(pieces[1:], kinds):
        name, xfade, seconds = TRANSITIONS.get(kind, TRANSITIONS["cut"])
        d = round(seconds * fps) / fps  # whole frames, so the sound overlaps by exactly the same time
        left = sum(b - a for a, b in groups[-1]) - sum(t[1] for t in transitions[-1:])
        if xfade and d > 0 and left >= 2 * d and piece[1] - piece[0] >= 2 * d:
            transitions.append((xfade, d))
            overlaps.append(d)
            groups.append([piece])
        else:
            overlaps.append(0.0)
            groups[-1].append(piece)
    return groups, transitions, overlaps


def output_length(pieces: list[tuple[float, float]], overlaps: list[float]) -> float:
    return sum(b - a for a, b in pieces) - sum(overlaps)


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


def output_size(info: export.VideoInfo, size: str) -> tuple[int, int]:
    """The long video's width and height (the same sums as overlays.long_frame)."""
    height = output_height(info, size)
    width = info.width if height == info.height else int(height * info.width / info.height) // 2 * 2
    return width, height


def finish_steps(info: export.VideoInfo, size: str) -> list[str]:
    """Resizing and color steps, done once the frames to keep have been picked."""
    steps = []
    width, height = output_size(info, size)
    if height != info.height:
        steps.append(f"scale={width}:{height}:flags=lanczos")
    if info.hdr:
        steps += ["zscale=t=linear:npl=100", "format=gbrpf32le", "zscale=p=bt709",
                  "tonemap=hable:desat=0", "zscale=t=bt709:m=bt709:r=tv"]
    return steps


POST = "format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709,setsar=1"


def _span(group, fps):
    """A group's first and last frame, for trimming: once a part has passed, it ends straight away
    (a select alone would keep every later frame waiting in memory for the transition after it)."""
    return round(group[0][0] * fps), round(group[-1][1] * fps)


def transition_video(info: export.VideoInfo, groups, transitions, size: str, title: tuple | None = None) -> str:
    """Graph parts: every group picked out of one decode, joined by xfade, ending at [lv].
    title: (input number, seconds) of the title card picture that opens the video."""
    fps, n = info.fps, len(groups)
    parts = [f"[0:v]fps={fps},split={n}" + "".join(f"[vs{i}]" for i in range(n))]
    # With a title card, each part is finished (sized, colored) first, so it matches the title picture
    finish = "," + ",".join(finish_steps(info, size) + ["format=yuv420p", "setsar=1"]) if title else ""
    for i, g in enumerate(groups):
        half = 0.5 / fps  # by time, half a frame either side, like the select that follows
        parts.append(f"[vs{i}]trim=start={max(g[0][0] - half, 0):.6f}:end={g[-1][1] + half:.6f},"
                     f"select='{keep_expression(g, fps)}',"
                     f"setpts=N/FRAME_RATE/TB{finish}[v{i}]")
    label, length = "v0", sum(b - a for a, b in groups[0])
    if title:
        index, seconds = title
        width, height = output_size(info, size)
        d = pause_title.title_dip(fps)
        parts.append(f"[{index}:v]scale={width}:{height}:flags=lanczos,format=yuv420p,setsar=1,fps={fps},"
                     f"setpts=N/FRAME_RATE/TB[vt]")
        parts.append(f"[vt][v0]xfade=transition=fadeblack:duration={d:.6f}:offset={seconds - d:.6f}[vh]")
        label, length = "vh", seconds + length - d
    for i, (xfade, d) in enumerate(transitions):
        parts.append(f"[{label}][v{i + 1}]xfade=transition={xfade}:duration={d:.6f}:offset={length - d:.6f}[vx{i}]")
        label = f"vx{i}"
        length += sum(b - a for a, b in groups[i + 1]) - d
    steps = "null" if title else (",".join(finish_steps(info, size)) or "null")
    parts.append(f"[{label}]{steps}[lv]")
    return ";".join(parts)


def transition_audio(groups, transitions, fps: int, tail: str, title_seconds: float = 0.0) -> str:
    """Graph parts for the sound: the same groups, in frame-long chunks, joined by acrossfade, then tail, ending at [aout].
    With a title card, silence plays under it and fades into the game's sound."""
    n, chunk = len(groups), 48000 // fps
    fmt = ",aformat=sample_fmts=fltp:channel_layouts=stereo" if title_seconds else ""
    parts = [f"[0:a]aresample=48000{fmt},asetnsamples=n={chunk}:p=0,asplit={n}" + "".join(f"[as{i}]" for i in range(n))]
    for i, g in enumerate(groups):
        first, last = _span(g, fps)
        parts.append(f"[as{i}]atrim=start_sample={first * chunk}:end_sample={last * chunk},"
                     f"aselect='{keep_expression(g, fps)}',asetpts=N/SR/TB[a{i}]")
    label = "a0"
    if title_seconds:
        d = pause_title.title_dip(fps)
        parts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={title_seconds:.6f},aformat=sample_fmts=fltp[atl]")
        parts.append(f"[atl][a0]acrossfade=d={d:.6f}:c1=tri:c2=tri[ah]")
        label = "ah"
    for i, (_, d) in enumerate(transitions):
        parts.append(f"[{label}][a{i + 1}]acrossfade=d={d:.6f}:c1=tri:c2=tri[ax{i}]")
        label = f"ax{i}"
    parts.append(f"[{label}]{tail}[aout]")
    return ";".join(parts)


def encode_args(video: Path, info: export.VideoInfo, pieces, measured, out: Path, gpu: bool, size: str,
                crf: int, cq: int, placed: list | None = None, kinds: list[str] | None = None,
                title: tuple | None = None) -> list[str]:
    """title: (title card picture, seconds) to open the video with."""
    groups, transitions, _ = plan(pieces, kinds or ["cut"] * (len(pieces) - 1), info.fps)
    if transitions or title:
        return _transition_args(video, info, groups, transitions, measured, out, gpu, size, crf, cq, placed, title)
    args = [ffmpeg_path(), "-hide_banner", "-nostats", "-y", "-progress", "pipe:1", "-i", str(video),
            *export.video_args(video_filter(info, pieces, size), placed, info.fps), "-fps_mode", "cfr"]
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


def _codec_args(gpu: bool, crf: int, cq: int) -> list[str]:
    if gpu:
        args = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-b:v", "0"]
    else:
        args = ["-c:v", "libx264", "-preset", "fast", "-crf", str(crf)]
    return args + ["-profile:v", "high", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]


def _transition_args(video, info, groups, transitions, measured, out, gpu, size, crf, cq, placed,
                     title=None) -> list[str]:
    """One FFmpeg run for a long video with transitions or a title card: one -filter_complex for picture and sound."""
    inputs = []
    if title:
        image, seconds = title
        inputs = ["-loop", "1", "-framerate", str(info.fps), "-t", f"{seconds + 0.2:.3f}", "-i", str(image)]
    graph = transition_video(info, groups, transitions, size, (1, seconds) if title else None)
    graph += ";" + overlay_mod.filter_graph("null", POST, placed or [], 2 if title else 1, info.fps, source="[lv]")
    if info.has_audio:
        graph += ";" + transition_audio(groups, transitions, info.fps, export.audio_filter(measured) + ",aresample=48000",
                                        seconds if title else 0.0)
    args = [ffmpeg_path(), "-hide_banner", "-nostats", "-y", "-progress", "pipe:1", "-i", str(video), *inputs,
            *overlay_mod.image_inputs(placed or [], info.fps), "-filter_complex", graph, "-map", "[vout]",
            "-fps_mode", "cfr", *_codec_args(gpu, crf, cq)]
    if info.has_audio:
        args += ["-map", "[aout]", "-c:a", "aac", "-b:a", export.AUDIO_BITRATE, "-ar", "48000"]
    return args + ["-movflags", "+faststart", str(out)]


def measure_with_transitions(video: Path, groups, transitions, fps: int) -> dict | None:
    """The volume pass when the sound crossfades at the joins: listens to exactly what will be exported."""
    loud = f"loudnorm=I={export.LOUDNESS}:TP={export.TRUE_PEAK}:LRA={export.LOUDNESS_RANGE}:print_format=json"
    args = [ffmpeg_path(), "-hide_banner", "-nostats", "-i", str(video),
            "-filter_complex", transition_audio(groups, transitions, fps, loud), "-map", "[aout]", "-f", "null", "-"]
    result = run_hidden(args, timeout=4 * 3600)
    if result.returncode != 0:
        return None
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", result.stderr.decode(errors="replace"), re.S)
    if not match:
        return None
    data = json.loads(match.group(0))
    return None if data.get("input_i") in ("-inf", None) else data


def output_path(folder: Path, video: Path) -> Path:
    return folder / f"{safe_name(video.stem)}.mp4"


class LongExportWorker(QObject):
    """Same signals as export_dialog.ExportWorker, so the export window can show either."""
    progress = Signal(float, str)
    finished = Signal(list, str, bool)

    def __init__(self, video: Path, cuts: list[Clip], duration: float, folder: Path, size: str,
                 crf: int = export.X264_QUALITY, cq: int = export.NVENC_QUALITY, placed: list | None = None,
                 transition: str = "cut", title: tuple | None = None):
        super().__init__()
        self.title = title  # (title card picture, seconds), or None
        self.video, self.cuts, self.duration, self.folder, self.size = video, cuts, duration, folder, size
        self.transition = transition  # the default join, for cuts that don't pick their own
        self.placed = placed or []  # overlays.Placed, already timed for the finished video
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
            kinds = joins(self.cuts, pieces, self.transition)
            groups, transitions, overlaps = plan(pieces, kinds, info.fps)
            length = output_length(pieces, overlaps)
            if self.title:
                length += self.title[1] - pause_title.title_dip(info.fps)
            self.folder.mkdir(parents=True, exist_ok=True)
            gpu = export.gpu_encoder_works()
            self.progress.emit(0.0, "Measuring the volume of the whole video (this takes a minute)")
            if not info.has_audio:
                measured = None
            elif transitions:
                measured = measure_with_transitions(self.video, groups, transitions, info.fps)
            else:
                measured = measure_loudness(self.video, pieces, info.fps)
            if self._cancelled:
                self.finished.emit([], "", True)
                return
            report = lambda p: self.progress.emit(p, f"Making the long video ({format_time(length, tenths=False)} long)")
            self.encoder_label = "graphics card" if gpu else "processor"
            code, log = export.run_encode(encode_args(self.video, info, pieces, measured, temp, gpu, self.size,
                                                      self.crf, self.cq, self.placed, kinds, self.title), length,
                                          report, self._register)
            if code != 0 and gpu and not self._cancelled:
                self.encoder_label = "processor"  # the graphics card failed: use the processor instead
                code, log = export.run_encode(encode_args(self.video, info, pieces, measured, temp, False,
                                                          self.size, self.crf, self.cq, self.placed, kinds, self.title),
                                              length, report, self._register)
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
