"""Looking up Magic cards on Scryfall (scryfall.com), the free card database, and saving their pictures.

Scryfall asks programs to be gentle: at most about 10 requests a second, a User-Agent and Accept
header on every request, and to keep what they download instead of asking again. So:
- every request to the API waits its turn, at least REQUEST_GAP apart, one at a time
- lookups are saved in the cards folder for a week, and pictures are kept for good
- if Scryfall ever says "too many requests" (429), Lethal Cuts stops asking for a minute and says so
Pictures come from Scryfall's picture server (cards.scryfall.io), a few at a time.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import __version__
from .settings import data_dir

API = "https://api.scryfall.com"
HEADERS = {"User-Agent": f"LethalCuts/{__version__} (github.com/AlxGod/lethal-cuts)", "Accept": "application/json"}
REQUEST_GAP = 0.12          # seconds between API requests (Scryfall allows about 10 a second)
COOL_OFF = 60               # seconds to stop asking after a "too many requests" answer
LOOKUP_DAYS = 7             # saved lookups are reused for this long
MAX_PRINTINGS = 120         # printings shown for one card (newest first)
COLLECTION_BATCH = 75       # Scryfall's limit for looking up many cards in one request
DECK_HEADERS = {"commander", "deck", "mainboard", "main", "sideboard", "maybeboard", "maybe", "companion",
                "lands", "creatures", "artifacts", "enchantments", "instants", "sorceries", "planeswalkers",
                "battles", "other", "tokens"}


class ScryfallError(Exception):
    """A problem worth telling the user about, in plain words."""


@dataclass
class Face:
    name: str
    small: str   # picture addresses on Scryfall's picture server
    large: str


@dataclass
class Printing:
    """One printing of a card: its set, number and picture(s). Double-faced cards have two faces."""
    id: str
    name: str
    set_code: str
    set_name: str
    number: str
    year: str
    faces: list[Face] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.set_name} ({self.set_code.upper()}) #{self.number}, {self.year}"


# --- the network (tests replace _get and _post) ---
def _get(url: str, timeout: float = 15) -> bytes:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _post(url: str, body: bytes, timeout: float = 20) -> bytes:
    request = urllib.request.Request(url, data=body, headers={**HEADERS, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


_turn = threading.Lock()
_last_request = 0.0
_blocked_until = 0.0


def _api(path: str, params: dict | None = None, body: dict | None = None) -> dict:
    """One API request, waiting its turn. Returns the answer, or raises ScryfallError."""
    global _last_request, _blocked_until
    url = path if path.startswith("http") else API + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    with _turn:
        if time.monotonic() < _blocked_until:
            left = int(_blocked_until - time.monotonic()) + 1
            raise ScryfallError(f"Scryfall asked Lethal Cuts to slow down. Card search is paused for {left} more seconds.")
        wait = REQUEST_GAP - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            raw = _post(url, json.dumps(body).encode()) if body is not None else _get(url)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                _blocked_until = time.monotonic() + COOL_OFF
                raise ScryfallError("Scryfall asked Lethal Cuts to slow down, so card search is paused for a minute.")
            if e.code == 404:
                return {"object": "error", "status": 404}
            raise ScryfallError(f"Scryfall had a problem (error {e.code}). Try again in a minute.")
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ScryfallError("Couldn't reach Scryfall. Check the internet connection and try again.")
        finally:
            _last_request = time.monotonic()
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        raise ScryfallError("Scryfall sent back something unexpected. Try again in a minute.")


# --- the cards folder ---
def cards_dir() -> Path:
    return data_dir() / "cards"


def _saved_lookup(key: str) -> Path:
    return cards_dir() / "lookups" / (hashlib.sha1(key.encode()).hexdigest()[:20] + ".json")


def _read_saved(key: str):
    path = _saved_lookup(key)
    try:
        if time.time() - path.stat().st_mtime < LOOKUP_DAYS * 86400:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return None


def _write_saved(key: str, data) -> None:
    path = _saved_lookup(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # only a cache: it just gets asked again next time


# --- lookups ---
_suggestions: dict[str, list[str]] = {}


def autocomplete(text: str) -> list[str]:
    """Up to 20 card names that start like what's been typed."""
    text = text.strip()
    if len(text) < 2:
        return []
    key = text.lower()
    if key not in _suggestions:
        data = _api("/cards/autocomplete", {"q": text})
        _suggestions[key] = [str(n) for n in data.get("data", [])]
    return _suggestions[key]


def find_card(name: str) -> dict:
    """The card with this name (or the closest match to a misspelling)."""
    key = "named:" + name.strip().lower()
    card = _read_saved(key)
    if card is None:
        card = _api("/cards/named", {"exact": name})
        if card.get("object") == "error":
            card = _api("/cards/named", {"fuzzy": name})
        if card.get("object") == "error":
            raise ScryfallError(f'No card called "{name}" was found on Scryfall.')
        _write_saved(key, card)
    return card


def _faces(card: dict) -> list[Face]:
    if card.get("image_uris"):
        u = card["image_uris"]
        return [Face(card.get("name", ""), u.get("small", ""), u.get("large", u.get("normal", "")))]
    faces = []
    for f in card.get("card_faces", []):
        u = f.get("image_uris") or {}
        if u:
            faces.append(Face(f.get("name", ""), u.get("small", ""), u.get("large", u.get("normal", ""))))
    return faces


def _printing(card: dict) -> Printing:
    return Printing(str(card.get("id", "")), str(card.get("name", "")), str(card.get("set", "")),
                    str(card.get("set_name", "")), str(card.get("collector_number", "")),
                    str(card.get("released_at", ""))[:4], _faces(card))


def printings(name: str) -> list[Printing]:
    """Every printing of a card that has a picture, newest first."""
    card = find_card(name)
    key = "prints:" + str(card.get("oracle_id") or card.get("id"))
    cards = _read_saved(key)
    if cards is None:
        cards = []
        url = card.get("prints_search_uri")
        while url and len(cards) < MAX_PRINTINGS:
            page = _api(url)
            if page.get("object") == "error":
                break
            cards += page.get("data", [])
            url = page.get("next_page") if page.get("has_more") else None
        if not cards:
            cards = [card]
        cards = cards[:MAX_PRINTINGS]
        _write_saved(key, cards)
    found = [p for p in (_printing(c) for c in cards) if p.faces]
    found.sort(key=lambda p: p.year, reverse=True)
    return found


def check_names(names: list[str]) -> tuple[list[str], list[str]]:
    """Looks up a whole decklist in a few requests: (names as Scryfall spells them, names not found)."""
    good, missing = [], []
    for i in range(0, len(names), COLLECTION_BATCH):
        batch = names[i:i + COLLECTION_BATCH]
        data = _api("/cards/collection", body={"identifiers": [{"name": n} for n in batch]})
        if data.get("object") == "error":
            raise ScryfallError("Scryfall couldn't check that list. Try again in a minute.")
        good += [str(c.get("name", "")) for c in data.get("data", [])]
        missing += [str(n.get("name", "")) for n in data.get("not_found", [])]
    return good, missing


def picture_path(printing_id: str, face: int, size: str) -> Path:
    return cards_dir() / "pictures" / f"{printing_id}-{face}-{size}.jpg"


def download_picture(url: str, path: Path) -> Path:
    """Saves a card picture once; later calls just return the saved file."""
    if path.exists() and path.stat().st_size > 0:
        return path
    if not url.startswith("https://"):
        raise ScryfallError("This card has no picture on Scryfall.")
    try:
        data = _get(url, timeout=20)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ScryfallError("Couldn't download the card picture. Check the internet connection and try again.")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path


# --- decklists ---
def parse_decklist(text: str) -> list[str]:
    """Card names from a pasted decklist ("1 Sol Ring", "1x Sol Ring (CMM) 400 *F*", or just "Sol Ring")."""
    names, seen = [], set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "//")):
            continue
        line = re.sub(r"^\d+\s*x?\s+", "", line, flags=re.I)          # the count
        line = re.sub(r"\s+\([A-Za-z0-9]{2,6}\)(\s+\S+)?.*$", "", line)  # (SET) 123 *F*
        line = re.sub(r"\s+\*[A-Z]+\*$", "", line).strip()
        if not line or line.rstrip(":").lower() in DECK_HEADERS:
            continue
        if line.lower() not in seen:
            seen.add(line.lower())
            names.append(line)
    return names


def decks_path() -> Path:
    return data_dir() / "decks.json"


def load_decks() -> list[dict]:
    """His own decks: [{"name": ..., "cards": [...]}]."""
    try:
        data = json.loads(decks_path().read_text(encoding="utf-8"))
        return [{"name": str(d["name"]), "cards": [str(c) for c in d.get("cards", [])]} for d in data.get("decks", [])]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def load_last_deck() -> str:
    """The deck that was showing last time, so the picker opens on it."""
    try:
        return str(json.loads(decks_path().read_text(encoding="utf-8")).get("last", ""))
    except (OSError, ValueError, AttributeError):
        return ""


def save_decks(decks: list[dict], last: str | None = None) -> None:
    path = decks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    last = load_last_deck() if last is None else last
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"decks": decks, "last": last}, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def save_last_deck(name: str) -> None:
    if name != load_last_deck():
        try:
            save_decks(load_decks(), name)
        except OSError:
            pass


# --- background work for the window ---
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="scryfall")


class Loader(QObject):
    """Runs lookups in the background so the window never freezes. Connect these signals to methods
    of objects on the main thread (never lambdas: those would run on the background thread)."""
    suggestions = Signal(str, list)      # what was typed, names
    printings_ready = Signal(str, list)  # card name, [Printing]
    picture_ready = Signal(str, str)     # key, file path
    checked = Signal(list, list)         # names found, names not found
    failed = Signal(str, str)            # what failed ("search", "printings", "picture", "check"), message

    def search(self, text: str) -> None:
        _pool.submit(self._run, "search", lambda: self.suggestions.emit(text, autocomplete(text)))

    def load_printings(self, name: str) -> None:
        _pool.submit(self._run, "printings", lambda: self.printings_ready.emit(name, printings(name)))

    def load_picture(self, key: str, url: str, path: Path) -> None:
        _pool.submit(self._run, "picture", lambda: self.picture_ready.emit(key, str(download_picture(url, path))))

    def check(self, names: list[str]) -> None:
        _pool.submit(self._run, "check", lambda: self.checked.emit(*check_names(names)))

    def _run(self, what: str, job) -> None:
        try:
            job()
        except ScryfallError as e:
            self.failed.emit(what, str(e))
        except Exception as e:  # never let a background error vanish silently
            self.failed.emit(what, f"Something went wrong looking that up: {e}")
