import threading
import traceback

from PySide6.QtCore import QThread, Signal


class TaskThread(QThread):
    """Runs fn(progress, cancel_event) off the UI thread."""
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self.cancel_event = threading.Event()

    def _report(self, current, total, message=""):
        self.progress.emit(int(current), int(total), str(message))

    def run(self):
        try:
            result = self._fn(self._report, self.cancel_event)
        except Exception:  # noqa: BLE001
            self.failed.emit(traceback.format_exc())
            return
        self.done.emit(result)
