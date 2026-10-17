"""The user's settings, kept in a plain JSON file that survives updates.

The file lives in %APPDATA%\\Lethal Cuts\\settings.json, outside the install
folder, so installing a new version never erases it. For testing, the
LETHALCUTS_DATA environment variable points it at another folder.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

# Each action the user can give a key, in the order shown in Settings and the Guide.
ACTIONS = {
    "play_pause": ("Play / pause", "Space"),
    "mark_start": ("Mark start", "I"),
    "mark_end": ("Mark end (saves the clip)", "O"),
    "cancel": ("Cancel the start mark / leave preview", "Escape"),
    "preview": ("Preview the selected clip vertically", "P"),
    "step_back": ("Jump back", "Left"),
    "step_forward": ("Jump forward", "Right"),
    "small_back": ("Jump back 1 second", "Shift+Left"),
    "small_forward": ("Jump forward 1 second", "Shift+Right"),
    "speed_1": ("Speed 1x", "1"),
    "speed_2": ("Speed 2x", "2"),
    "speed_3": ("Speed 3x", "3"),
    "speed_4": ("Speed 4x", "4"),
    "delete": ("Delete the selected clip", "Delete"),
    "undo": ("Bring back a deleted clip", "Ctrl+Z"),
    "export": ("Export all clips", "Ctrl+E"),
    "open": ("Open a video", "Ctrl+O"),
}

# Export quality: (name shown, x264 CRF, NVENC CQ). Lower numbers look better and make bigger files.
QUALITIES = {
    "good": ("Good (smaller files)", 22, 24),
    "high": ("High (recommended)", 19, 21),
    "best": ("Best (biggest files)", 16, 18),
}


LONG_SIZES = {
    "1080": "1080p (faster to make and upload)",
    "source": "Same as the recording (sharpest, e.g. 4K)",
}


@dataclass
class Settings:
    hotkeys: dict = field(default_factory=lambda: {k: v[1] for k, v in ACTIONS.items()})
    pad_before: float = 0.5   # extra seconds added before each clip's start mark
    pad_after: float = 0.5    # and after its end mark
    step_seconds: float = 5.0  # how far the arrow keys jump
    save_folder: str = ""     # where all videos go; filled in on the first start (see folders.py)
    quality: str = "high"
    long_size: str = "1080"   # long videos: "1080" (faster, smaller) or "source" (same size as the recording)
    nudges: bool = True       # friendly tips while working
    clip_color_a: str = "#b0304a"
    clip_color_b: str = "#7b4fc9"
    crop_color: str = "#f0b840"
    walkthrough_done: bool = False
    obs_exe: str = ""         # OBS's program file, if it isn't where the OBS installer puts it
    open_after_record: bool = True

    def key(self, action: str) -> str:
        return self.hotkeys.get(action) or ACTIONS[action][1]


def data_dir() -> Path:
    override = os.environ.get("LETHALCUTS_DATA")
    if override:
        return Path(override)
    return Path(os.environ.get("APPDATA", Path.home())) / "Lethal Cuts"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def load() -> Settings:
    """Reads the settings file. Missing or damaged values fall back to the defaults."""
    s = Settings()
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return s
    if not isinstance(data, dict):
        return s
    for f in fields(Settings):
        if f.name not in data:
            continue
        value, default = data[f.name], getattr(s, f.name)
        if f.name == "hotkeys" and isinstance(value, dict):
            s.hotkeys.update({k: str(v) for k, v in value.items() if k in ACTIONS})
        elif isinstance(default, bool):
            s.__dict__[f.name] = bool(value)
        elif isinstance(default, float):
            try:
                s.__dict__[f.name] = max(0.0, float(value))
            except (TypeError, ValueError):
                pass
        elif isinstance(default, str) and isinstance(value, str):
            s.__dict__[f.name] = value
    if s.quality not in QUALITIES:
        s.quality = "high"
    if s.long_size not in LONG_SIZES:
        s.long_size = "1080"
    return s


def save(s: Settings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), indent=2), encoding="utf-8")
    os.replace(tmp, path)
