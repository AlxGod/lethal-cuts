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
class Crop:
    """Where the tall 9:16 box sits, as fractions of the video picture
    (0 = left/top edge, 1 = right/bottom edge), so it works at any resolution."""
    x: float  # left edge of the box
    y: float  # top edge of the box
    h: float  # box height (1 = the full height of the video)

    @staticmethod
    def from_dict(d: dict | None) -> "Crop | None":
        return Crop(float(d["x"]), float(d["y"]), float(d["h"])) if d else None


@dataclass
class Clip:
    start: float  # seconds into the video
    end: float
    name: str = ""
    crop: Crop | None = None  # None = not set yet (exports centered)

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass
class Project:
    video_path: Path
    clips: list[Clip] = field(default_factory=list)
    position: float = 0.0  # where playback was when last saved
    last_crop: Crop | None = None  # given to each new clip, since the camera usually doesn't move
    cuts: list[Clip] = field(default_factory=list)  # long video: the dead stretches to leave out
    moments: list[float] = field(default_factory=list)  # seconds where the moment key was pressed while recording

    @property
    def path(self) -> Path:
        return project_path_for(self.video_path)

    def add_clip(self, clip: Clip) -> int:
        """Adds a clip, keeps the list in time order, and returns its index."""
        self.clips.append(clip)
        self.sort()
        return self.index_of(clip)

    def sort(self) -> None:
        self.clips.sort(key=lambda c: c.start)

    def index_of(self, clip: Clip) -> int:
        """Finds this exact clip (not just one with the same times)."""
        return next((i for i, c in enumerate(self.clips) if c is clip), -1)

    def overlapping(self, start: float, end: float, ignore: Clip | None = None) -> list[int]:
        return [i for i, c in enumerate(self.clips) if c is not ignore and c.start < end and start < c.end]

    def save(self) -> None:
        data = {
            "version": PROJECT_VERSION,
            "video": self.video_path.name,
            "position": round(self.position, 3),
            "last_crop": asdict(self.last_crop) if self.last_crop else None,
            "clips": [asdict(c) for c in self.clips],
            "cuts": [{"start": round(c.start, 3), "end": round(c.end, 3)} for c in self.cuts],
            "moments": [round(m, 3) for m in self.moments],
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
    clips = [
        Clip(float(c["start"]), float(c["end"]), c.get("name", ""), Crop.from_dict(c.get("crop")))
        for c in data.get("clips", [])
    ]
    clips.sort(key=lambda c: c.start)
    cuts = sorted((Clip(float(c["start"]), float(c["end"])) for c in data.get("cuts", [])), key=lambda c: c.start)
    moments = sorted(float(m) for m in data.get("moments", []))
    return Project(video_path, clips, float(data.get("position", 0.0)), Crop.from_dict(data.get("last_crop")), cuts,
                   moments)


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
