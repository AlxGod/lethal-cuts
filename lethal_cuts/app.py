"""Starts the program: dark theme, main window, and an optional video to open."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow

STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 10pt; }
QPushButton { background: #2c2440; border: 1px solid #3d3358; border-radius: 6px; padding: 6px 14px; }
QPushButton:hover { background: #3a2f55; }
QPushButton:disabled { color: #6a6080; }
QPushButton#markIn { background: #1f5a44; border-color: #2e7a5e; }
QPushButton#markIn:hover { background: #267052; }
QPushButton#markOut { background: #6e1f33; border-color: #8e2b45; }
QPushButton#markOut:hover { background: #85263e; }
QPushButton#speedButton { padding: 6px 9px; }
QPushButton#speedButton:checked { background: #7b4fc9; border-color: #9a70e0; }
QPushButton#previewButton:checked { background: #8a6418; border-color: #f0b840; }
QPushButton#exportButton { background: #7b4fc9; border-color: #9a70e0; font-weight: bold; padding: 8px 14px; }
QPushButton#exportButton:hover { background: #8d60dc; }
QPushButton#exportButton:disabled { background: #2c2440; border-color: #3d3358; }
QProgressBar { background: #2a2338; border: none; border-radius: 5px; height: 14px; text-align: center; }
QProgressBar::chunk { background: #b0304a; border-radius: 5px; }
QLabel#dimLabel { color: #8a80a0; padding-right: 4px; }
QGroupBox { border: 1px solid #2a2338; border-radius: 6px; margin-top: 10px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #b8aed0; }
QGroupBox:disabled { color: #6a6080; }
QLabel#timeLabel { font-family: Consolas; font-size: 11pt; padding: 0 8px; }
QLabel#panelTitle { font-size: 12pt; font-weight: bold; padding: 2px 0 6px 2px; }
QTableWidget { background: #1a1524; alternate-background-color: #1f192b; gridline-color: #2a2338; border: 1px solid #2a2338; }
QHeaderView::section { background: #241d33; border: none; padding: 4px; }
QStatusBar { color: #b8aed0; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#16121e"))
    pal.setColor(QPalette.WindowText, QColor("#e8e2f4"))
    pal.setColor(QPalette.Base, QColor("#1a1524"))
    pal.setColor(QPalette.AlternateBase, QColor("#1f192b"))
    pal.setColor(QPalette.Text, QColor("#e8e2f4"))
    pal.setColor(QPalette.Button, QColor("#2c2440"))
    pal.setColor(QPalette.ButtonText, QColor("#e8e2f4"))
    pal.setColor(QPalette.Highlight, QColor("#8e2b45"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor("#2c2440"))
    pal.setColor(QPalette.ToolTipText, QColor("#e8e2f4"))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Lethal Cuts")
    apply_theme(app)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        window.open_video(Path(sys.argv[1]))
    return app.exec()
