import os
import tempfile
import unittest
from pathlib import Path

from fileflow.core.history import History


class TmpCase(unittest.TestCase):
    """Gives each test a scratch folder (self.root) and an isolated history DB."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.root = base / "messy"
        self.root.mkdir()
        self.history = History(base / "db" / "history.db")

    def make(self, rel: str, data: bytes | str = b"x", mtime: float | None = None) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data.encode() if isinstance(data, str) else data)
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def snapshot(self) -> dict:
        """{relative path: content} of every file plus the set of directories."""
        files, dirs = {}, set()
        for dp, dn, fn in os.walk(self.root):
            for d in dn:
                dirs.add(str((Path(dp) / d).relative_to(self.root)))
            for f in fn:
                p = Path(dp) / f
                files[str(p.relative_to(self.root))] = p.read_bytes()
        return {"files": files, "dirs": dirs}
