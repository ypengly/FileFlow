import sys

from PySide6.QtWidgets import QApplication

from .core.history import History
from .ui.main_window import MainWindow
from .ui.themes import apply_theme


def main(argv=None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("FileFlow")
    history = History()
    dark = history.get_setting("theme", "dark") == "dark"
    apply_theme(app, dark)
    win = MainWindow(history, dark)
    win.show()
    return app.exec()
