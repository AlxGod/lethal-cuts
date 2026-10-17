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
<ul>
<li><b>Record in 4K at 30 fps.</b> The tall Shorts clip is cut out of the middle of the picture, so starting in 4K keeps it sharp.
On iPhone: Settings &gt; Camera &gt; Record Video &gt; 4K at 30 fps.</li>
<li><b>Turn HDR Video off.</b> iPhone HDR often looks washed out after YouTube and TikTok process it. Lethal Cuts converts it,
but recording without it looks best. On iPhone: Settings &gt; Camera &gt; Record Video &gt; HDR Video off.</li>
<li><b>Keep the "High Efficiency" format on</b> (Settings &gt; Camera &gt; Formats). It keeps files about half the size.</li>
<li><b>Clear space on the phone first.</b> A 2-hour game in 4K is about 20 GB.</li>
<li><b>Plug the phone in</b> and turn on Do Not Disturb, so a dead battery or a phone call doesn't stop the recording.</li>
<li><b>Mount the phone over the table</b>, looking down, so every player's cards are in the shot. Try not to bump it during the game:
the crop box carries over from clip to clip because the camera usually stays put.</li>
<li><b>Clicker and "clip that"</b> <span class="soon">(coming in a later update)</span>: press a dog-training clicker or say
"clip that" when something great happens, and Lethal Cuts will drop a marker there for you.</li>
</ul>
"""

STEPS = """
<a name="steps"></a><h2>Step by step</h2>
<ol>
<li><b>Open the game video.</b> Click <i>Open video</i>, or drag the file onto the window. iPhone .mov files work as they are.</li>
<li><b>Skim for good moments.</b> Use the 2x, 3x or 4x speed buttons, the arrow keys, or click anywhere on the timeline.</li>
<li><b>Mark a clip.</b> Press <span class="key">{mark_start}</span> where the moment starts and <span class="key">{mark_end}</span>
where it ends. The video keeps playing while you mark. The clip appears as a numbered bar on the timeline and in the list.</li>
<li><b>Name it.</b> Click the clip's name in the list (or press F2) and type something like "combo turn".</li>
<li><b>Fine-tune if needed.</b> The <i>-0.1s</i> and <i>+0.1s</i> buttons move the start or end a tenth of a second at a time.
Hold a button to keep going.</li>
<li><b>Place the crop box.</b> With a clip picked, drag the tall box over the part of the table to keep. Drag a corner, or use the mouse
wheel, to zoom in. Double-click the box to make it full height again. The next clip reuses the same box.</li>
<li><b>Preview it.</b> Press <span class="key">{preview}</span> to watch the clip exactly as the phone video will look.</li>
<li><b>Export.</b> Click <i>Export all clips</i>. Each clip becomes a 1080x1920 video with its volume evened out for Shorts and TikTok.</li>
<li><b>Upload.</b> Click <i>Upload</i>. YouTube and TikTok open in your browser along with the clips folder. Drag each clip in.</li>
</ol>
<p>Your clips save by themselves into a small <i>.lcproj</i> file next to the video. Close the program any time and open the
video again later to pick up where you left off.</p>
"""

SHORTS = """
<a name="shorts"></a><h2>Shorts tips</h2>
<ul>
<li><b>Hook them in the first 2 seconds.</b> Start right before the big moment, not at the start of the turn.</li>
<li><b>Aim for 20 to 45 seconds.</b> Short clips get watched to the end and replayed, which helps them spread.</li>
<li><b>Show the cards.</b> Place the crop box so viewers can see what was played.</li>
<li><b>Catch the reactions.</b> The table's reaction is often the best part. Leave a second or two after the play.</li>
<li><b>End on the payoff.</b> Stop right after the big moment lands. Don't let it trail off.</li>
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
                    ' &nbsp;|&nbsp; <a href="#hotkeys">Hotkeys</a> &nbsp;|&nbsp; <a href="#shorts">Shorts tips</a></p>')
        html = (f"<h1>How to use Lethal Cuts</h1>{contents}{RECORDING}"
                f"{STEPS.format(**keys)}{hotkeys}{SHORTS}")
        self.browser.setHtml(html)
