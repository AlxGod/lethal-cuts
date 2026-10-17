"""Builds everything to hand over: the packaged program, the installer, and the handoff zip.

    python packaging/build.py            # all three
    python packaging/build.py --app      # only the packaged program (for testing)

Needs: Python with the packages in requirements.txt, PyInstaller, and Inno Setup 6
(free, from jrsoftware.org, or: winget install JRSoftware.InnoSetup).
Build leftovers and the downloaded FFmpeg are kept in %TEMP%\\pyi-build\\LethalCuts so
rebuilds are fast; the installer and zip go in dist\\ in the project folder.
Commit your changes first: the zip's source code comes from the latest git save point.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lethal_cuts import __version__  # noqa: E402

BUILD = Path(tempfile.gettempdir()) / "pyi-build" / "LethalCuts"
FFMPEG_DIR = BUILD / "ffmpeg"
# FFmpeg 9.0, "shared" build (its two programs share their parts, so it's smaller).
# GPL edition, because it includes the x264 encoder used for exports.
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n9.0-latest-win64-gpl-shared-9.0.zip"
APP_NAME = "Lethal Cuts"
DIST = ROOT / "dist"


def step(text: str) -> None:
    print(f"\n=== {text}", flush=True)


def ensure_ffmpeg() -> None:
    if (FFMPEG_DIR / "ffmpeg.exe").exists() and (FFMPEG_DIR / "ffprobe.exe").exists():
        return
    step("Downloading FFmpeg (about 85 MB, once)")
    download = BUILD / "ffmpeg-download"
    download.mkdir(parents=True, exist_ok=True)
    archive = download / "ffmpeg.zip"
    urllib.request.urlretrieve(FFMPEG_URL, archive)
    FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            base = name.split("/")[-1]
            if ("/bin/" in name and base and base != "ffplay.exe") or base == "LICENSE.txt":
                with z.open(name) as src, open(FFMPEG_DIR / base, "wb") as dst:
                    shutil.copyfileobj(src, dst)


def ensure_icon() -> None:
    if not (ROOT / "assets" / "icon.ico").exists():
        step("Drawing the icon")
        subprocess.run([sys.executable, str(ROOT / "packaging" / "make_icon.py")], check=True,
                       env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


def build_app() -> Path:
    """Packs the program with PyInstaller into one folder with Lethal Cuts.exe."""
    ensure_ffmpeg()
    ensure_icon()
    step("Packing the program with PyInstaller")
    shutil.rmtree(BUILD / "dist", ignore_errors=True)  # PyInstaller leaves old files behind otherwise
    icon = ROOT / "assets" / "icon.ico"
    sep = ";"  # PyInstaller's source;destination separator on Windows
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed",
        "--name", APP_NAME,
        "--icon", str(icon),
        "--contents-directory", ".",  # keep everything beside the .exe, so vendor\ffmpeg sits next to it
        "--workpath", str(BUILD / "work"), "--specpath", str(BUILD / "spec"), "--distpath", str(BUILD / "dist"),
        "--paths", str(ROOT),
        "--add-data", f"{icon}{sep}.",
        "--exclude-module", "tkinter", "--exclude-module", "numpy", "--exclude-module", "PIL",
        str(ROOT / "packaging" / "launch.py"),
    ], check=True)
    app = BUILD / "dist" / APP_NAME
    # FFmpeg is copied in afterwards, not given to PyInstaller: PyInstaller would follow
    # ffmpeg.exe's DLLs and put a second copy of all of them beside Lethal Cuts.exe (+180 MB).
    shutil.copytree(FFMPEG_DIR, app / "vendor" / "ffmpeg", dirs_exist_ok=True)
    print("Program folder:", app)
    return app


def find_iscc() -> Path:
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", "")):
        for folder in ("Inno Setup 6", r"Programs\Inno Setup 6"):
            candidate = Path(base) / folder / "ISCC.exe"
            if candidate.exists():
                return candidate
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    sys.exit("Inno Setup 6 wasn't found. Install it (winget install JRSoftware.InnoSetup) and run this again.")


def build_installer(app: Path) -> Path:
    step("Building the installer with Inno Setup")
    DIST.mkdir(exist_ok=True)
    subprocess.run([str(find_iscc()), f"/DAppVersion={__version__}", f"/DSourceDir={app}", f"/DOutputDir={DIST}",
                    str(ROOT / "packaging" / "installer.iss")], check=True)
    installer = DIST / f"{APP_NAME} Setup {__version__}.exe"
    print("Installer:", installer)
    return installer


def build_zip(installer: Path) -> Path:
    """The handoff zip: installer, README, and the source code from the latest git save point."""
    step("Making the handoff zip")
    source_zip = BUILD / "source.zip"
    subprocess.run(["git", "-C", str(ROOT), "archive", "--format=zip", "--prefix=Lethal Cuts source/",
                    "-o", str(source_zip), "HEAD"], check=True)
    out = DIST / f"{APP_NAME} {__version__}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(installer, installer.name)
        z.write(ROOT / "README.txt", "README.txt")
        with zipfile.ZipFile(source_zip) as src:
            for item in src.infolist():
                z.writestr(item, src.read(item.filename))
    print("Handoff zip:", out, f"({out.stat().st_size // 2**20} MB)")
    return out


def main() -> None:
    app = build_app()
    if "--app" in sys.argv:
        return
    installer = build_installer(app)
    build_zip(installer)


if __name__ == "__main__":
    main()
