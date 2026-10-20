"""Finding clicker presses in a recording's sound, so each one becomes a marker on the timeline.

A dog-training clicker makes a short, sharp click with its own "color" of sound. He teaches
Lethal Cuts his clicker once, by putting the playhead on one click: the program finds the
sharpest sound within half a second and remembers its frequency mix (its spectrum). Then a
scan looks for sudden sounds that stand out from the background and keeps the ones whose mix
matches. Card slaps and shuffling are sudden too, but sound different, so most don't match.

The sound comes from FFmpeg already filtered to the clicker's range (1.5-7 kHz) at 16,000
samples a second, read in chunks so a 3-hour game never sits in memory all at once.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from .settings import data_dir
from .tools import NO_WINDOW, ffmpeg_path, run_hidden

RATE = 16000
BAND = "highpass=f=1500,lowpass=f=7000"
FFT = 1024                 # 64 ms of sound per spectrum
BEFORE, AFTER = 160, 864   # the click's window: 10 ms before its peak, 54 ms after
ENVELOPE = 32              # 2 ms smoothing to find sudden sounds
BACKGROUND = RATE // 2     # half a second of background to compare against
JUMP = 6.0                 # a click is at least this many times louder than the background
MIN_GAP = 1.0              # clicks closer together than this count once
CHUNK = RATE * 30          # 30 seconds at a time
DEFAULT_MATCH = 0.65       # how closely a sound must match the learned click (card slaps score about 0.4)


class ClickerError(Exception):
    pass


def template_path() -> Path:
    return data_dir() / "clicker.json"


def load_template() -> dict | None:
    try:
        data = json.loads(template_path().read_text(encoding="utf-8"))
        return {"spectrum": np.array(data["spectrum"], dtype=np.float32), "match": float(data.get("match", DEFAULT_MATCH))}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_template(spectrum: np.ndarray, match: float = DEFAULT_MATCH) -> None:
    path = template_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"spectrum": [round(float(v), 6) for v in spectrum], "match": match}), encoding="utf-8")


def set_match(match: float) -> None:
    t = load_template()
    if t:
        save_template(t["spectrum"], match)


def _audio_args(video: Path, start: float | None = None, length: float | None = None) -> list[str]:
    args = [ffmpeg_path(), "-hide_banner", "-nostats", "-v", "error"]
    if start is not None:
        args += ["-ss", f"{max(start, 0):.3f}", "-t", f"{length:.3f}"]
    return args + ["-i", str(video), "-vn", "-ac", "1", "-ar", str(RATE), "-af", BAND, "-f", "f32le", "-"]


def _spectrum(segment: np.ndarray) -> np.ndarray:
    padded = np.zeros(FFT, dtype=np.float32)
    seg = segment[:FFT] * np.hanning(len(segment[:FFT])).astype(np.float32)
    padded[:len(seg)] = seg
    s = np.abs(np.fft.rfft(padded))
    norm = np.linalg.norm(s)
    return s / norm if norm > 0 else s


def _envelope(x: np.ndarray) -> np.ndarray:
    kernel = np.ones(ENVELOPE, dtype=np.float32) / ENVELOPE
    return np.convolve(np.abs(x), kernel, mode="same")


def learn(video: Path, at: float) -> np.ndarray:
    """Finds the sharpest sound within half a second of `at` and returns its spectrum."""
    result = run_hidden(_audio_args(video, at - 0.5, 1.0), timeout=60)
    x = np.frombuffer(result.stdout, dtype=np.float32)
    if result.returncode != 0 or len(x) < RATE // 4:
        raise ClickerError("Couldn't read the sound there. Does this video have sound?")
    env = _envelope(x)
    peak = int(np.argmax(env))
    background = float(np.median(env)) + 1e-9
    if env[peak] < background * JUMP:
        raise ClickerError("There's no sharp click within half a second of the playhead. Put it right on a click "
                           "(listen at 1x speed) and try again.")
    return _spectrum(x[max(peak - BEFORE, 0):peak + AFTER])


def find_clicks(samples: np.ndarray, offset: float, spectrum: np.ndarray, match: float) -> list[tuple[float, float]]:
    """(seconds, how well it matched) for each click in a stretch of sound starting at `offset` seconds."""
    env = _envelope(samples)
    cs = np.concatenate(([0.0], np.cumsum(env, dtype=np.float64)))
    idx = np.arange(len(env))
    lo = np.clip(idx - BACKGROUND, 0, len(env))
    background = (cs[idx] - cs[lo]) / np.maximum(idx - lo, 1)  # the half second before each moment
    floor = max(float(np.percentile(env, 50)) * 0.5, 1e-5)
    loud = env > np.maximum(background, floor) * JUMP
    found, last = [], -10 ** 9
    for i in np.flatnonzero(loud):
        if i - last < MIN_GAP * RATE:
            continue
        window = env[i:i + RATE // 20]  # the peak of this sudden sound, within 50 ms
        peak = i + int(np.argmax(window))
        score = float(np.dot(_spectrum(samples[max(peak - BEFORE, 0):peak + AFTER]), spectrum))
        if score >= match:
            found.append((offset + peak / RATE, score))
            last = peak
        else:
            last = i - int(MIN_GAP * RATE) + RATE // 10  # skip past this sound, but not a whole second
    return found


class ClickScan(QObject):
    """Scans a whole recording on a background thread. Connect to methods, never lambdas."""
    progress = Signal(float)
    finished = Signal(list, str)  # click times, error message

    def __init__(self, video: Path, duration: float, spectrum: np.ndarray, match: float):
        super().__init__()
        self.video, self.duration, self.spectrum, self.match = video, duration, spectrum, match
        self._cancelled = False
        self._proc = None

    def cancel(self):
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.kill()

    def run(self):
        times: list[float] = []
        try:
            self._proc = subprocess.Popen(_audio_args(self.video), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                          creationflags=NO_WINDOW)
            carry = np.zeros(0, dtype=np.float32)
            read = 0
            overlap = AFTER + BACKGROUND
            while not self._cancelled:
                raw = self._proc.stdout.read(CHUNK * 4)
                if not raw:
                    break
                chunk = np.frombuffer(raw[:len(raw) // 4 * 4], dtype=np.float32)
                block = np.concatenate((carry, chunk))
                start = (read - len(carry)) / RATE
                for t, _ in find_clicks(block, start, self.spectrum, self.match):
                    if not times or t - times[-1] >= MIN_GAP:
                        times.append(round(t, 3))
                read += len(chunk)
                carry = block[-overlap:]
                if self.duration > 0:
                    self.progress.emit(min(read / RATE / self.duration, 1.0))
            self._proc.wait()
            self.finished.emit(times, "")
        except Exception as e:
            self.finished.emit(times, f"The click scan stopped: {e}")
