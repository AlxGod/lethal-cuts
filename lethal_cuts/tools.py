"""Finding and running FFmpeg, the free video engine used for previews and exports."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# Keeps FFmpeg from flashing a black console window on screen each time it runs.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def app_dir() -> Path:
    """The folder the program runs from (the install folder once it's packaged)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def ffmpeg_path() -> str | None:
    """The copy of FFmpeg bundled with the program, or one installed on this PC."""
    bundled = app_dir() / "vendor" / "ffmpeg" / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    return shutil.which("ffmpeg")


def run_hidden(args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
