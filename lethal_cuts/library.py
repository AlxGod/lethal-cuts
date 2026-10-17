"""Every exported Short from every game, and where each one has been posted.

Kept in library.json beside settings.json, so it survives reinstalls. Clips whose file
was deleted or moved by hand simply drop off the list.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .settings import data_dir

# site key: (name shown, upload page)
SITES = {
    "youtube": ("YouTube", "https://www.youtube.com/upload"),
    "tiktok": ("TikTok", "https://www.tiktok.com/upload"),
}


@dataclass
class Short:
    file: str
    name: str
    video: str      # the game recording it was cut from
    length: float
    exported: str   # when it was exported (ISO date and time)
    posted: dict[str, str] = field(default_factory=dict)  # site key: when it was marked posted

    @property
    def path(self) -> Path:
        return Path(self.file)

    @property
    def is_posted(self) -> bool:
        return bool(self.posted)


def library_path() -> Path:
    return data_dir() / "library.json"


def _same_file(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def nice_date(iso: str) -> str:
    """'Oct 17' (or 'Oct 17, 2025' for another year)."""
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    text = f"{when:%b} {when.day}"
    return text if when.year == datetime.now().year else f"{text}, {when.year}"


class Library:
    def __init__(self, shorts: list[Short] | None = None):
        self.shorts = shorts or []

    @classmethod
    def load(cls) -> Library:
        """Reads library.json. A damaged file or damaged entries are skipped, never fatal."""
        try:
            data = json.loads(library_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        shorts = []
        for item in data.get("shorts", []) if isinstance(data, dict) else []:
            try:
                posted = item.get("posted") or {}
                shorts.append(Short(str(item["file"]), str(item["name"]), str(item.get("video", "")),
                                    float(item.get("length", 0)), str(item.get("exported", "")),
                                    {k: str(v) for k, v in posted.items() if k in SITES}))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        return cls(shorts)

    def save(self) -> None:
        path = library_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "shorts": [asdict(s) for s in self.shorts]}, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def add(self, file: str | Path, name: str, video: str | Path, length: float) -> Short:
        """Records a freshly exported clip. Exporting the same file again updates it and keeps its posted marks."""
        file = str(file)
        old = next((s for s in self.shorts if _same_file(s.file, file)), None)
        short = Short(file, name, str(video), round(length, 2), now(), dict(old.posted) if old else {})
        if old:
            self.shorts.remove(old)
        self.shorts.append(short)
        return short

    def find(self, file: str) -> Short | None:
        return next((s for s in self.shorts if s.file == file), None)

    def existing(self) -> list[Short]:
        """Clips whose file is still there, newest first. Missing ones are forgotten."""
        gone = [s for s in self.shorts if not s.path.exists()]
        if gone:
            self.shorts = [s for s in self.shorts if s not in gone]
            try:
                self.save()
            except OSError:
                pass
        return sorted(self.shorts, key=lambda s: s.exported, reverse=True)

    def set_posted(self, short: Short, site: str, posted: bool) -> None:
        if posted:
            short.posted[site] = now()
        else:
            short.posted.pop(site, None)
        self.save()

    def remove(self, short: Short) -> None:
        if short in self.shorts:
            self.shorts.remove(short)
            self.save()
