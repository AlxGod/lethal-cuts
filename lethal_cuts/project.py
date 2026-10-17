"""The project file: the clips marked in one video, saved as JSON next to that video.

A video "game.mov" gets a project file "game.lcproj" in the same folder, so the
user can close the program and pick up where he left off.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

PROJECT_VERSION = 1
PROJECT_SUFFIX = ".lcproj"


@dataclass
class Clip:
    start: float  # seconds into the video
    end: float
    name: str = ""

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass
class Project:
    video_path: Path
    clips: list[Clip] = field(default_factory=list)
    position: float = 0.0  # where playback was when last saved

    @property
    def path(self) -> Path:
        return project_path_for(self.video_path)

    def add_clip(self, clip: Clip) -> int:
        """Adds a clip, keeps the list in time order, and returns its index."""
        self.clips.append(clip)
        self.clips.sort(key=lambda c: c.start)
        return self.clips.index(clip)

    def save(self) -> None:
        data = {
            "version": PROJECT_VERSION,
            "video": self.video_path.name,
            "position": round(self.position, 3),
            "clips": [asdict(c) for c in self.clips],
        }
        # Write to a temporary file first, then swap it in, so a crash mid-save
        # can never leave a half-written project file behind.
        tmp = self.path.with_suffix(PROJECT_SUFFIX + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


def project_path_for(video_path: Path) -> Path:
    return video_path.with_suffix(PROJECT_SUFFIX)


def open_project(video_path: Path) -> Project:
    """Loads the saved project for a video, or starts a fresh one."""
    path = project_path_for(video_path)
    if not path.exists():
        return Project(video_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    clips = [Clip(float(c["start"]), float(c["end"]), c.get("name", "")) for c in data.get("clips", [])]
    clips.sort(key=lambda c: c.start)
    return Project(video_path, clips, float(data.get("position", 0.0)))


def format_time(seconds: float, tenths: bool = True) -> str:
    """1:02:03.4 for long times, 2:03.4 for short ones."""
    seconds = max(0.0, seconds)
    whole = int(seconds)
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    text = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    if tenths:
        text += f".{int((seconds - whole) * 10)}"
    return text
