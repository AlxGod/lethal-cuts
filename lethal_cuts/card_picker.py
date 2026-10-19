"""The "Add a card" window: search every Magic card on Scryfall, pick the printing (artwork) and,
for double-faced cards, the side to show. "My decks" keeps his own decklists one click away."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from . import scryfall
from .help import HELP, HelpButton

THUMB = QSize(98, 137)
LABEL_HEIGHT = 30   # set and year under each printing
PREVIEW_W = 250
SEARCH_DELAY = 300  # ms after the last key press before asking Scryfall


def _blank_icon() -> QIcon:
    pix = QPixmap(THUMB)
    pix.fill(QColor("#2a2338"))
    return QIcon(pix)


class DeckDialog(QDialog):
    """Paste a decklist (from Moxfield, Archidekt, or typed one card per line)."""

    def __init__(self, parent=None, name: str = "", text: str = ""):
        super().__init__(parent)
        self.setWindowTitle("My deck")
        self.setMinimumSize(420, 480)
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("Deck name, e.g. Atraxa Superfriends")
        self.list_edit = QPlainTextEdit(text)
        self.list_edit.setPlaceholderText("Paste the decklist here, one card per line:\n\n1 Sol Ring (CMM) 400\n"
                                          "1 Atraxa, Praetors' Voice\n...\n\nExported from Moxfield or Archidekt? "
                                          "Their set codes and numbers are kept, so each card opens on the exact "
                                          "printing you own.")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Name"))
        layout.addWidget(self.name_edit)
        layout.addWidget(QLabel("Cards"))
        layout.addWidget(self.list_edit, 1)
        layout.addWidget(buttons)

    def _save(self):
        if not self.name_edit.text().strip():
            self.name_edit.setFocus()
            return
        if not scryfall.parse_decklist(self.list_edit.toPlainText()):
            self.list_edit.setFocus()
            return
        self.accept()

    def result_deck(self) -> tuple[str, list[str], dict]:
        entries = scryfall.parse_deck_entries(self.list_edit.toPlainText())
        printings = {name.lower(): [s, n] for name, s, n in entries if s}
        return self.name_edit.text().strip(), [name for name, _, _ in entries], printings


class CardPicker(QDialog):
    def __init__(self, parent=None, start_name: str = "", start_id: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Add a card")
        self.resize(980, 640)
        self.card: dict | None = None  # the chosen card, once Add is clicked
        self.loader = scryfall.Loader(self)
        self.loader.suggestions.connect(self._on_suggestions)
        self.loader.printings_ready.connect(self._on_printings)
        self.loader.picture_ready.connect(self._on_picture)
        self.loader.checked.connect(self._on_checked)
        self.loader.failed.connect(self._on_failed)
        self._wanted = ""            # the card whose printings are being shown
        self._printings: list[scryfall.Printing] = []
        self._face = 0
        self._add_when_ready = False
        self._pending_deck: tuple | None = None  # (name, cards, printings, index or -1 for new)
        self._prefer: tuple[str, str, str] = ("", "", "")  # (printing id, set code, number) to open on
        self.decks = scryfall.load_decks()

        # Left: search, then My decks
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a card name, e.g. Sol Ring")
        self.search.setClearButtonEnabled(True)
        self.search.textEdited.connect(lambda _: self.search_timer.start())
        self.search.returnPressed.connect(self._search_now)
        self.search_timer = QTimer(self, singleShot=True, interval=SEARCH_DELAY, timeout=self._ask_suggestions)
        self.names = QListWidget()
        self.names.itemClicked.connect(lambda item: self.choose_name(item.text()))
        self.names.itemActivated.connect(lambda item: self.choose_name(item.text()))
        self.deck_combo = QComboBox()
        self.deck_combo.currentIndexChanged.connect(self._show_deck)
        new_deck = QPushButton("New deck")
        new_deck.setToolTip("Paste one of your decklists so its cards are one click away")
        new_deck.clicked.connect(self.new_deck)
        self.edit_deck_btn = QPushButton("Edit")
        self.edit_deck_btn.clicked.connect(self.edit_deck)
        self.delete_deck_btn = QPushButton("Delete")
        self.delete_deck_btn.clicked.connect(self.delete_deck)
        deck_buttons = QHBoxLayout()
        deck_buttons.addWidget(new_deck)
        deck_buttons.addWidget(self.edit_deck_btn)
        deck_buttons.addWidget(self.delete_deck_btn)
        deck_buttons.addStretch(1)
        self.deck_cards = QListWidget()
        self.deck_cards.itemClicked.connect(self._on_deck_card)
        self.deck_note = QLabel("Optional: save your own decks here so their cards are one click away.")
        self.deck_note.setObjectName("dimLabel")
        self.deck_note.setWordWrap(True)
        left = QVBoxLayout()
        search_title = QLabel("Search every card")
        search_title.setObjectName("panelTitle")
        title_row = QHBoxLayout()
        title_row.addWidget(search_title)
        title_row.addStretch(1)
        title_row.addWidget(HelpButton(HELP["cards"]))
        left.addLayout(title_row)
        left.addWidget(self.search)
        left.addWidget(self.names, 3)
        decks_title = QLabel("My decks")
        decks_title.setObjectName("panelTitle")
        left.addWidget(decks_title)
        left.addWidget(self.deck_combo)
        left.addLayout(deck_buttons)
        left.addWidget(self.deck_note)
        left.addWidget(self.deck_cards, 2)
        left_box = QWidget()
        left_box.setLayout(left)
        left_box.setFixedWidth(300)

        # Middle: the printings; right: the picked one, big
        self.card_title = QLabel("Pick a card on the left")
        self.card_title.setObjectName("panelTitle")
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(THUMB)
        self.grid.setGridSize(QSize(THUMB.width() + 16, THUMB.height() + LABEL_HEIGHT + 10))
        self.grid.setWordWrap(True)
        self.grid.setTextElideMode(Qt.ElideRight)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Find a printing: set name, set code or year (e.g. Commander Masters, CMM, 2023)")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.currentRowChanged.connect(self._on_printing_picked)
        self.grid.itemDoubleClicked.connect(lambda _: self.add())
        self.preview = QLabel()
        self.preview.setFixedSize(PREVIEW_W, int(PREVIEW_W * 88 / 63))
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background: #16121e; border-radius: 10px;")
        self.printing_label = QLabel("")
        self.printing_label.setObjectName("dimLabel")
        self.printing_label.setWordWrap(True)
        self.printing_label.setFixedWidth(PREVIEW_W)
        self.flip_btn = QPushButton("Show the other side")
        self.flip_btn.setToolTip("This card has two sides: pick which one goes on the video")
        self.flip_btn.clicked.connect(self.flip)
        self.flip_btn.hide()
        right = QVBoxLayout()
        right.addWidget(self.preview)
        right.addWidget(self.flip_btn)
        right.addWidget(self.printing_label)
        right.addStretch(1)
        middle = QVBoxLayout()
        middle.addWidget(self.card_title)
        middle.addWidget(self.filter)
        middle.addWidget(self.grid, 1)
        body = QHBoxLayout()
        body.addWidget(left_box)
        body.addLayout(middle, 1)
        body.addLayout(right)

        self.status = QLabel("Card details and pictures come from Scryfall. Each picture is downloaded once and kept.")
        self.status.setObjectName("dimLabel")
        self.status.setWordWrap(True)
        self.add_btn = QPushButton("Add to video")
        self.add_btn.setObjectName("exportButton")
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self.add)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.add_btn)
        bottom.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addLayout(bottom)

        self._fill_decks(scryfall.load_last_deck())
        self.search.setFocus()
        if start_name:
            self.search.setText(start_name)
            self.choose_name(start_name, (start_id, "", ""))

    # --- searching ---
    def _ask_suggestions(self):
        text = self.search.text().strip()
        if len(text) >= 2:
            self.loader.search(text)

    def _on_suggestions(self, text: str, names: list):
        if text != self.search.text().strip():
            return  # typed more since
        self.names.clear()
        self.names.addItems(names)
        if not names:
            self.status.setText(f'No card names start with "{text}". Press Enter to search for the closest match.')

    def _search_now(self):
        """Enter: take the top suggestion, or the closest match to what's typed."""
        text = self.search.text().strip()
        if self.names.count() and self.names.item(0).text().lower().startswith(text.lower()):
            self.choose_name(self.names.item(0).text())
        elif len(text) >= 2:
            self.choose_name(text)

    def _on_deck_card(self, item):
        i = self._deck_index()
        printings = self.decks[i].get("printings", {}) if i >= 0 else {}
        name = item.text().lower()
        # Scryfall spells double-faced cards "Front // Back"; the list may have just the front
        set_code, number = printings.get(name) or printings.get(name.split(" // ")[0]) or ["", ""]
        self.choose_name(item.text(), ("", set_code, number))

    def choose_name(self, name: str, prefer: tuple[str, str, str] = ("", "", "")):
        """Shows every printing of a card. prefer = (printing id, set code, number) to start on, if known."""
        self._wanted = name
        self._prefer = prefer
        self._printings = []
        self.filter.clear()
        self.grid.clear()
        self.preview.clear()
        self.printing_label.setText("")
        self.flip_btn.hide()
        self.add_btn.setEnabled(False)
        self.card_title.setText(name)
        self.status.setText(f"Looking up {name}...")
        self.loader.load_printings(name)

    def _on_printings(self, name: str, found: list):
        if name != self._wanted:
            return
        self._printings = found
        if not found:
            self.status.setText(f"Scryfall has no pictures of {name}.")
            return
        self.card_title.setText(f"{found[0].name}: {len(found)} printing{'s' if len(found) != 1 else ''}, newest first")
        blank = _blank_icon()
        for i, p in enumerate(found):
            item = QListWidgetItem(blank, f"{p.set_code.upper()} #{p.number}\n{p.year}")
            item.setToolTip(p.label)
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self.grid.addItem(item)
            path = scryfall.picture_path(p.id, 0, "small")
            self.loader.load_picture(f"thumb:{i}:{p.id}", p.faces[0].small, path)
        want_id, want_set, want_number = self._prefer
        row = next((i for i, p in enumerate(found) if want_id and p.id == want_id), -1)
        if row < 0 and want_set:
            row = next((i for i, p in enumerate(found) if p.set_code == want_set and
                        (not want_number or p.number == want_number)), -1)
        if row >= 0:
            p = found[row]
            why = "the one already on the video" if want_id else "the printing from your decklist"
            self.status.setText(f"Opened on {why}: {p.set_name} ({p.set_code.upper()}) #{p.number}. "
                                "Pick another to change it.")
        elif want_set:
            self.status.setText(f"Your decklist says {want_set.upper()} {want_number}, but Scryfall has no picture of "
                                "that printing. Pick the one that matches your card.")
        else:
            self.status.setText("Pick the artwork that matches your card (hover for the set's full name), then click "
                                "Add to video (or double-click it).")
        self.grid.setCurrentRow(max(row, 0))
        self.grid.scrollToItem(self.grid.currentItem())

    def _apply_filter(self, text: str):
        """Hides printings that don't match the set name, set code or year typed."""
        words = text.lower().split()
        for i, p in enumerate(self._printings):
            hay = f"{p.set_name} {p.set_code} {p.year} #{p.number}".lower()
            self.grid.item(i).setHidden(not all(w in hay for w in words))

    def _on_printing_picked(self, row: int):
        self._face = 0
        self._show_big()

    def _current(self) -> scryfall.Printing | None:
        row = self.grid.currentRow()
        return self._printings[row] if 0 <= row < len(self._printings) else None

    def _show_big(self):
        p = self._current()
        if p is None:
            return
        self.flip_btn.setVisible(len(p.faces) > 1)
        face = p.faces[self._face]
        side = (" - front" if self._face == 0 else " - back") if len(p.faces) > 1 else ""
        self.printing_label.setText(f"{face.name}{side}\n{p.label}")
        path = scryfall.picture_path(p.id, self._face, "large")
        self.add_btn.setEnabled(False)
        self.preview.setText("Downloading...")
        self.loader.load_picture(f"big:{p.id}:{self._face}", face.large, path)

    def flip(self):
        p = self._current()
        if p and len(p.faces) > 1:
            self._face = 1 - self._face
            self._show_big()

    def _on_picture(self, key: str, path: str):
        kind, a, b = key.split(":", 2)
        if kind == "thumb":
            row = int(a)
            if row < self.grid.count() and row < len(self._printings) and self._printings[row].id == b:
                pix = QPixmap(path)
                if not pix.isNull():
                    self.grid.item(row).setIcon(QIcon(pix.scaled(THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            return
        p = self._current()
        if p is None or p.id != a or int(b) != self._face:
            return  # picked something else since
        pix = QPixmap(path)
        self.preview.setPixmap(pix.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.add_btn.setEnabled(True)
        if self._add_when_ready:
            self.add()

    def _on_failed(self, what: str, message: str):
        self._add_when_ready = False
        if what == "check" and self._pending_deck:
            # Couldn't check the names (no internet?): keep the list as typed
            name, cards, printings, index = self._pending_deck
            self._pending_deck = None
            self._store_deck(name, cards, printings, index)
            message += " The deck was saved as typed."
        elif what == "picture" and self.preview.text() == "Downloading...":
            self.preview.setText("No picture")
        self.status.setText(message)

    # --- adding ---
    def add(self):
        p = self._current()
        if p is None:
            return
        path = scryfall.picture_path(p.id, self._face, "large")
        if not path.exists():
            self._add_when_ready = True
            self.status.setText("Downloading the picture, one moment...")
            return
        face = p.faces[self._face]
        self.card = {"name": face.name, "id": p.id, "set": p.set_code, "set_name": p.set_name, "number": p.number,
                     "face": self._face, "image": str(path), "large_url": face.large}
        self.accept()

    # --- my decks ---
    def _fill_decks(self, select: str = ""):
        self.deck_combo.blockSignals(True)
        self.deck_combo.clear()
        for d in self.decks:
            self.deck_combo.addItem(f"{d['name']} ({len(d['cards'])})", d["name"])
        index = max(self.deck_combo.findData(select), 0)
        self.deck_combo.setCurrentIndex(index if self.decks else -1)
        self.deck_combo.blockSignals(False)
        self._show_deck()

    def _deck_index(self) -> int:
        i = self.deck_combo.currentIndex()
        return i if 0 <= i < len(self.decks) else -1

    def _show_deck(self):
        i = self._deck_index()
        has = i >= 0
        self.deck_combo.setVisible(has)
        self.edit_deck_btn.setVisible(has)
        self.delete_deck_btn.setVisible(has)
        self.deck_note.setVisible(not has)
        self.deck_cards.setVisible(has)
        self.deck_cards.clear()
        if has:
            self.deck_cards.addItems(self.decks[i]["cards"])
            scryfall.save_last_deck(self.decks[i]["name"])

    def new_deck(self):
        dialog = DeckDialog(self)
        if dialog.exec():
            self._check_deck(*dialog.result_deck(), -1)

    def edit_deck(self):
        i = self._deck_index()
        if i < 0:
            return
        dialog = DeckDialog(self, self.decks[i]["name"], scryfall.deck_text(self.decks[i]))
        if dialog.exec():
            self._check_deck(*dialog.result_deck(), i)

    def _check_deck(self, name: str, cards: list[str], printings: dict, index: int):
        """Asks Scryfall about the whole list at once (one request per 75 cards) to catch typos."""
        self._pending_deck = (name, cards, printings, index)
        self.status.setText(f"Checking the {len(cards)} card names with Scryfall...")
        self.loader.check(cards)

    def _on_checked(self, found: list, missing: list):
        if not self._pending_deck:
            return
        name, cards, printings, index = self._pending_deck
        self._pending_deck = None
        self._store_deck(name, found + missing if missing else found, printings, index)
        if missing:
            were = "names weren't" if len(missing) != 1 else "name wasn't"
            self.status.setText(f"Saved {name}. {len(missing)} {were} found on Scryfall (check the spelling with "
                                f"Edit): {', '.join(missing[:6])}"
                                + ("..." if len(missing) > 6 else ""))
        else:
            self.status.setText(f"Saved {name} ({len(found)} cards).")

    def _store_deck(self, name: str, cards: list[str], printings: dict, index: int):
        deck = {"name": name, "cards": cards, "printings": printings}
        if index >= 0:
            self.decks[index] = deck
        else:
            self.decks = [d for d in self.decks if d["name"] != name] + [deck]
        try:
            scryfall.save_decks(self.decks)
        except OSError as e:
            self.status.setText(f"Couldn't save the deck: {e}")
        self._fill_decks(name)

    def delete_deck(self):
        i = self._deck_index()
        if i < 0:
            return
        answer = QMessageBox.question(self, "Delete deck", f"Delete the deck {self.decks[i]['name']} from My decks?\n\n"
                                      "(This only removes the list from Lethal Cuts.)")
        if answer != QMessageBox.Yes:
            return
        del self.decks[i]
        try:
            scryfall.save_decks(self.decks)
        except OSError:
            pass
        self._fill_decks()
