import os
import unittest

from fileflow.core.cleanup import find_cleanup
from fileflow.core.operations import (Op, apply_ops, ops_from_plan, quarantine_ops, undo_batch)
from fileflow.core.planner import build_plan
from fileflow.core.scanner import scan_folder
from tests.helpers import TmpCase


class OperationTests(TmpCase):
    def test_apply_plan_then_full_undo_restores_everything(self):
        self.make("invoice-final.pdf", "inv")
        self.make("vacation.jpg", "jpg")
        self.make("IMG_0001.jpg", "img")
        self.make("project_notes.txt", "notes")
        self.make("Copy of thing.zip", "zip")
        before = self.snapshot()
        items = build_plan(scan_folder(self.root))
        res = apply_ops(self.history, ops_from_plan(items), "organize", self.root)
        self.assertEqual(res.done, len(items))
        self.assertEqual(res.skipped + res.failed, [])
        after = self.snapshot()
        self.assertNotEqual(before, after)
        self.assertIn("Documents/Finance/Invoices/invoice-final.pdf".replace("/", os.sep), after["files"])
        self.assertEqual(sorted(after["files"].values()), sorted(before["files"].values()))  # no data lost

        undo = undo_batch(self.history, res.batch_id)
        self.assertEqual(undo.restored, len(items))
        self.assertEqual(undo.skipped, [])
        self.assertEqual(self.snapshot(), before)  # files AND created folders are gone again
        self.assertIsNone(self.history.latest_undoable())

    def test_never_overwrites_existing_destination(self):
        src = self.make("a.txt", "source")
        dst = self.make("dest/a.txt", "precious")
        res = apply_ops(self.history, [Op("move", src, dst)], "x", self.root)
        self.assertEqual(res.done, 0)
        self.assertEqual(len(res.skipped), 1)
        self.assertEqual(dst.read_text(), "precious")
        self.assertEqual(src.read_text(), "source")
        self.assertEqual(self.history.batches(), [])  # empty batch not recorded

    def test_missing_source_is_skipped_not_fatal(self):
        good = self.make("good.txt")
        ops = [Op("move", self.root / "gone.txt", self.root / "d" / "gone.txt"),
               Op("move", good, self.root / "d" / "good.txt")]
        res = apply_ops(self.history, ops, "x", self.root)
        self.assertEqual((res.done, len(res.skipped)), (1, 1))

    def test_undo_skips_file_that_changed_since_and_keeps_batch_open(self):
        src = self.make("a.txt", "A")
        dst = self.root / "d" / "a.txt"
        res = apply_ops(self.history, [Op("move", src, dst)], "x", self.root)
        dst.unlink()  # user deleted it afterwards
        undo = undo_batch(self.history, res.batch_id)
        self.assertEqual(undo.restored, 0)
        self.assertEqual(len(undo.skipped), 1)

    def test_undo_does_not_clobber_occupied_original_location(self):
        src = self.make("a.txt", "A")
        dst = self.root / "d" / "a.txt"
        res = apply_ops(self.history, [Op("move", src, dst)], "x", self.root)
        self.make("a.txt", "NEW FILE")  # something new now sits at the original path
        undo = undo_batch(self.history, res.batch_id)
        self.assertEqual(len(undo.skipped), 1)
        self.assertEqual((self.root / "a.txt").read_text(), "NEW FILE")
        self.assertEqual(dst.read_text(), "A")

    def test_quarantine_and_rmdir_are_undoable(self):
        tmpf = self.make("junk/file.tmp", "t")
        (self.root / "empty").mkdir()
        before = self.snapshot()
        ops = quarantine_ops(self.root, [tmpf]) + [Op("rmdir", self.root / "empty")]
        res = apply_ops(self.history, ops, "cleanup", self.root)
        self.assertEqual(res.done, 2)
        self.assertFalse(tmpf.exists())
        self.assertFalse((self.root / "empty").exists())
        quarantined = [p for p in self.root.rglob("file.tmp")]
        self.assertEqual(len(quarantined), 1)  # moved, not deleted
        undo_batch(self.history, res.batch_id)
        self.assertEqual(self.snapshot(), before)

    def test_rmdir_refuses_non_empty_folder(self):
        self.make("d/keep.txt")
        res = apply_ops(self.history, [Op("rmdir", self.root / "d")], "x", self.root)
        self.assertEqual(res.done, 0)
        self.assertTrue((self.root / "d" / "keep.txt").exists())

    def test_history_persists_across_instances_and_orders_batches(self):
        from fileflow.core.history import History
        a = self.make("a.txt")
        b = self.make("b.txt")
        r1 = apply_ops(self.history, [Op("move", a, self.root / "x" / "a.txt")], "first", self.root)
        r2 = apply_ops(self.history, [Op("move", b, self.root / "x" / "b.txt")], "second", self.root)
        h2 = History(self.history.db_path)
        self.assertEqual([r["label"] for r in h2.batches()], ["second", "first"])
        self.assertEqual(h2.latest_undoable(), r2.batch_id)
        undo_batch(h2, r2.batch_id)
        self.assertEqual(h2.latest_undoable(), r1.batch_id)

    def test_cleanup_suggestions(self):
        self.make("download.crdownload", "partial")
        self.make("empty.txt", b"")
        self.make("notes.bak", "old")
        self.make("fine.txt", "ok")
        (self.root / "nothing").mkdir()
        sug = {s.path.name: s.kind for s in find_cleanup(scan_folder(self.root))}
        self.assertEqual(sug, {"download.crdownload": "temp", "empty.txt": "empty_file",
                               "notes.bak": "obsolete", "nothing": "empty_dir"})


if __name__ == "__main__":
    unittest.main()
