"""The project file: the clips marked in one video, saved as JSON next to that video.

A video "game.mov" gets a project file "game.lcproj" in the same folder, so the
user can close the program and pick up where he left off.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields, asdict
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
    transition: str = ""      # long video cuts: how the video joins up here ("" = the default in Settings)

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass
class Overlay:
    """Something shown on top of the video for a while: a card picture or some text.

    Times are seconds into the recording. Place and size are fractions of the finished
    video (the tall Short or the widescreen long video), so they work at any resolution."""
    kind: str             # "text" or "card"
    start: float
    end: float
    x: float = 0.5        # where its middle is: 0 = left edge, 1 = right edge
    y: float = 0.3        # 0 = top, 1 = bottom
    size: float = 0.6     # its width, as a fraction of the video's width
    anim_in: str = "pop"  # how it comes in: none, fade, pop, slide or type (text only: letter by letter)
    anim_out: str = "fade"
    text: str = ""        # words between *stars* are drawn in the highlight color
    style: str = "plain"  # the ready-made style it started from (text_look.STYLES)
    card: dict | None = None  # the card's name, picture file and Scryfall details
    # How text looks (cards ignore these)
    font: str = "Segoe UI"
    weight: int = 900         # 400 normal, 700 bold, 900 extra bold
    color: str = "#ffffff"
    accent: str = "#ffd400"   # the highlight color for *starred* words
    outline: float = 0.14     # outline thickness, as a fraction of the letter size (0 = none)
    outline_color: str = "#000000"
    shadow: bool = False
    box: str = ""             # background box color ("#AARRGGBB" allowed), "" for none
    stripe: bool = False      # a highlight-colored bar down the box's left side (name tags)
    caps: bool = False        # ALL CAPITALS
    align: str = "center"     # "center" or "left"

    @property
    def length(self) -> float:
        return self.end - self.start

    @staticmethod
    def from_dict(d: dict) -> "Overlay":
        o = Overlay(str(d.get("kind", "text")), float(d["start"]), float(d["end"]))
        for f in fields(Overlay):
            if f.name in ("kind", "start", "end", "card") or f.name not in d:
                continue
            kind = type(getattr(o, f.name))  # each value is read as the same type as its default
            try:
                setattr(o, f.name, d[f.name] if kind is bool and isinstance(d[f.name], bool) else kind(d[f.name]))
            except (TypeError, ValueError):
                pass  # a damaged value keeps the default
        o.card = d.get("card") if isinstance(d.get("card"), dict) else None
        return o


@dataclass
class Project:
    video_path: Path
    clips: list[Clip] = field(default_factory=list)
    position: float = 0.0  # where playback was when last saved
    last_crop: Crop | None = None  # given to each new clip, since the camera usually doesn't move
    cuts: list[Clip] = field(default_factory=list)  # long video: the dead stretches to leave out
    moments: list[float] = field(default_factory=list)  # seconds where the moment key was pressed while recording
    overlays: list[Overlay] = field(default_factory=list)       # cards and text on the Shorts
    long_overlays: list[Overlay] = field(default_factory=list)  # cards and text on the long video
    title_card: dict | None = None  # the long video's opening title card (pause_title.new_title)
    markers: list[dict] = field(default_factory=list)  # found in the sound: {"t": seconds, "kind": "click" or "speech"}
    scanned: dict = field(default_factory=dict)        # which scans have run on this video, e.g. {"click": true}

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
            "cuts": [{"start": round(c.start, 3), "end": round(c.end, 3), **({"transition": c.transition} if c.transition else {})}
                     for c in self.cuts],
            "moments": [round(m, 3) for m in self.moments],
            "overlays": [asdict(o) for o in self.overlays],
            "long_overlays": [asdict(o) for o in self.long_overlays],
            "title_card": self.title_card,
            "markers": self.markers,
            "scanned": self.scanned,
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
    cuts = sorted((Clip(float(c["start"]), float(c["end"]), transition=str(c.get("transition", "")))
                   for c in data.get("cuts", [])), key=lambda c: c.start)
    moments = sorted(float(m) for m in data.get("moments", []))
    overlays = sorted((Overlay.from_dict(o) for o in data.get("overlays", [])), key=lambda o: o.start)
    long_overlays = sorted((Overlay.from_dict(o) for o in data.get("long_overlays", [])), key=lambda o: o.start)
    title = data.get("title_card") if isinstance(data.get("title_card"), dict) else None
    markers = sorted((m for m in data.get("markers", []) if isinstance(m, dict) and "t" in m), key=lambda m: m["t"])
    scanned = data.get("scanned") if isinstance(data.get("scanned"), dict) else {}
    return Project(video_path, clips, float(data.get("position", 0.0)), Crop.from_dict(data.get("last_crop")), cuts,
                   moments, overlays, long_overlays, title, markers, scanned)


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
