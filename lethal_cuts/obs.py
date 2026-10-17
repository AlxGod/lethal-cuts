"""Recording with OBS (the free recorder), the same way Clip Drop does it.

Lethal Cuts gives OBS its own "Lethal Cuts" profile (recording settings) and scene collection
(what's on screen: the Tabletop Simulator window, the computer's sound and the microphone),
starts OBS minimized by the clock already recording, and closes it the way clicking its X does
when the game is over. Never kill OBS: a killed OBS asks about "safe mode" the next time.
The person's own OBS profiles and scenes are never touched.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import time
import uuid
from ctypes import wintypes
from pathlib import Path

from .tools import NO_WINDOW, run_hidden

NAME = "Lethal Cuts"  # the profile, the scene collection and the scene are all called this
TTS_WINDOW = "Tabletop Simulator:UnityWndClass:Tabletop Simulator.exe"  # OBS's "title:class:program" form
CANVAS = (1920, 1080)
VIDEO_SUFFIXES = (".mp4", ".mkv", ".mov")
GET_OBS = "https://obsproject.com/download"


def config_root() -> Path:
    """OBS's settings folder. LETHALCUTS_OBS_CONFIG points it elsewhere for tests."""
    override = os.environ.get("LETHALCUTS_OBS_CONFIG")
    if override:
        return Path(override)
    return Path(os.environ.get("APPDATA", Path.home())) / "obs-studio"


def profile_ini() -> Path:
    return config_root() / "basic" / "profiles" / NAME / "basic.ini"


def collection_json() -> Path:
    return config_root() / "basic" / "scenes" / f"{NAME}.json"


def find_exe(custom: str = "") -> Path | None:
    """OBS's program file: the one picked in Settings, or wherever the OBS installer put it."""
    if custom:
        return Path(custom) if Path(custom).exists() else None
    candidates = []
    try:
        import winreg
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\OBS Studio", 0, winreg.KEY_READ | view) as key:
                    candidates.append(Path(winreg.QueryValueEx(key, "")[0]))
            except OSError:
                pass
    except ImportError:
        pass
    candidates.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "obs-studio")
    for folder in candidates:
        exe = folder / "bin" / "64bit" / "obs64.exe"
        if exe.exists():
            return exe
    return None


def is_running() -> bool:
    try:
        out = run_hidden(["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/NH"], timeout=15).stdout.decode(errors="replace")
    except Exception:
        return False
    return "obs64.exe" in out.lower()


def has_nvidia() -> bool:
    """NVIDIA's video encoder comes with its driver; OBS uses it so recording barely touches the game's speed."""
    return (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvEncodeAPI64.dll").exists()


# --- setting OBS up ---
def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _profile_text(recordings: Path) -> str:
    w, h = CANVAS
    return "\n".join([
        "[General]", f"Name={NAME}", "",
        "[Video]", f"BaseCX={w}", f"BaseCY={h}", f"OutputCX={w}", f"OutputCY={h}",
        "FPSType=0", "FPSCommon=30", "",
        "[Output]", "Mode=Simple", f"FilenameFormatting={NAME} %CCYY-%MM-%DD %hh-%mm-%ss", "",
        "[SimpleOutput]", f"FilePath={recordings.as_posix()}",
        "RecFormat2=hybrid_mp4",  # an MP4 that survives a crash or power cut
        "RecQuality=Small", f"RecEncoder={'nvenc' if has_nvidia() else 'x264'}", "",
        "[Audio]", "SampleRate=48000", "ChannelSetup=Stereo", "",
    ])


def _source(kind: str, name: str, settings: dict, mixers: int = 255, **extra) -> dict:
    return {"id": kind, "versioned_id": kind, "name": name, "uuid": str(uuid.uuid4()), "settings": settings,
            "mixers": mixers, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5, "enabled": True, "muted": False,
            "push-to-mute": False, "push-to-mute-delay": 0, "push-to-talk": False, "push-to-talk-delay": 0,
            "hotkeys": {}, "deinterlace_mode": 0, "deinterlace_field_order": 0, "monitoring_type": 0,
            "private_settings": {}, **extra}


def _collection(window: str = TTS_WINDOW) -> dict:
    w, h = CANVAS
    game = _source("game_capture", "Tabletop Simulator", {
        "capture_mode": "window", "window": window, "priority": 2,  # 2 = any window of that program
        "capture_audio": False,  # its sound already comes in through Desktop Audio
    })
    item = {"name": game["name"], "source_uuid": game["uuid"], "visible": True, "locked": True, "rot": 0.0,
            "align": 5, "bounds_type": 2, "bounds_align": 0, "bounds_crop": False,  # fit the window to the canvas
            "crop_left": 0, "crop_top": 0, "crop_right": 0, "crop_bottom": 0, "id": 1, "group_item_backup": False,
            "pos": {"x": 0.0, "y": 0.0}, "scale": {"x": 1.0, "y": 1.0}, "bounds": {"x": float(w), "y": float(h)},
            "scale_filter": "disable", "blend_method": "default", "blend_type": "normal",
            "show_transition": {"duration": 0}, "hide_transition": {"duration": 0}, "private_settings": {}}
    scene = _source("scene", NAME, {"custom_size": False, "id_counter": 1, "items": [item]}, mixers=0)
    return {
        "name": NAME,
        "DesktopAudioDevice1": _source("wasapi_output_capture", "Desktop Audio", {"device_id": "default"}),
        "AuxAudioDevice1": _source("wasapi_input_capture", "Mic/Aux", {"device_id": "default"}),
        "sources": [game, scene], "groups": [], "scene_order": [{"name": NAME}],
        "current_scene": NAME, "current_program_scene": NAME, "canvases": [],
        "current_transition": "Fade", "transition_duration": 300, "transitions": [], "quick_transitions": [],
        "saved_projectors": [], "preview_locked": False, "scaling_enabled": False,
        "resolution": {"x": w, "y": h}, "version": 2,
    }


def _get_ini_value(path: Path, section: str, key: str) -> str | None:
    current = None
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1]
        elif current == section and stripped.split("=", 1)[0] == key and "=" in stripped:
            return stripped.split("=", 1)[1]
    return None


def _set_ini_value(path: Path, section: str, key: str, value: str) -> None:
    """Changes one line of an OBS settings file, keeping everything else as it was."""
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    out, in_section, done = [], False, False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section and not done:
                out.append(f"{key}={value}")
                done = True
            in_section = stripped[1:-1] == section
        elif in_section and stripped.split("=", 1)[0] == key:
            if not done:
                out.append(f"{key}={value}")
                done = True
            continue
        out.append(line)
    if not done:
        if not in_section:
            out += ["", f"[{section}]"] if out else [f"[{section}]"]
        out.append(f"{key}={value}")
    _write(path, "\n".join(out) + "\n")


def set_up(recordings: Path) -> None:
    """Makes the Lethal Cuts profile and scenes the first time; after that only the recordings
    folder is kept up to date, so any changes made in OBS itself (a different mic, say) stay."""
    recordings.mkdir(parents=True, exist_ok=True)
    if profile_ini().exists():
        _set_ini_value(profile_ini(), "SimpleOutput", "FilePath", recordings.as_posix())
    else:
        _write(profile_ini(), _profile_text(recordings))
    if not collection_json().exists():
        _write(collection_json(), json.dumps(_collection(), indent=4))
    for name in ("user.ini", "global.ini"):
        ini = config_root() / name
        if ini.exists() or name == "user.ini":
            # Closing OBS while it records normally asks "are you sure?"; Lethal Cuts closes it on purpose.
            _set_ini_value(ini, "General", "ConfirmOnExit", "false")
            # A brand-new OBS opens a setup wizard first, which would get in the way of recording.
            if _get_ini_value(ini, "General", "FirstRun") is None:
                _set_ini_value(ini, "General", "FirstRun", "true")


def is_set_up() -> bool:
    return profile_ini().exists() and collection_json().exists()


# --- recording ---
def start(exe: Path) -> subprocess.Popen:
    """Starts OBS by the clock, on the Lethal Cuts profile and scenes, already recording."""
    return subprocess.Popen(
        [str(exe), "--profile", NAME, "--collection", NAME, "--startrecording", "--minimize-to-tray",
         "--disable-shutdown-check", "--disable-updater"],
        cwd=str(exe.parent),  # OBS only finds its own files when started from its folder
        creationflags=NO_WINDOW)


_user32 = ctypes.windll.user32 if os.name == "nt" else None
_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM) if os.name == "nt" else None


def _main_window(pid: int):
    found = []

    def visit(hwnd, _):
        owner = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            title = ctypes.create_unicode_buffer(512)
            _user32.GetWindowTextW(hwnd, title, 512)
            if title.value.startswith("OBS ") and " - Profile: " in title.value:
                found.append(hwnd)
                return False
        return True

    _user32.EnumWindows(_EnumProc(visit), 0)
    return found[0] if found else None


def close(proc: subprocess.Popen, wait: float = 60.0) -> bool:
    """Closes OBS like clicking its X, so it finishes the recording file properly. True once it's gone."""
    if proc.poll() is not None:
        return True
    hwnd = _main_window(proc.pid)
    if hwnd is None:
        return False
    _user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    try:
        proc.wait(timeout=wait)
        return True
    except subprocess.TimeoutExpired:
        return False


def newest_recording(folder: Path, since: float) -> Path | None:
    """The video OBS made in this folder since a moment in time (time.time())."""
    try:
        files = [f for f in folder.iterdir() if f.suffix.lower() in VIDEO_SUFFIXES and f.stat().st_mtime >= since - 2]
    except OSError:
        return None
    return max(files, key=lambda f: f.stat().st_mtime, default=None)


def recording_started(folder: Path, since: float) -> bool:
    return newest_recording(folder, since) is not None


def wait_for_file_settled(path: Path, seconds: float = 3.0) -> None:
    """OBS can take a moment to finish writing after it closes; wait until the size stops changing."""
    last, end = -1, time.monotonic() + 30
    while time.monotonic() < end:
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size == last:
            return
        last = size
        time.sleep(seconds / 3)
