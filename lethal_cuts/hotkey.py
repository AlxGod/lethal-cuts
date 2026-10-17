"""A key that works from any program, even with the game in front (Windows' RegisterHotKey).

Used while recording: pressing it marks "something great just happened". Windows hands the key
to Lethal Cuts only, so it doesn't also do something in the game. It's only taken while recording.
"""
from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

# F1 is 0x70, F2 is 0x71 and so on (Windows' key numbers)
KEY_CODES = {f"F{n}": 0x6F + n for n in range(1, 25)}
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000  # holding the key down counts once

if os.name == "nt":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32")
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
                                     wintypes.UINT]
    _user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]


class GlobalHotkey(QObject):
    pressed = Signal()

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.key = key
        self._thread: threading.Thread | None = None
        self._thread_id = 0

    def start(self) -> bool:
        """Takes the key. False if another program already has it."""
        if self._thread or os.name != "nt" or self.key not in KEY_CODES:
            return bool(self._thread)
        ready = threading.Event()
        result = {"ok": False}

        def run():
            msg = wintypes.MSG()
            _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # gives this thread a message queue
            self._thread_id = _kernel32.GetCurrentThreadId()
            result["ok"] = bool(_user32.RegisterHotKey(None, 1, MOD_NOREPEAT, KEY_CODES[self.key]))
            ready.set()
            if not result["ok"]:
                return
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self.pressed.emit()  # reaches the window safely: Qt passes it across threads
            _user32.UnregisterHotKey(None, 1)

        self._thread = threading.Thread(target=run, daemon=True, name="moment key")
        self._thread.start()
        ready.wait(3)
        if not result["ok"]:
            self._thread.join(1)
            self._thread = None
        return result["ok"]

    def stop(self) -> None:
        """Gives the key back."""
        if self._thread:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(3)
            self._thread = None
