"""Updates: new versions are posted as GitHub Releases. The program checks once when it opens
(one small request) and, if there's a newer one, offers an Update button that downloads the
new installer, runs it quietly and reopens the program. Settings, clips and the Post list are kept.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from . import __version__

REPO = "AlxGod/lethal-cuts"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "Lethal Cuts update"


@dataclass
class Update:
    version: str
    url: str
    size: int
    notes: str


def version_tuple(text: str) -> tuple[int, ...]:
    """'v0.10.2' -> (0, 10, 2), so 0.10 counts as newer than 0.9."""
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3]) or (0,)


def _get(url: str, timeout: float = 15):
    request = urllib.request.Request(url, headers={"User-Agent": f"Lethal-Cuts/{__version__}",
                                                   "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(request, timeout=timeout)


def check(current: str = __version__) -> Update | None:
    """The newest release if it's newer than this copy, otherwise None. Raises OSError/ValueError on problems."""
    with _get(LATEST) as response:
        data = json.loads(response.read().decode("utf-8"))
    tag = str(data.get("tag_name", ""))
    if version_tuple(tag) <= version_tuple(current):
        return None
    for asset in data.get("assets", []):
        name = str(asset.get("name", ""))
        if name.lower().endswith(".exe") and "setup" in name.lower():
            return Update(tag.lstrip("vV"), str(asset["browser_download_url"]), int(asset.get("size", 0)),
                          str(data.get("body") or ""))
    return None


def should_check() -> bool:
    """Only the installed program checks; a copy run from the source code doesn't."""
    return bool(getattr(sys, "frozen", False))


def clean_old_download() -> None:
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)


def run_installer(installer: Path) -> None:
    """Starts the new installer quietly; it closes this program, updates it and opens it again."""
    subprocess.Popen([str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NOCANCEL", "/RESTART"],
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))


class Checker(QObject):
    """Runs check() off the main thread, so a slow connection never freezes the window."""
    found = Signal(object)    # Update or None
    failed = Signal(str)

    def run(self):
        try:
            self.found.emit(check())
        except Exception as e:  # no internet, GitHub busy, etc.: just try again next time
            self.failed.emit(str(e))


class _Downloader(QObject):
    progress = Signal(int, int)   # bytes so far, total
    done = Signal(str, str)       # file path, error

    def __init__(self, update: Update):
        super().__init__()
        self.update, self.cancelled = update, False

    def run(self):
        target = DOWNLOAD_DIR / f"Lethal Cuts Setup {self.update.version}.exe"
        partial = target.with_suffix(".part")
        try:
            DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
            with _get(self.update.url, timeout=30) as response, open(partial, "wb") as out:
                total = int(response.headers.get("Content-Length") or self.update.size or 0)
                got = 0
                while not self.cancelled:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    got += len(chunk)
                    self.progress.emit(got, total)
            if self.cancelled:
                partial.unlink(missing_ok=True)
                self.done.emit("", "cancelled")
                return
            if total and got != total:
                raise OSError(f"the download stopped early ({got} of {total} bytes)")
            partial.replace(target)
            self.done.emit(str(target), "")
        except Exception as e:
            partial.unlink(missing_ok=True)
            self.done.emit("", str(e))


class UpdateDialog(QDialog):
    """Downloads the update with a progress bar. accepted with .installer set when it's ready to run."""

    def __init__(self, update: Update, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Updating Lethal Cuts")
        self.setMinimumWidth(460)
        self.installer: Path | None = None
        title = QLabel(f"Downloading Lethal Cuts {update.version}...")
        title.setObjectName("panelTitle")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.detail = QLabel("Your settings, clips and Post list are kept.")
        self.detail.setObjectName("dimLabel")
        self.detail.setWordWrap(True)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.bar)
        layout.addWidget(self.detail)
        layout.addLayout(buttons)
        self.worker = _Downloader(update)
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.done.connect(self.thread.quit)
        self.thread.start()

    def _on_progress(self, got: int, total: int):
        if total:
            self.bar.setValue(int(got * 1000 / total))
            self.detail.setText(f"{got / 2**20:.0f} of {total / 2**20:.0f} MB. Your settings, clips and Post list are kept.")

    def _on_done(self, path: str, error: str):
        if path:
            self.installer = Path(path)
            self.accept()
        elif error != "cancelled":
            self.cancel_btn.setText("Close")
            self.bar.setValue(0)
            self.detail.setText(f"The download didn't work: {error}\n\nCheck the internet connection and try again "
                                f"later, or download the new installer yourself from {RELEASES_PAGE}")
            self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)

    def reject(self):
        self.worker.cancelled = True
        self.thread.quit()
        self.thread.wait(5000)
        super().reject()
