"""SQLite-backed operation history (used for undo) and small settings store."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches(
    id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT NOT NULL, label TEXT NOT NULL,
    root TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS ops(
    id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL, seq INTEGER NOT NULL,
    kind TEXT NOT NULL, src TEXT NOT NULL, dst TEXT, status TEXT NOT NULL DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS created_dirs(batch_id INTEGER NOT NULL, path TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""
ACTIVE = ("done", "pending")  # op states that can still be undone


def default_db_path() -> Path:
    """FILEFLOW_HOME overrides; else %LOCALAPPDATA%/FileFlow on Windows; else ~/.fileflow."""
    if os.environ.get("FILEFLOW_HOME"):
        return Path(os.environ["FILEFLOW_HOME"]) / "history.db"
    if os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "FileFlow" / "history.db"
    return Path.home() / ".fileflow" / "history.db"


class History:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(self.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # -- batches / ops
    def begin_batch(self, label: str, root: str) -> int:
        with self._conn() as c:
            return c.execute("INSERT INTO batches(created,label,root) VALUES(?,?,?)",
                             (datetime.now().isoformat(timespec="seconds"), label, str(root))).lastrowid

    def add_op(self, batch_id: int, seq: int, kind: str, src: Path, dst: Path | None) -> int:
        with self._conn() as c:
            return c.execute("INSERT INTO ops(batch_id,seq,kind,src,dst) VALUES(?,?,?,?,?)",
                             (batch_id, seq, kind, str(src), str(dst) if dst else None)).lastrowid

    def set_op_status(self, op_id: int, status: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE ops SET status=? WHERE id=?", (status, op_id))

    def add_created_dirs(self, batch_id: int, paths) -> None:
        with self._conn() as c:
            c.executemany("INSERT INTO created_dirs(batch_id,path) VALUES(?,?)",
                          [(batch_id, str(p)) for p in paths])

    def created_dirs(self, batch_id: int) -> list[Path]:
        with self._conn() as c:
            return [Path(r["path"]) for r in
                    c.execute("SELECT path FROM created_dirs WHERE batch_id=?", (batch_id,))]

    def ops(self, batch_id: int) -> list[sqlite3.Row]:
        with self._conn() as c:
            return c.execute("SELECT * FROM ops WHERE batch_id=? ORDER BY seq", (batch_id,)).fetchall()

    def batches(self) -> list[sqlite3.Row]:
        with self._conn() as c:
            return c.execute(
                "SELECT b.*, (SELECT COUNT(*) FROM ops o WHERE o.batch_id=b.id AND o.status!='failed')"
                " AS op_count FROM batches b ORDER BY b.id DESC").fetchall()

    def latest_undoable(self) -> int | None:
        with self._conn() as c:
            r = c.execute("SELECT id FROM batches WHERE undone=0 ORDER BY id DESC LIMIT 1").fetchone()
            return r["id"] if r else None

    def remaining_ops(self, batch_id: int) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM ops WHERE batch_id=? AND status IN ('done','pending')",
                             (batch_id,)).fetchone()[0]

    def mark_batch_undone(self, batch_id: int) -> None:
        with self._conn() as c:
            c.execute("UPDATE batches SET undone=1 WHERE id=?", (batch_id,))

    def discard_if_empty(self, batch_id: int) -> None:
        with self._conn() as c:
            n = c.execute("SELECT COUNT(*) FROM ops WHERE batch_id=?", (batch_id,)).fetchone()[0]
            if n == 0:
                c.execute("DELETE FROM batches WHERE id=?", (batch_id,))
                c.execute("DELETE FROM created_dirs WHERE batch_id=?", (batch_id,))

    # -- settings
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._conn() as c:
            r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return r["value"] if r else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
