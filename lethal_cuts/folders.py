"""Where Lethal Cuts saves videos: one folder picked when installing (changeable in Settings),
with a subfolder for each kind of video."""
from __future__ import annotations

import configparser
import os
import re
import shutil
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from .tools import app_dir

RECORDINGS = "Recordings"
SHORTS = "Shorts"
LONG_VIDEOS = "Long videos"


def install_ini() -> Path:
    """Written by the installer: the save folder picked while installing."""
    return app_dir() / "install.ini"


def installer_choice() -> str:
    ini = configparser.ConfigParser()
    try:
        ini.read(install_ini(), encoding="utf-8-sig")
        return ini.get("Lethal Cuts", "SaveFolder", fallback="").strip()
    except (OSError, configparser.Error):
        return ""


def default_save_folder() -> Path:
    chosen = installer_choice()
    if chosen:
        return Path(chosen)
    videos = QStandardPaths.writableLocation(QStandardPaths.MoviesLocation) or str(Path.home() / "Videos")
    return Path(videos) / "Lethal Cuts"


def save_folder(s) -> Path:
    return Path(s.save_folder) if s.save_folder else default_save_folder()


def safe_name(text: str, fallback: str = "Video") -> str:
    """A name Windows accepts as a file or folder name."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip().rstrip(".")[:80] or fallback


def shorts_folder(s, video: Path) -> Path:
    """Each game gets its own folder of Shorts, so clip names from different games never clash."""
    return save_folder(s) / SHORTS / safe_name(video.stem)


def long_videos_folder(s) -> Path:
    return save_folder(s) / LONG_VIDEOS


def recordings_folder(s) -> Path:
    return save_folder(s) / RECORDINGS


def is_inside_program(folder: Path) -> bool:
    """The program's own folder is replaced on every update, so videos must never be saved inside it."""
    try:
        a = os.path.normcase(os.path.abspath(folder))
        b = os.path.normcase(os.path.abspath(app_dir()))
    except (OSError, ValueError):
        return False
    return a == b or a.startswith(b + os.sep)


def free_space(folder: Path) -> int | None:
    """Bytes free on the drive that holds this folder (it doesn't have to exist yet)."""
    folder = Path(folder)
    for candidate in (folder, *folder.parents):
        if candidate.exists():
            try:
                return shutil.disk_usage(candidate).free
            except OSError:
                return None
    return None
