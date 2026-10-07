from fileflow.core.duplicates import PARTIAL_BYTES, find_exact_duplicates
from fileflow.core.scanner import scan_folder
from tests.helpers import TmpCase


class DuplicateTests(TmpCase):
    def groups(self):
        return find_exact_duplicates(scan_folder(self.root).files)

    def test_identical_content_grouped_regardless_of_name(self):
        self.make("photo1.jpg", b"same-bytes", mtime=1000)
        self.make("sub/photo-copy.jpg", b"same-bytes", mtime=2000)
        self.make("other.jpg", b"different!")
        g = self.groups()
        self.assertEqual(len(g), 1)
        self.assertEqual([p.name for p in g[0].paths], ["photo1.jpg", "photo-copy.jpg"])  # oldest first
        self.assertEqual(g[0].wasted, len(b"same-bytes"))
        self.assertEqual(len(g[0].key), 64)

    def test_same_size_different_content_not_grouped(self):
        self.make("a.bin", b"A" * 50)
        self.make("b.bin", b"B" * 50)
        self.assertEqual(self.groups(), [])

    def test_large_files_that_differ_only_after_partial_hash_window(self):
        head = b"H" * PARTIAL_BYTES
        self.make("one.bin", head + b"tail-1")
        self.make("two.bin", head + b"tail-2")
        self.make("three.bin", head + b"tail-1")
        g = self.groups()
        self.assertEqual(len(g), 1)
        self.assertEqual({p.name for p in g[0].paths}, {"one.bin", "three.bin"})

    def test_empty_files_ignored(self):
        self.make("e1.txt", b"")
        self.make("e2.txt", b"")
        self.assertEqual(self.groups(), [])
