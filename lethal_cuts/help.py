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
    "mode": "Shorts: mark the best moments and each one becomes a tall clip for Shorts and TikTok.\n\n"
            "Long video: make one normal widescreen video of the whole game. Mark the dead stretches "
            "(shuffling, long thinks, bathroom breaks) and they're cut out; everything else stays in. "
            "Your Shorts clips and your cuts are kept separately, so you can do both with the same recording.",
    "cuts": "The parts that get cut out of the long video. Press I where a dead stretch starts and O where it ends. "
            "Cuts that overlap are joined into one. Double-click a row to jump there.",
    "preview_long": "Plays the long video from where you are, jumping over every cut, so you can check that "
                    "it flows. Press P or Esc to stop.",
    "export_long": "Makes one widescreen video of everything that isn't cut out, with the volume evened out for "
                   "YouTube. The size (1080p or the recording's own size) is in Settings.",
    "clips": "Every clip you've made. Click a name to rename it. Double-click a row to jump to that clip. "
             "Everything saves by itself.",
    "nudge": "Moves the picked clip's start or end by a tenth of a second, for a cleaner cut. "
             "Hold a button to keep moving. The video stops on the new spot so you can see it.",
    "preview": "Plays the picked clip exactly as the tall phone video will look, with only what's inside the crop box. "
               "Press P or Esc to go back.",
    "delete": "Deletes the picked clip. Changed your mind? Ctrl+Z brings it back.",
    "export": "Turns every clip into a tall 1080x1920 video for Shorts and TikTok: cropped to its box, steady frame rate, "
              "and the volume evened out so it's not too quiet or too loud.",
    "post_clips": "Opens the Post tab, which keeps every clip you've exported from every game, ready to watch "
                  "and post one at a time.",
    "post": "Every clip you've exported, newest first. Click one to watch it on the right. \"Post to YouTube\" or "
            "\"Post to TikTok\" opens the upload page and shows the clip in its folder so you can drag it in; its name is "
            "copied for the title. Tick \"Posted\" once it's up, and it moves to the Posted list. "
            "Posting about one a day usually does better than several at once.",
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
