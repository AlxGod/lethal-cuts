"""Small "?" buttons that explain a control in plain words when clicked."""
from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWhatsThis, QWidget

HELP = {
    "open": "Opens a game recording. iPhone .mov videos work as they are, with nothing to convert. "
            "You can also drag a video file onto the window.",
    "play": "Plays or pauses the video. The Space bar does the same.",
    "speed": "Plays faster so you can skim a long game. 1x is normal speed; 4x gets through an hour in 15 minutes. "
             "Keys 1 to 4 switch speed too.",
    "mark": "Press Mark start (I) when a great moment begins and Mark end (O) when it's over. "
            "The video keeps playing, and the clip is saved the moment you press O.",
    "timeline": "The whole game from left to right. Each numbered bar is a clip. Click anywhere to jump there; "
                "click a bar to pick that clip.",
    "clips": "Every clip you've made. Click a name to rename it. Double-click a row to jump to that clip. "
             "Everything saves by itself.",
    "nudge": "Moves the picked clip's start or end by a tenth of a second, for a cleaner cut. "
             "Hold a button to keep moving. The video stops on the new spot so you can see it.",
    "preview": "Plays the picked clip exactly as the tall phone video will look, with only what's inside the crop box. "
               "Press P or Esc to go back.",
    "delete": "Deletes the picked clip. Changed your mind? Ctrl+Z brings it back.",
    "export": "Turns every clip into a tall 1080x1920 video for Shorts and TikTok: cropped to its box, steady frame rate, "
              "and the volume evened out so it's not too quiet or too loud.",
    "upload": "Opens the YouTube and TikTok upload pages in your browser, plus the folder with your finished clips, "
              "so you can drag each clip in.",
    "crop": "The tall box is what ends up in the phone video. Drag it over the cards and players to keep. "
            "Drag a corner or use the mouse wheel to zoom in. Double-click it for full height.",
}


class HelpButton(QToolButton):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.help_text = text
        self.setText("?")
        self.setObjectName("helpButton")
        self.setToolTip("What does this do?")
        self.setAutoRaise(True)
        self.clicked.connect(self.show_help)

    def show_help(self):
        QWhatsThis.showText(self.mapToGlobal(QPoint(self.width(), self.height())), self.help_text, self)


def with_help(widget: QWidget, key: str, stretch: bool = False) -> QHBoxLayout:
    """Puts a "?" button right after a control."""
    row = QHBoxLayout()
    row.setSpacing(2)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(widget, 1 if stretch else 0)
    row.addWidget(HelpButton(HELP[key]))
    return row
