from fileflow.core.scanner import scan_folder
from fileflow.core.utils import QUARANTINE_DIR
from tests.helpers import TmpCase


class ScannerTests(TmpCase):
    def test_counts_sizes_and_nesting(self):
        self.make("a.txt", b"12345")
        self.make("sub/b.jpg", b"1234567890")
        self.make("sub/deep/c.pdf", b"x" * 100)
        res = scan_folder(self.root)
        self.assertEqual(len(res.files), 3)
        self.assertEqual(res.total_size, 115)
        self.assertEqual(res.largest_files(1)[0].path.name, "c.pdf")
        cats = {c: n for c, n, _ in res.type_breakdown()}
        self.assertEqual(cats, {"Documents": 2, "Images": 1})
        folders = {p.name: (s, n) for p, s, n in res.folder_sizes()}
        self.assertEqual(folders["sub"], (110, 2))

    def test_empty_dirs_detected_including_nested_empty_chains(self):
        (self.root / "e1" / "e2").mkdir(parents=True)
        (self.root / "full").mkdir()
        self.make("full/f.txt")
        res = scan_folder(self.root)
        names = [p.name for p in res.empty_dirs]
        self.assertEqual(names, ["e2", "e1"])  # deepest first so rmdir works in order

    def test_project_folders_are_protected(self):
        self.make("proj/pyproject.toml")
        self.make("proj/src/main.py")
        self.make("loose.txt")
        res = scan_folder(self.root)
        flags = {f.path.name: f.protected for f in res.files}
        self.assertTrue(flags["main.py"])
        self.assertFalse(flags["loose.txt"])

    def test_quarantine_and_symlinks_skipped(self):
        self.make(f"{QUARANTINE_DIR}/x.txt")
        self.make("real.txt")
        try:
            (self.root / "link.txt").symlink_to(self.root / "real.txt")
        except (OSError, NotImplementedError):
            pass
        res = scan_folder(self.root)
        self.assertEqual([f.path.name for f in res.files], ["real.txt"])
