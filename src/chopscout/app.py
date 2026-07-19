from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .logging_config import configure_logging
from .ui import MainWindow

DARK_STYLE = """
QWidget { background: #202329; color: #e5e7eb; font-size: 13px; }
QMainWindow { background: #17191d; }
QFrame { background: #202329; }
QPushButton, QComboBox, QSpinBox, QDoubleSpinBox { background: #2c313a; border: 1px solid #454b57; border-radius: 5px; padding: 6px; }
QPushButton:hover { background: #39404b; }
QToolBar { background: #252930; border-bottom: 1px solid #3b414b; spacing: 6px; padding: 5px; }
QStatusBar { background: #252930; }
"""


def main() -> int:
    configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("ChopScout")
    app.setOrganizationName("ChopScout")
    app.setStyleSheet(DARK_STYLE)
    window = MainWindow(); window.show()
    window.offer_recovery()
    return app.exec()
