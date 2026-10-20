"""The Guide tab: recording tips, a step-by-step walkthrough, the hotkey cheat sheet and Shorts tips."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from .settings import ACTIONS, Settings

CSS = """
body { color: #e8e2f4; font-family: 'Segoe UI'; font-size: 11pt; }
h1 { color: #f0b840; font-size: 18pt; margin-bottom: 4px; }
h2 { color: #f0b840; font-size: 14pt; margin-top: 22px; margin-bottom: 6px; }
a { color: #c9a6ff; }
li { margin-bottom: 5px; }
.soon { color: #8a80a0; }
td { padding: 3px 18px 3px 0; }
.key { font-family: Consolas; color: #ffffff; background: #2c2440; }
"""

RECORDING = """
<a name="recording"></a><h2>Recording tips</h2>
<p><b>Playing on the computer (Tabletop Simulator)?</b> Use the <i>Record</i> tab: start the game, click <i>Start recording</i>,
and click <i>Stop recording</i> when you're done. Lethal Cuts records with OBS (free; get it from obsproject.com) and opens the
recording in the Editor. It records the game, your computer's sound (including Discord) and your microphone.</p>
<p><b>Mark the great moments as they happen.</b> While recording, press the moment key (<b>F8</b>, or whichever you picked in
Settings &gt; Recording) when something great happens, even with the game in front. Nothing pops up, so keep playing. The
recording opens with a gold flag at each press, and <i>Moment &gt;</i> jumps to a few minutes before it, so you can find the best
bits of a 3-hour game without watching all 3 hours.</p>
<p><b>Leave room on the drive.</b> A recording takes several GB an hour. The Record tab shows how many hours fit and warns
before you start if a long game won't. Recordings you've already made your videos from are safe to delete.</p>
<p><b>Playing in person?</b> Record on a phone:</p>
<ul>
<li><b>Record in 4K at 30 fps.</b> The tall Shorts clip is cut out of the middle of the picture, so starting in 4K keeps it sharp.
On iPhone: Settings &gt; Camera &gt; Record Video &gt; 4K at 30 fps.</li>
<li><b>Turn HDR Video off.</b> iPhone HDR often looks washed out after YouTube and TikTok process it. Lethal Cuts converts it,
but recording without it looks best. On iPhone: Settings &gt; Camera &gt; Record Video &gt; HDR Video off.</li>
<li><b>Keep the "High Efficiency" format on</b> (Settings &gt; Camera &gt; Formats). It keeps files about half the size.</li>
<li><b>Clear space on the phone first.</b> 4K takes about 10 GB an hour, so a 3-hour game needs about 30 GB free.</li>
<li><b>Plug the phone in</b> and turn on Do Not Disturb, so a dead battery or a phone call doesn't stop the recording.</li>
<li><b>Mount the phone over the table</b>, looking down, so every player's cards are in the shot. Try not to bump it during the game:
the crop box carries over from clip to clip because the camera usually stays put.</li>
<li><b>Mark great moments with a clicker.</b> Keep a dog-training clicker (a few dollars at a pet store) by the table and
click it when something great happens. Each click becomes a cyan flag on the timeline, and <i>Moment &gt;</i> jumps to the
minutes before it, just like F8.</li>
</ul>
<p><b>Teaching Lethal Cuts your clicker (once).</b> Open a recording with a click in it, play it at 1x and stop with the
playhead right on a click. Click <i>Clicker...</i> (under the timeline), then <i>Learn the click</i>, then <i>Find clicks in
this video</i>. From then on, every video you open is checked for clicks by itself (it takes about a minute for a 3-hour game).
Lethal Cuts tells clicks apart from card slaps and shuffling by their sound; if it misses some, move the slider towards
<i>Finds more</i>, and if it flags other sounds, towards <i>Stricter</i>.</p>
"""

STEPS = """
<a name="steps"></a><h2>Making Shorts, step by step</h2>
<ol>
<li><b>Open the game video.</b> Click <i>Open video</i>, or drag the file onto the window. iPhone .mov files work as they are.</li>
<li><b>Skim for good moments.</b> Use the 2x, 3x or 4x speed buttons, the arrow keys, or click anywhere on the timeline.
Marked moments while recording? Press <span class="key">{next_moment}</span> to jump to each one. On a long game, scroll the mouse
wheel over the timeline to zoom in.</li>
<li><b>Mark a clip.</b> Press <span class="key">{mark_start}</span> where the moment starts and <span class="key">{mark_end}</span>
where it ends. The video keeps playing while you mark. The clip appears as a numbered bar on the timeline and in the list.</li>
<li><b>Name it.</b> Click the clip's name in the list (or press F2) and type something like "combo turn".</li>
<li><b>Fine-tune if needed.</b> The <i>-0.1s</i> and <i>+0.1s</i> buttons move the start or end a tenth of a second at a time.
Hold a button to keep going.</li>
<li><b>Place the crop box.</b> With a clip picked, drag the tall box over the part of the table to keep. Drag a corner, or use the mouse
wheel, to zoom in. Double-click the box to make it full height again. The next clip reuses the same box.</li>
<li><b>Preview it.</b> Press <span class="key">{preview}</span> to watch the clip exactly as the phone video will look.</li>
<li><b>Export.</b> Click <i>Export all clips</i>. Each clip becomes a 1080x1920 video with its volume evened out for Shorts and TikTok.</li>
<li><b>Post them one at a time.</b> Your finished clips wait in the <i>Post</i> tab, from every game you've done. Click one to watch it,
then <i>Post to YouTube</i> or <i>Post to TikTok</i>: the upload page opens and the clip is highlighted in its folder, so you can drag it in
(its name is copied, so paste it as the title). Tick <i>Posted</i> once it's up and it moves to the Posted list.</li>
</ol>
<p>Your clips save by themselves into a small <i>.lcproj</i> file next to the video. Close the program any time and open the
video again later to pick up where you left off.</p>
"""

LONG = """
<a name="long"></a><h2>Making a long video</h2>
<p>A long video is one normal widescreen video of the whole game for YouTube, with the dead stretches cut out.</p>
<ol>
<li><b>Open the game video</b> in the Editor and click <i>Long video</i> at the top right.</li>
<li><b>Mark what to cut.</b> Press <span class="key">{mark_start}</span> where a dead stretch starts (shuffling, a long think,
a break) and <span class="key">{mark_end}</span> where it ends. It shows striped red on the timeline. Cuts that overlap join into one.</li>
<li><b>Pick how each cut joins up (optional).</b> With a cut picked, <i>Join</i> (under the fine-tune buttons) chooses
<i>Hard cut</i> (straight on, the usual choice), <i>Crossfade</i> (the two parts blend for half a second), <i>Dip to black</i>
(a fade to black and back, good for a big jump in time) or <i>Whip</i> (a quick blurred smear, for energy). The cut list's
<i>Join</i> column shows each one. To change every cut at once, pick the default in Settings &gt; Export.</li>
<li><b>Check the flow.</b> Press <span class="key">{preview}</span> to watch from where you are with every cut skipped. The joins
play in the preview too.</li>
<li><b>Export.</b> Click <i>Export long video</i>. It goes in the <i>Long videos</i> folder and the Post tab. A long game takes a
while to export; the window shows how long is left. The size (1080p or the recording's own size) is in Settings.</li>
</ol>
<p>Your Shorts clips and your cuts are kept separately, so you can make both from the same recording. Switch back with <i>Shorts</i>.</p>
<p><b>How long can it be?</b> YouTube takes videos up to 15 minutes until the account has a verified phone number (free, once,
at youtube.com/verify), then up to 12 hours. TikTok takes up to 60 minutes. Lethal Cuts tells you while you edit if the video is
over a limit; once the YouTube account is verified, click <i>It's verified, stop telling me</i>.</p>
"""

ON_SCREEN = """
<a name="onscreen"></a><h2>Cards and text on screen</h2>
<p>Pop a card up while you talk about it, or put words on the video. Both work on Shorts and long videos, and what you see in the
Editor is exactly what gets exported. Find them in the Editor's <i>On screen</i> tab (next to <i>Clips</i>).</p>
<p><b>Adding a card</b></p>
<ol>
<li>Move the playhead to where the card should appear, then click <i>+ Card</i>.</li>
<li>Type the card's name. Suggestions appear after two letters: click the right one (or press Enter for the closest match).
Every Magic card is there, not just your decks.</li>
<li><b>Pick the right printing.</b> Every printing with a picture shows, newest first, with its set code, number and year
under it (hover for the set's full name). Type in the <i>Find a printing</i> box to narrow it down, e.g. <i>Commander Masters</i>,
<i>CMM</i> or <i>2023</i>. The set code and number are printed on the bottom left of the real card, so you can match it to the
one in your hand. The big picture on the right shows exactly what goes on the video.</li>
<li>Double-faced card? Click <i>Show the other side</i> to pick which side shows.</li>
<li>Click <i>Add to video</i> (or double-click the artwork). The card shows for 5 seconds.</li>
</ol>
<p><b>My decks (optional).</b> Paste your own decklists once (click <i>New deck</i> in the card window) and their cards are a click
away from then on. Export the list from Moxfield or Archidekt and keep the set codes in it: then each card opens straight on the
exact printing you own. Lists typed one card per line work too. Other people's decks aren't needed: search finds any card.</p>
<p><b>Adding text.</b> Move the playhead there and click <i>+ Text</i>, then type the words in the <i>Selected</i> box.
It shows for 4 seconds. Put <b>*stars*</b> around a word to make it stand out in the highlight color:
<i>That's *LETHAL*</i> shows LETHAL in yellow.</p>
<p><b>Text styles.</b> Pick one from <i>Style</i>. Each also moves the text to where that style usually goes:</p>
<ul>
<li><b>Hook</b>: a big headline in capitals at the top, for the first seconds of a Short ("HE HAD THE ANSWER").</li>
<li><b>Callout</b>: dark words in a gold box, to point something out ("Turn 4 combo").</li>
<li><b>Name tag</b>: a small dark tag in the bottom corner with a gold edge, for who's who ("Alex, Atraxa").</li>
<li><b>Plain</b>: white words with a black outline.</li>
</ul>
<p>Click <i>Edit look</i> to change the font, the text and highlight colors, the outline, the box (its color can be see-through)
and the shadow, or to put it all in CAPS. The next text you add starts in the style you used last.</p>
<p><b>Typewriter.</b> Set <i>Comes in</i> to <i>Typewriter</i> and the words type themselves out letter by letter.
The typing speeds up if needed so it finishes with time left to read it.</p>
<p><b>"What's your play?" pause card (Shorts).</b> Find the moment just before a big decision, then click <i>+ Pause</i>.
The Short freezes on that frame, darkens, and shows the question with a countdown (3, 2, 1) and a soft tick each second,
then carries on so viewers see what was played. It gets people commenting what they'd have done. Change the words in the
<i>Selected</i> box, and <i>Countdown</i> sets how many seconds (2 to 10). Press <span class="key">{preview}</span> to watch
it in the vertical preview.</p>
<p><b>Series title card (long videos).</b> In <i>Long video</i> mode, click <i>+ Title card</i>: type the series name, the
episode number and who's playing, and add up to four commanders from Scryfall. Their art fills the background and their
cards fan out along the bottom. It opens the long video for a few seconds, then dips to black into the game. The episode
number counts up by itself after each long video you export with a title card.</p>
<p><b>Placing and timing them</b></p>
<ul>
<li><b>Where:</b> drag it on the video. Drag its gold corner, use the <i>Size</i> slider, or scroll the mouse wheel over it to resize.
On Shorts it sits inside the tall crop box, so you see exactly where it lands on the phone video.</li>
<li><b>When:</b> each one has a bar in the strip under the timeline. Drag the bar to move it; drag either end to make it show
longer or shorter. <i>Shows for</i> sets the length in seconds.</li>
<li><b>How it moves:</b> <i>Comes in</i> and <i>Goes away</i> pick Pop, Fade, Slide or None (text can also use Typewriter).</li>
<li><b>Changing a card:</b> pick it and click <i>Change card...</i> to swap the card or the printing.</li>
<li><b>Deleting:</b> pick it and press Delete (or the Delete button). Ctrl+Z brings it back.</li>
</ul>
<p>Shorts and the long video each keep their own cards and text. A card added while making Shorts appears in any clip that
covers that moment. In a long video, one that runs into a cut just ends where the cut starts.</p>
<p>Card pictures come from Scryfall, the free card database, and each one is downloaded once and kept, so searching needs the
internet but a card you've used before works offline.</p>
"""

SHORTS = """
<a name="shorts"></a><h2>Shorts tips</h2>
<ul>
<li><b>Hook them in the first 2 seconds.</b> Start right before the big moment, not at the start of the turn.</li>
<li><b>Aim for 20 to 45 seconds.</b> Short clips get watched to the end and replayed, which helps them spread.
Over 3 minutes, YouTube won't count it as a Short at all.</li>
<li><b>Show the cards.</b> Place the crop box so viewers can see what was played.</li>
<li><b>Catch the reactions.</b> The table's reaction is often the best part. Leave a second or two after the play.</li>
<li><b>End on the payoff.</b> Stop right after the big moment lands. Don't let it trail off.</li>
<li><b>Post about one a day.</b> A steady stream does better than a pile at once. The Post tab keeps the rest waiting for you.</li>
</ul>
"""


class GuidePage(QWidget):
    replay_walkthrough = Signal()

    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.s = s
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.document().setDefaultStyleSheet(CSS)
        replay = QPushButton("Replay the first-time walkthrough")
        replay.clicked.connect(self.replay_walkthrough.emit)
        top = QHBoxLayout()
        title = QLabel("Guide")
        title.setObjectName("panelTitle")
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(replay)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.addLayout(top)
        layout.addWidget(self.browser, 1)
        self.refresh()

    def refresh(self, s: Settings | None = None):
        """Rebuilds the page so the hotkeys shown always match Settings."""
        if s is not None:
            self.s = s
        keys = {a: escape(self.s.key(a)) for a in ACTIONS}
        rows = "".join(
            f'<tr><td><span class="key">&nbsp;{keys[a]}&nbsp;</span></td><td>{escape(label)}</td></tr>'
            for a, (label, _) in ACTIONS.items()
        )
        rows += '<tr><td><span class="key">&nbsp;F2&nbsp;</span></td><td>Rename the selected clip</td></tr>'
        hotkeys = f'<a name="hotkeys"></a><h2>Hotkey cheat sheet</h2><p>Change any of these in Settings.</p><table>{rows}</table>'
        contents = ('<p><a href="#recording">Recording tips</a> &nbsp;|&nbsp; <a href="#steps">Step by step</a>'
                    ' &nbsp;|&nbsp; <a href="#long">Long videos</a> &nbsp;|&nbsp; <a href="#onscreen">Cards and text</a>'
                    ' &nbsp;|&nbsp; <a href="#hotkeys">Hotkeys</a>'
                    ' &nbsp;|&nbsp; <a href="#shorts">Shorts tips</a></p>')
        html = (f"<h1>How to use Lethal Cuts</h1>{contents}{RECORDING}"
                f"{STEPS.format(**keys)}{LONG.format(**keys)}{ON_SCREEN.format(**keys)}{hotkeys}{SHORTS}")
        self.browser.setHtml(html)
