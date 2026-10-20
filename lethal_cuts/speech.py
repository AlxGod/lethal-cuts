"""Speech-to-text for captions and "clip that" markers, with Whisper (faster-whisper) on this PC.

Whisper needs a "model": the trained file that turns sound into words. It downloads once from
Hugging Face (where the model's makers publish it) into the data folder. Nothing is uploaded.

A whole game is transcribed once in the background, 10 minutes of sound at a time, and the words
(each with its start and end time) are saved next to the video as "<video>.words.json". Captions
and "clip that" markers then come from that file instantly.

Speed: on the processor, roughly 4-10 times faster than the video plays, depending on the PC. With
the optional graphics card pack (NVIDIA's cuBLAS and cuDNN libraries, downloaded once from PyPI,
where NVIDIA publishes them), much faster. If the graphics card fails, it falls back to the processor.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import __version__
from .settings import data_dir
from .tools import NO_WINDOW, ffmpeg_path

# name: (label, download size in MB)
MODELS = {
    "base.en": ("Base: faster, less accurate (145 MB)", 145),
    "small.en": ("Small: the best balance (480 MB)", 484),
    "medium.en": ("Medium: most accurate, slowest (1.5 GB)", 1530),
}
DEFAULT_MODEL = "small.en"
MODEL_URL = "https://huggingface.co/Systran/faster-whisper-{name}/resolve/main/{file}"
MODEL_FILES = ["config.json", "tokenizer.json", "vocabulary.txt", "model.bin"]
GPU_PACKAGES = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12"]  # NVIDIA's own packages on PyPI
GPU_SIZE_MB = 1300
RATE = 16000
CHUNK_SECONDS = 600         # transcribed 10 minutes at a time, so a 3-hour game never sits in memory at once
TAIL_SECONDS = 3            # each piece hears a little past its end, so words on the edge aren't cut in half
HEADERS = {"User-Agent": f"LethalCuts/{__version__} (github.com/AlxGod/lethal-cuts)"}
CLIP_WORDS = {"that", "this", "it"}  # "clip that", "clip this", "clip it"


class SpeechError(Exception):
    pass


def speech_dir() -> Path:
    return data_dir() / "speech"


def model_dir(name: str) -> Path:
    return speech_dir() / "models" / name


def model_installed(name: str) -> bool:
    d = model_dir(name)
    return all((d / f).exists() for f in MODEL_FILES) and (d / "model.bin").stat().st_size > 1_000_000


def gpu_dir() -> Path:
    return speech_dir() / "gpu"


def gpu_pack_installed() -> bool:
    d = gpu_dir()
    return d.exists() and any(d.glob("cublas64_*.dll")) and any(d.glob("cudnn*.dll"))


def use_gpu_libraries() -> None:
    """Lets the speech engine find the graphics card pack's libraries."""
    d = gpu_dir()
    if d.exists():
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(d))
            except OSError:
                pass


# --- downloads (tests replace _open) ---
def _open(url: str, timeout: float = 30):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout)


def _download(url: str, dest: Path, report, cancelled) -> None:
    """Streams a file to dest (through a .part file, so a stopped download never looks finished)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with _open(url) as response, open(part, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if cancelled():
                    raise SpeechError("Download cancelled.")
                block = response.read(1 << 20)
                if not block:
                    break
                out.write(block)
                done += len(block)
                report(done, total)
        os.replace(part, dest)
    except SpeechError:
        part.unlink(missing_ok=True)
        raise
    except OSError as e:
        part.unlink(missing_ok=True)
        raise SpeechError(f"The download stopped ({e}). Check the internet connection and try again.")


class Download(QObject):
    """Downloads the speech model, or the graphics card pack, on a background thread."""
    progress = Signal(float, str)
    finished = Signal(str)  # "" when it worked, otherwise what went wrong

    def __init__(self, what: str):
        super().__init__()
        self.what = what  # a model name, or "gpu"
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            if self.what == "gpu":
                self._gpu_pack()
            else:
                self._model(self.what)
            self.finished.emit("")
        except SpeechError as e:
            self.finished.emit(str(e))
        except Exception as e:
            self.finished.emit(f"The download stopped: {e}")

    def _model(self, name: str):
        size = MODELS[name][1]
        for f in MODEL_FILES:
            dest = model_dir(name) / f
            if dest.exists():
                continue
            label = "the speech model" if f == "model.bin" else "the model's word list"

            def report(done, total, label=label):
                if f == "model.bin":
                    self.progress.emit(done / (total or size * 1e6), f"Downloading {label}: {done / 1e6:.0f} of "
                                                                     f"{(total or size * 1e6) / 1e6:.0f} MB")
            _download(MODEL_URL.format(name=name, file=f), dest, report, lambda: self._cancelled)

    def _gpu_pack(self):
        """NVIDIA's cuBLAS and cuDNN for Windows, from their official PyPI packages: only the .dll files are kept."""
        target = gpu_dir()
        target.mkdir(parents=True, exist_ok=True)
        for n, package in enumerate(GPU_PACKAGES):
            with _open(f"https://pypi.org/pypi/{package}/json") as r:
                info = json.loads(r.read().decode("utf-8"))
            wheel = next((u for u in info.get("urls", []) if u.get("filename", "").endswith("win_amd64.whl")), None)
            if not wheel:
                raise SpeechError(f"NVIDIA's {package} has no Windows download right now.")
            temp = speech_dir() / wheel["filename"]

            def report(done, total, n=n):
                self.progress.emit((n + done / (total or 1)) / len(GPU_PACKAGES),
                                   f"Downloading the graphics card pack ({n + 1} of {len(GPU_PACKAGES)}): "
                                   f"{done / 1e6:.0f} of {total / 1e6:.0f} MB")
            _download(wheel["url"], temp, report, lambda: self._cancelled)
            try:
                with zipfile.ZipFile(temp) as z:
                    for member in z.namelist():
                        if member.lower().endswith(".dll") and "/bin/" in member.replace("\\", "/"):
                            (target / Path(member).name).write_bytes(z.read(member))
            finally:
                temp.unlink(missing_ok=True)


# --- the transcript ---
def transcript_path(video: Path) -> Path:
    return video.with_name(video.name + ".words.json")


def load_words(video: Path) -> list[list] | None:
    """[[word, start, end], ...] for a video that's been listened to, or None."""
    try:
        return json.loads(transcript_path(video).read_text(encoding="utf-8"))["words"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_words(video: Path, words: list, model: str) -> None:
    path = transcript_path(video)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"model": model, "words": words}), encoding="utf-8")
    os.replace(tmp, path)


def _plain(word: str) -> str:
    return re.sub(r"[^a-z']", "", word.lower())


def find_clip_that(words: list) -> list[tuple[float, float]]:
    """(start, end) of each "clip that" (or "clip this", "clip it") said in the game."""
    found = []
    for i in range(len(words) - 1):
        if _plain(words[i][0]) == "clip" and _plain(words[i + 1][0]) in CLIP_WORDS:
            found.append((float(words[i][1]), float(words[i + 1][2])))
    return found


def card_prompt(names: list[str]) -> str:
    """A hint for Whisper about the names it will hear, so card names come out spelled right."""
    unique = list(dict.fromkeys(n.split(" // ")[0] for n in names if n))[:60]
    base = "A game of Magic: The Gathering, Commander."
    return base + (" Cards: " + ", ".join(unique) + "." if unique else "")


def _audio(video: Path, start: float, length: float):
    args = [ffmpeg_path(), "-hide_banner", "-nostats", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
            "-i", str(video), "-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"]
    result = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW, timeout=600)
    import numpy as np
    return np.frombuffer(result.stdout, dtype=np.float32)


def load_model(name: str, gpu: bool):
    """The Whisper model, on the graphics card if asked and it works, otherwise the processor.
    Returns (model, "graphics card" or "processor")."""
    from faster_whisper import WhisperModel
    path = str(model_dir(name))
    if gpu and gpu_pack_installed():
        use_gpu_libraries()
        try:
            import ctranslate2
            types = ctranslate2.get_supported_compute_types("cuda")
            compute = "int8_float16" if "int8_float16" in types else "int8"
            model = WhisperModel(path, device="cuda", compute_type=compute)
            import numpy as np
            list(model.transcribe(np.zeros(RATE, dtype=np.float32), language="en")[0])  # proves it really runs
            return model, "graphics card"
        except Exception:
            pass  # the graphics card can't: fall back to the processor
    # Half the processor's threads (its real cores) was fastest in tests: 4.2x real time vs 3.2x with all 16
    threads = max((os.cpu_count() or 2) // 2, 1)
    return WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=threads), "processor"


class Transcriber(QObject):
    """Listens to a whole recording on a background thread. Connect to methods, never lambdas."""
    progress = Signal(float, str)
    finished = Signal(list, str)  # words, error ("" if it worked)

    def __init__(self, video: Path, duration: float, model: str, gpu: bool, prompt: str = ""):
        super().__init__()
        self.video, self.duration, self.model_name, self.gpu, self.prompt = video, duration, model, gpu, prompt
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        words: list = []
        try:
            if not model_installed(self.model_name):
                raise SpeechError("The speech model isn't downloaded yet.")
            self.progress.emit(0.0, "Getting the speech model ready")
            model, where = load_model(self.model_name, self.gpu)
            started = time.monotonic()
            at = 0.0
            while at < self.duration and not self._cancelled:
                audio = _audio(self.video, at, CHUNK_SECONDS + TAIL_SECONDS)
                if len(audio) == 0:
                    break
                segments, _ = model.transcribe(audio, language="en", word_timestamps=True, vad_filter=True,
                                               beam_size=2, condition_on_previous_text=False,
                                               initial_prompt=self.prompt or None)
                for segment in segments:
                    if self._cancelled:
                        break
                    for w in segment.words or []:
                        start = at + w.start
                        if start < at + CHUNK_SECONDS or at + CHUNK_SECONDS >= self.duration:
                            words.append([w.word.strip(), round(start, 2), round(at + w.end, 2)])
                    done = min((at + segment.end) / max(self.duration, 1), 1.0)
                    spent = time.monotonic() - started
                    left = spent / done - spent if done > 0.02 else 0
                    self.progress.emit(done, f"Listening on the {where}" +
                                       (f", about {int(left // 60)} min left" if left > 60 else ""))
                at += CHUNK_SECONDS
            if self._cancelled:
                self.finished.emit([], "")
                return
            words = [w for w in words if w[0]]
            save_words(self.video, words, self.model_name)
            self.finished.emit(words, "")
        except SpeechError as e:
            self.finished.emit([], str(e))
        except Exception as e:
            self.finished.emit([], f"Listening stopped: {e}")
