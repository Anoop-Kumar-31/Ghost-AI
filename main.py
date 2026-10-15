"""
Entry point for Ghost AI.
Initializes the application, sets standard stealth cursor, and launches the main window.
"""

import sys
import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ghost_ai.main_window import MainWindow

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ghost_ai")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Ghost AI")
    app.setOrganizationName("GhostAI")

    # Prevent Qt from auto-quitting when dialogs (like SettingsDialog) close,
    # because frameless Tool windows are not counted as standard primary windows by Qt.
    app.setQuitOnLastWindowClosed(False)

    # Standard arrow cursor everywhere (Ghost requirement: stealth, no jarring cursor changes)
    app.setOverrideCursor(Qt.CursorShape.ArrowCursor)

    window = MainWindow()
    window.show_app()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
