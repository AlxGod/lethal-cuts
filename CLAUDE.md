# Lethal Cuts

A Windows program that turns long, in-person Magic Commander game recordings (iPhone .mov, HEVC) into vertical 9:16 clips for YouTube Shorts and TikTok. The full feature plan is the Google Doc "Lethal Cuts – Build Plan". It is built in phases, and each step is tested and signed off before the next one starts.

## How it's organized

- `lethal_cuts/app.py`: starts the program and sets the dark theme. Run with `python -m lethal_cuts [video]`, or double-click `Run Lethal Cuts.bat`.
- `lethal_cuts/main_window.py`: the main window. It holds the player, controls, keys (Space, I, O, Esc, Delete, Ctrl+Z), marking logic and autosave.
- `lethal_cuts/project.py`: the `Clip` and `Project` data. Each video `game.mov` gets `game.lcproj` (JSON) next to it, written through a temporary file so a crash can't corrupt it.
- `lethal_cuts/timeline.py`: the custom-drawn timeline (clip bars, start mark, playhead, click to seek).
- `lethal_cuts/clip_list.py`: the side table of clips (number, editable name, start, length).
- `lethal_cuts/video_view.py`: the video, drawn in a QGraphicsView so overlays such as the crop box can sit on top.

## Choices made

- Video playback uses Qt's own player (QMediaPlayer with Qt's bundled FFmpeg backend), not libmpv. It plays 4K 10-bit HEVC .mov at full speed and 4x, and seeks to the exact frame, with nothing extra to install. Tested on 2026-10-16 on a generated sample.
- Exports must even out loudness automatically (two-pass loudnorm to -14 LUFS, with a true-peak ceiling).

## Testing

Test offline with a small generated HEVC clip in a temp folder, never in this folder. For example:
`ffmpeg -f lavfi -i testsrc2=size=3840x2160:rate=30:duration=20 -f lavfi -i sine=frequency=330:duration=20 -vf "select='not(eq(mod(n,10),3))',format=yuv420p10le" -fps_mode vfr -c:v libx265 -preset ultrafast -tag:v hvc1 -c:a aac test.mov`
(dropping every 10th frame makes it variable frame rate like an iPhone). Drive the window with `QTest` key clicks and save `window.grab()` screenshots.
