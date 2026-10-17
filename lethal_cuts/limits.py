"""How long a video YouTube and TikTok accept, so Lethal Cuts can warn before it's too late.

YouTube Shorts can be up to 3 minutes. YouTube takes normal videos up to 15 minutes until the
account has verified a phone number (free, once), then up to 12 hours. TikTok takes uploads up
to 60 minutes.
"""
from __future__ import annotations

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .project import format_time

SHORTS_MAX = 3 * 60
YOUTUBE_UNVERIFIED_MAX = 15 * 60
TIKTOK_MAX = 60 * 60
YOUTUBE_VERIFY = "https://www.youtube.com/verify"

VERIFY_TEXT = ("Over 15 minutes: YouTube needs the account's phone number verified first "
               "(free, takes a minute).")


def too_long_for_tiktok(length: float) -> bool:
    return length > TIKTOK_MAX


def needs_verified_youtube(length: float, verified: bool) -> bool:
    return length > YOUTUBE_UNVERIFIED_MAX and not verified


def long_video_problems(length: float, verified: bool) -> list[str]:
    """Plain-English warnings for a long video of this length (empty when it can go anywhere)."""
    problems = []
    if too_long_for_tiktok(length):
        problems.append(f"{format_time(length, tenths=False)} is over TikTok's 60 minutes, so it's YouTube only "
                        "(unless it's cut under an hour).")
    if needs_verified_youtube(length, verified):
        problems.append(VERIFY_TEXT)
    return problems


def short_problems(length: float) -> list[str]:
    if length > SHORTS_MAX:
        return ["Over 3 minutes, so YouTube posts it as a normal video, not a Short. TikTok takes it as it is."]
    return []


class LimitNote(QFrame):
    """A gold note about upload limits, with buttons for fixing the YouTube one."""
    verified = Signal()  # "my account is verified now, stop telling me"

    def __init__(self, stacked: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("limitNote")
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.verify_btn = QPushButton("Verify my account")
        self.verify_btn.setToolTip("Opens YouTube's phone verification page in your browser")
        self.verify_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(YOUTUBE_VERIFY)))
        self.done_btn = QPushButton("It's verified, stop telling me")
        self.done_btn.setToolTip("Hides this note for good. You can change it back in Settings.")
        self.done_btn.clicked.connect(self.verified.emit)
        buttons = QVBoxLayout() if stacked else QHBoxLayout()  # stacked fits a narrow side panel
        buttons.setSpacing(4)
        buttons.addWidget(self.verify_btn)
        buttons.addWidget(self.done_btn)
        if not stacked:
            buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.addWidget(self.text)
        layout.addLayout(buttons)
        self.hide()

    def show_problems(self, problems: list[str]) -> None:
        self.text.setText("\n\n".join(problems))
        fixable = VERIFY_TEXT in problems
        self.verify_btn.setVisible(fixable)
        self.done_btn.setVisible(fixable)
        self.setVisible(bool(problems))
