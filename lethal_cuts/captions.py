"""Captions from the words Lethal Cuts heard (speech.py).

Shorts: the words are burned into the picture a few at a time, with the word being said lit up in
the highlight color (the usual Shorts look). Each moment's caption is drawn as a picture the width
of the video, and the export plays them all as one image sequence (FFmpeg's concat list, which says
how long each picture shows), so even a minute of captions is a single input.

Long videos: a caption file (.srt) is saved next to the video, to upload to YouTube with it, so
viewers can turn captions on or off.

"clip that" (and the word after it) never shows in captions.
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QPainter

from . import text_look
from .overlays import PHONE_COVERED
from .project import Clip, Overlay
from .speech import CLIP_WORDS, _plain

WORDS_PER = 3          # words on screen at once on a Short
SRT_WORDS = 8          # words per line in a long video's caption file
GAP_BREAK = 0.6        # a pause this long starts a new caption
HOLD = 0.4             # a caption stays this long after its last word (unless the next one starts)
BAND = 0.2             # the caption picture's height, as a fraction of the video's height
POSITIONS = {"low": ("Low", 0.72), "middle": ("Middle", 0.5), "high": ("High", 0.25)}
STYLES = {
    "caption": "Bold",
    "hook": "Hook",
    "callout": "Callout",
    "plain": "Plain",
}


def look(style: str, frame_w: int = 1080) -> Overlay:
    """The text look the captions are drawn with."""
    o = Overlay("text", 0, 1, size=0.5)
    if style == "caption":
        text_look.apply_style(o, "hook", long=False, place=False)
        o.size, o.shadow = 0.44, True
    else:
        text_look.apply_style(o, style if style in text_look.STYLES else "plain", long=False, place=False)
        o.size = 0.42
    return o


def _clean(word: str) -> str:
    return word.replace("*", "").strip()


def chunks(words: list, start: float, end: float, per: int = WORDS_PER) -> list[tuple[float, float, list]]:
    """Captions for start..end: (from, to, [(word, word start, word end)...]), a few words each."""
    hidden = set()
    for i in range(len(words) - 1):
        if _plain(words[i][0]) == "clip" and _plain(words[i + 1][0]) in CLIP_WORDS:
            hidden.update((i, i + 1))  # "clip that" stays out of the captions
    picked = [(_clean(w[0]), float(w[1]), float(w[2])) for i, w in enumerate(words)
              if i not in hidden and start <= float(w[1]) < end and _clean(w[0])]
    groups, current = [], []
    for w in picked:
        if current and (len(current) >= per or w[1] - current[-1][2] > GAP_BREAK
                        or re.search(r"[.!?]$", current[-1][0])):
            groups.append(current)
            current = []
        current.append(w)
    if current:
        groups.append(current)
    out = []
    for i, g in enumerate(groups):
        t0 = g[0][1]
        t1 = g[-1][2] + HOLD
        if i + 1 < len(groups):
            t1 = min(t1, groups[i + 1][0][1])
        out.append((t0, min(max(t1, g[-1][2]), end), g))
    return out


def states(caption_chunks: list) -> list[tuple[float, float, str]]:
    """Each moment's caption text, with the word being said starred (so it's drawn in the highlight color)."""
    out = []
    for t0, t1, g in caption_chunks:
        for i, (word, ws, we) in enumerate(g):
            a = t0 if i == 0 else ws
            b = g[i + 1][1] if i + 1 < len(g) else t1
            text = " ".join(f"*{w}*" if j == i else w for j, (w, _, _) in enumerate(g))
            if b > a:
                out.append((a, b, text))
    return out


def text_at(caption_states: list, t: float) -> str:
    for a, b, text in caption_states:
        if a <= t < b:
            return text
    return ""


def render(style: str, text: str, frame_w: int, frame_h: int) -> QImage:
    """One caption as a picture the full width of the video and BAND tall (the same size every time)."""
    band = QImage(frame_w, int(frame_h * BAND) // 2 * 2, QImage.Format_ARGB32_Premultiplied)
    band.fill(Qt.transparent)
    if text:
        o = look(style, frame_w)
        o.text = text
        # Centered, so on a Short it stays narrow enough to clear the like/share buttons on the right
        wrap = text_look.TEXT_WRAP if frame_h <= frame_w else 1 - 2 * PHONE_COVERED[2] - 0.02
        for _ in range(4):  # a long word or two: a bit smaller rather than a third line
            if len(text_look._layout(o, frame_w, wrap)[3]) <= 2:
                break
            o.size *= 0.88
        image = text_look.render_text(o, frame_w, wrap=wrap)
        p = QPainter(band)
        p.drawImage(QPointF((frame_w - image.width()) / 2, (band.height() - image.height()) / 2), image)
        p.end()
    return band


def clip_states(words: list, clip: Clip, freezes: list[tuple[float, int]]) -> list[tuple[float, float, str]]:
    """A Short's captions in the finished Short's time: pause cards hold them back (none show during a pause)."""
    out = []
    for a, b, text in states(chunks(words, clip.start, clip.end)):
        a, b = a - clip.start, b - clip.start
        for at, seconds in sorted(freezes):
            if a >= at:
                a, b = a + seconds, b + seconds
            elif b > at:
                b = at  # cut short by the pause card
        if b > a:
            out.append((a, b, text))
    return out


def write_sequence(caption_states: list, length: float, style: str, frame_w: int, frame_h: int,
                   folder: Path) -> Path:
    """The pictures and FFmpeg's list of how long each shows, covering the whole Short (blank between captions)."""
    folder.mkdir(parents=True, exist_ok=True)
    blank = folder / "caption_blank.png"
    render(style, "", frame_w, frame_h).save(str(blank), "PNG")
    lines, at, n = ["ffconcat version 1.0"], 0.0, 0

    def add(path: Path, seconds: float):
        lines.append(f"file '{path.name}'")
        lines.append(f"duration {seconds:.4f}")

    made: dict[str, Path] = {}
    for a, b, text in caption_states:
        if a > at + 0.001:
            add(blank, a - at)
        if text not in made:
            n += 1
            made[text] = folder / f"caption_{n:05d}.png"
            render(style, text, frame_w, frame_h).save(str(made[text]), "PNG")
        add(made[text], b - max(a, at))
        at = b
    if length > at:
        add(blank, length - at)
    lines.append(f"file '{blank.name}'")  # the concat list needs the last picture once more to end cleanly
    path = folder / "captions.ffconcat"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _srt_time(t: float) -> str:
    ms = int(round(max(t, 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt(words: list, to_output, kept) -> str:
    """A caption file for the long video. to_output maps recording time to the video's time; kept says
    whether a recording time is in the video (not cut out)."""
    entries, n = [], 0
    end = max((float(w[2]) for w in words), default=0) + 1
    for t0, t1, g in chunks(words, 0, end, SRT_WORDS):
        g = [w for w in g if kept(w[1])]
        if not g:
            continue
        n += 1
        a, b = to_output(g[0][1]), to_output(min(t1, g[-1][2] + HOLD))
        entries.append(f"{n}\n{_srt_time(a)} --> {_srt_time(max(b, a + 0.3))}\n{' '.join(w[0] for w in g)}\n")
    return "\n".join(entries)
