# Lethal Cuts

A Windows program that turns long, in-person Magic Commander game recordings (iPhone .mov, HEVC) into vertical 9:16 clips for YouTube Shorts and TikTok. The full feature plan is the Google Doc "Lethal Cuts – Build Plan". It is built in phases, and each step is tested and signed off before the next one starts.

## How it's organized

- `lethal_cuts/app.py`: starts the program and sets the dark theme. Run with `python -m lethal_cuts [video]`, or double-click `Run Lethal Cuts.bat`.
- `lethal_cuts/main_window.py`: the main window. It holds the player, controls, keys (Space, I, O, Esc, Delete, Ctrl+Z, Left/Right 5 s, Shift+Left/Right 1 s, 1-4 speed), marking with the overlap warning, the fine-tune (nudge) buttons, and autosave.
- `lethal_cuts/project.py`: the `Clip` and `Project` data. Each video `game.mov` gets `game.lcproj` (JSON) next to it, written through a temporary file so a crash can't corrupt it.
- `lethal_cuts/timeline.py`: the custom-drawn timeline (clip bars, start mark, playhead, click to seek).
- `lethal_cuts/clip_list.py`: the side table of clips (preview, number, editable name, start, length).
- `lethal_cuts/thumbnails.py`: the preview pictures, made by FFmpeg on background threads. Requests are bunched up with a short timer, and stale ones are dropped, so holding a nudge button doesn't queue hundreds of FFmpeg runs.
- `lethal_cuts/export.py`: the export engine (no UI). `probe()` reads size (swapped for rotated phone video), frame rate, audio and HDR. The video goes through crop, lanczos scale to 1080x1920, tone-mapping HLG/PQ to SDR (zscale+tonemap) if needed, a bt709 `setparams` tag, `fps=` for constant frame rate, then libx264 CRF 19. h264_nvenc is used instead if a tiny test encode works, falling back to the CPU mid-batch if it fails. Audio uses two-pass loudnorm (-14 LUFS, -1.5 dBTP, linear) to 48 kHz AAC. Progress comes from `-progress pipe:1`.
- `lethal_cuts/export_dialog.py`: the export window. `ExportWorker` runs on a QThread, writes `NN name.partial.mp4` and renames it when done, so cancelled or failed clips leave nothing behind. Also holds `open_upload_pages()` (YouTube + TikTok upload pages + the clips folder). Clips export to `<video name> Shorts` next to the video, until Settings (Step 5) adds a folder choice.
- `lethal_cuts/settings.py`: the `Settings` dataclass (hotkeys, padding, jump size, export folder, quality, tips on/off, colors, walkthrough_done). Saved as JSON in `%APPDATA%\Lethal Cuts\settings.json`, which survives reinstalls. `LETHALCUTS_DATA` points it at another folder: always set it in tests, so real AppData is never touched. A damaged file or bad values fall back to the defaults.
- `lethal_cuts/settings_page.py`, `guide.py`, `help.py`, `walkthrough.py`: the Settings tab (saves on every change), the Guide tab (HTML in a QTextBrowser, rebuilt so it shows the current hotkeys), the "?" buttons (`HELP` texts, shown with QWhatsThis), and the first-run walkthrough (a card plus a highlight outline on each part of the window).
- Hotkeys are QShortcuts rebuilt by `MainWindow.apply_settings()`. They only fire on the Editor tab and not while the walkthrough is showing. Friendly tips (`_clip_tips`) show above the clip list and in a check before export, unless they're turned off in Settings.
- `lethal_cuts/tools.py`: finds FFmpeg (bundled `vendor/ffmpeg/ffmpeg.exe` first, then PATH) and runs it without a console window.
- `lethal_cuts/video_view.py`: the video in a QGraphicsView, with the 9:16 crop box drawn in `drawForeground` (so it's per-view). Drag to move, drag a corner to resize, mouse wheel to resize, double-click to reset to full height, click beside it to move it there. Vertical preview (P) zooms the same view into the box with `fitInView` and blacks out the rest.
- `lethal_cuts/crop.py`: crop box math. A `Crop` is stored as fractions of the video picture (x, y, h), so it works at any resolution. `clip.crop = None` means not placed yet (exports centered). New clips copy `project.last_crop`.

## Choices made

- Video playback uses Qt's own player (QMediaPlayer with Qt's bundled FFmpeg backend), not libmpv. It plays 4K 10-bit HEVC .mov at full speed and 4x, and seeks to the exact frame, with nothing extra to install. Tested on 2026-10-16 on a generated sample.
- Exports even out loudness automatically (Alex asked for this). Tested: a quiet clip and a loud clip both came out at -14.0 LUFS.
- On Alex's PC (GTX 1080 Ti) NVENC fails with this FFmpeg build, so it encodes on the CPU: about 1.3 s per second of busy 4K footage. The friend's RTX 5070 should use NVENC; that can only be confirmed on his PC.

## Qt player gotchas

- `QGraphicsVideoItem.nativeSize()` stays empty with the FFmpeg backend. Use `video_item.videoSink().videoSize()`, and its `videoSizeChanged` signal.
- `boundingRect()` is the whole item, not the letterboxed picture. `VideoView.video_rect()` works out the real picture area.
- A stopped player draws nothing when seeking, so the window pauses the player once a video loads. Calling `pause()` inside the `mediaStatusChanged` handler crashes Python (segfault), so it's deferred with `QTimer.singleShot(0, ...)`.

## Testing

Test offline with a small generated HEVC clip in a temp folder, never in this folder. For example:
`ffmpeg -f lavfi -i testsrc2=size=3840x2160:rate=30:duration=20 -f lavfi -i sine=frequency=330:duration=20 -vf "select='not(eq(mod(n,10),3))',format=yuv420p10le" -fps_mode vfr -c:v libx265 -preset ultrafast -tag:v hvc1 -c:a aac test.mov`
(dropping every 10th frame makes it variable frame rate like an iPhone). Drive the window with `QTest` key clicks and save `window.grab()` screenshots.
