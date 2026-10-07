"""Headless smoke test of the Qt window. Skipped automatically when PySide6 is not installed."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

from tests.helpers import TmpCase


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class UiSmokeTests(TmpCase):
    def test_window_builds_shows_plan_and_reject_changes_nothing(self):
        from fileflow.core.planner import build_plan
        from fileflow.core.scanner import scan_folder
        from fileflow.ui.main_window import MainWindow

        QApplication.instance() or QApplication([])
        self.make("invoice-final.pdf")
        self.make("vacation.jpg")
        before = self.snapshot()
        win = MainWindow(self.history, True)
        scan = scan_folder(self.root)
        win._scan_done(scan)
        self.assertEqual(win.tbl_types.rowCount(), 2)
        win._plan_done((build_plan(scan), ""))
        self.assertEqual(win.tbl_plan.rowCount(), 2)
        win.on_reject()
        self.assertEqual(win.tbl_plan.rowCount(), 0)
        self.assertEqual(self.snapshot(), before)
