"""Small "?" buttons that explain a control in plain words when clicked."""
from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWhatsThis, QWidget

HELP = {
    "open": "Opens a game recording. iPhone .mov videos work as they are, with nothing to convert. "
            "You can also drag a video file onto the window.",
    "play": "Plays or pauses the video. The Space bar does the same.",
    "volume": "How loud the video plays while you edit. It only changes what you hear here: exported Shorts and "
              "long videos always have their volume evened out for YouTube and TikTok, whatever this is set to.",
    "speed": "Plays faster so you can skim a long game. 1x is normal speed; 4x gets through an hour in 15 minutes. "
             "Keys 1 to 4 switch speed too.",
    "mark": "Press Mark start (I) when a great moment begins and Mark end (O) when it's over. "
            "The video keeps playing, and the clip is saved the moment you press O.",
    "timeline": "The whole game from left to right. Each numbered bar is a clip. Click anywhere to jump there; "
                "click a bar to pick that clip.\n\n"
                "Long game? Scroll the mouse wheel over the timeline (or click +) to zoom in, so a few minutes fill "
                "the bar. The bar under it slides along; Shift + wheel does too. Double-click the timeline to see "
                "the whole game again.\n\n"
                "Gold flags are moments marked while recording.",
    "overlays": "Cards and text shown on top of the video. + Card searches every Magic card and puts the one you "
                "pick where the playhead is; + Text does the same with words. For text, Style picks a ready-made look "
                "(Hook, Callout, Name tag, Plain) and Edit look changes the font, colors, outline, box and shadow. "
                "Put *stars* around words to highlight them. + Pause (Shorts) freezes the clip with a \"What's your "
                "play?\" countdown; + Title card (long videos) opens the video with the series name and episode. "
                "Drag it on the video to place it; drag its corner, use the Size slider or scroll the mouse wheel "
                "over it to resize it. Its bar in the strip under the timeline sets when it shows: drag the bar to "
                "move it, or drag either end to make it show longer or shorter.\n\n"
                "What you see is what gets exported. Shorts and the long video each have their own: text added while "
                "making Shorts shows in any clip that covers that moment.",
    "cards": "Type any Magic card's name and pick it from the list. Every printing with a picture shows, newest "
             "first: click the artwork you want (double-click adds it straight away). Double-faced cards have a "
             "button to show the other side.\n\n"
             "My decks is optional: paste your own decklists (from Moxfield, Archidekt, or one card per line) and "
             "their cards are one click away next time.\n\n"
             "Card details and pictures come from Scryfall, the free card database. Each picture downloads once and "
             "is kept, so it works offline after that.",
    "join": "How the long video joins up where this dead stretch is cut out:\n\n"
            "Hard cut: straight to the next part (the usual choice, and the default).\n"
            "Crossfade: the two parts blend into each other for half a second.\n"
            "Dip to black: fades to black and back, good for a big jump in time (like between games).\n"
            "Whip: a quick blurred smear, for energy.\n\n"
            "Default uses the choice in Settings > Export, so you can change every cut at once. A transition "
            "overlaps the two parts slightly, so the video gets that much shorter. Press P to see it in the "
            "preview.",
    "moments": "Moments you marked while recording, by pressing the moment key (F8 unless you changed it) when "
               "something great happened. Each one is a gold flag on the timeline, with the few minutes before it "
               "shaded gold. Moment > (key N) jumps to the start of the next one, so you can watch the lead-up and "
               "mark the best part with I and O, without watching the whole game. < Moment (Shift+N) goes back.\n\n"
               "Playing in person? Press a dog-training clicker when something great happens. Teach Lethal Cuts "
               "your clicker once (Clicker...), and every video you open gets a cyan flag at each click. Someone "
               "saying \"clip that\" gets a pink flag.",
    "record": "For games played on the computer, like Tabletop Simulator. Click Start recording and Lethal Cuts "
              "starts OBS (the free recorder) by the clock, recording the game window, your computer's sound "
              "(the game and your friends on Discord) and your microphone. Click Stop recording when the game's "
              "over and it opens in the Editor, ready to clip or cut. Recordings go in the Recordings folder.\n\n"
              "Recording in person on a phone? Skip this tab: copy the video to the PC and open it in the Editor.",
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
