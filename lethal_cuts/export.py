"""Turning clips into finished vertical MP4 files with FFmpeg.

Each clip is cut from the game video, cropped to its 9:16 box, resized to
1080x1920, converted to normal (non-HDR) color when needed, made constant
frame rate, and its volume evened out to the loudness YouTube and TikTok use.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from . import crop as cropmath
from .project import Clip, Crop
from .tools import NO_WINDOW, ffmpeg_path, ffprobe_path, run_hidden

OUT_W, OUT_H = 1080, 1920
LOUDNESS = -14.0      # LUFS: the loudness YouTube and TikTok aim for
TRUE_PEAK = -1.5      # dB: ceiling so loud reactions never distort
LOUDNESS_RANGE = 11.0
X264_QUALITY = 19     # lower = better looking, bigger file (18-23 is normal)
NVENC_QUALITY = 21
AUDIO_BITRATE = "192k"
HDR_TRANSFERS = {"arib-std-b67", "smpte2084"}  # HLG (iPhone default) and PQ

UPLOAD_PAGES = ["https://www.youtube.com/upload", "https://www.tiktok.com/upload"]


class ExportError(Exception):
    pass


@dataclass
class VideoInfo:
    width: int        # as displayed, after any phone rotation
    height: int
    fps: int          # constant frame rate the export uses (30 or 60, etc.)
    has_audio: bool
    hdr: bool

    @property
    def aspect(self) -> float:
        return self.width / self.height


def probe(video: Path) -> VideoInfo:
    ffprobe = ffprobe_path()
    if not ffprobe:
        raise ExportError("FFprobe wasn't found, so the video can't be read.")
    result = run_hidden([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(video)], timeout=60)
    if result.returncode != 0:
        raise ExportError("FFprobe couldn't read this video:\n" + result.stderr.decode(errors="replace")[-500:])
    streams = json.loads(result.stdout)["streams"]
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if v is None:
        raise ExportError("This file has no video in it.")
    w, h = int(v["width"]), int(v["height"])
    rotation = 0
    for side in v.get("side_data_list", []):
        if "rotation" in side:
            rotation = int(side["rotation"])
    if abs(rotation) % 180 == 90:
        w, h = h, w  # phone held sideways: FFmpeg turns it upright, so swap
    return VideoInfo(
        width=w,
        height=h,
        fps=_nominal_fps(v.get("r_frame_rate", "30/1")),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        hdr=v.get("color_transfer") in HDR_TRANSFERS,
    )


def _nominal_fps(rate: str) -> int:
    """iPhones record 'variable' frame rate around 30 or 60; pick the nearest normal rate."""
    try:
        num, den = rate.split("/")
        value = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        return 30
    for standard in (24, 25, 30, 50, 60):
        if abs(value - standard) < 1.5:
            return standard
    return 60 if value > 45 else 30


_gpu_encoder_ok: bool | None = None


def gpu_encoder_works() -> bool:
    """Tries a tiny encode on the NVIDIA graphics card once; falls back to the processor if it fails."""
    global _gpu_encoder_ok
    if _gpu_encoder_ok is None:
        ffmpeg = ffmpeg_path()
        try:
            result = run_hidden([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.2",
                                 "-c:v", "h264_nvenc", "-f", "null", "-"], timeout=30)
            _gpu_encoder_ok = result.returncode == 0
        except Exception:
            _gpu_encoder_ok = False
    return _gpu_encoder_ok


def video_filter(info: VideoInfo, crop: Crop | None) -> str:
    c = cropmath.clamp(crop, info.aspect) if crop else cropmath.default_crop(info.aspect)
    box_w = cropmath.box_width(c.h, info.aspect) * info.width
    box_h = c.h * info.height
    # Even numbers keep the video encoder happy.
    cw, ch = int(box_w) // 2 * 2, int(box_h) // 2 * 2
    cx = min(int(round(c.x * info.width)), info.width - cw)
    cy = min(int(round(c.y * info.height)), info.height - ch)
    steps = [f"crop={cw}:{ch}:{cx}:{cy}", f"scale={OUT_W}:{OUT_H}:flags=lanczos"]
    if info.hdr:
        # iPhone HDR looks washed out on most phones' players once it's been
        # through YouTube/TikTok, so convert it to normal color.
        steps += [
            "zscale=t=linear:npl=100", "format=gbrpf32le", "zscale=p=bt709",
            "tonemap=hable:desat=0", "zscale=t=bt709:m=bt709:r=tv",
        ]
    # Label the picture as standard (Rec. 709) color so every player shows it the same.
    steps += ["format=yuv420p", "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709",
              f"fps={info.fps}", "setsar=1"]
    return ",".join(steps)


def measure_loudness(video: Path, clip: Clip, cancelled=lambda: False) -> dict | None:
    """First of two volume passes: listens to the clip and reports how loud it is."""
    args = [ffmpeg_path(), "-hide_banner", "-nostats", "-ss", f"{clip.start:.3f}", "-t", f"{clip.length:.3f}",
            "-i", str(video), "-vn",
            "-af", f"loudnorm=I={LOUDNESS}:TP={TRUE_PEAK}:LRA={LOUDNESS_RANGE}:print_format=json",
            "-f", "null", "-"]
    result = run_hidden(args, timeout=600)
    if cancelled() or result.returncode != 0:
        return None
    text = result.stderr.decode(errors="replace")
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", text, re.S)
    if not match:
        return None
    data = json.loads(match.group(0))
    if data.get("input_i") in ("-inf", None):
        return None  # silent clip: nothing to even out
    return data


def audio_filter(measured: dict | None) -> str:
    if measured is None:
        return f"loudnorm=I={LOUDNESS}:TP={TRUE_PEAK}:LRA={LOUDNESS_RANGE}"
    return (
        f"loudnorm=I={LOUDNESS}:TP={TRUE_PEAK}:LRA={LOUDNESS_RANGE}"
        f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true"
    )


def encode_args(video: Path, clip: Clip, info: VideoInfo, measured: dict | None, out: Path, gpu: bool) -> list[str]:
    args = [ffmpeg_path(), "-hide_banner", "-nostats", "-y", "-progress", "pipe:1",
            "-ss", f"{clip.start:.3f}", "-t", f"{clip.length:.3f}", "-i", str(video),
            "-map", "0:v:0", "-vf", video_filter(info, clip.crop), "-fps_mode", "cfr"]
    if gpu:
        args += ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(NVENC_QUALITY), "-b:v", "0"]
    else:
        args += ["-c:v", "libx264", "-preset", "medium", "-crf", str(X264_QUALITY)]
    args += ["-profile:v", "high", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    if info.has_audio:
        args += ["-map", "0:a:0", "-af", audio_filter(measured) + ",aresample=48000",
                 "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", "48000"]
    args += ["-movflags", "+faststart", str(out)]
    return args


def output_name(number: int, clip: Clip) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", clip.name).strip().rstrip(".") or "Clip"
    return f"{number:02d} {name[:60]}.mp4"


def default_export_folder(video: Path) -> Path:
    return video.parent / f"{video.stem} Shorts"


def run_encode(args: list[str], length: float, on_progress, register_process) -> tuple[int, str]:
    """Runs FFmpeg, reporting progress (0 to 1) as it goes. Returns exit code and the end of its log."""
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    register_process(proc)
    # FFmpeg's error log is read on the side so it can't fill up and stall it.
    errors: list[bytes] = []
    reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
    reader.start()
    for raw in proc.stdout:
        line = raw.decode(errors="replace").strip()
        if line.startswith("out_time_us=") and line[12:].isdigit() and length > 0:
            on_progress(min(int(line[12:]) / 1e6 / length, 1.0))
    proc.wait()
    reader.join(timeout=5)
    return proc.returncode, (errors[0] if errors else b"").decode(errors="replace")[-800:]
