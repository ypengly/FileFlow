"""The only module that changes files. Every change is journaled for undo.

Guarantees:
* nothing is ever overwritten (an existing destination => the operation is skipped);
* nothing is ever permanently deleted ("cleanup" moves files into a quarantine folder);
* every operation is written to the SQLite journal *before* it runs, so Undo can always
  restore the previous state - even after a crash.
"""
from __future__ import annotations

import errno
import os
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .history import ACTIVE, History
from .scanner import Progress
from .utils import QUARANTINE_DIR, path_key, same_file, unique_path


@dataclass
class Op:
    kind: str                 # move | rename | move+rename | quarantine | rmdir
    src: Path
    dst: Path | None = None


@dataclass
class ApplyResult:
    batch_id: int | None = None
    done: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class UndoResult:
    restored: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)


class SkipOp(Exception):
    pass


def _missing_dirs(p: Path) -> list[Path]:
    out = []
    while not p.exists() and p != p.parent:
        out.append(p)
        p = p.parent
    return out[::-1]


def safe_move(src: Path, dst: Path) -> None:
    """Move a file without ever overwriting. Verifies cross-device copies before removing source."""
    if dst.exists() and not (src.exists() and same_file(src, dst) and str(src) != str(dst)):
        raise FileExistsError(str(dst))
    if src.exists() and dst.exists() and same_file(src, dst):  # case-only rename
        tmp = src.with_name(src.name + ".fileflow-tmp")
        os.rename(src, tmp)
        os.rename(tmp, dst)
        return
    try:
        os.rename(src, dst)
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
        try:
            shutil.copy2(src, dst)
            if dst.stat().st_size != src.stat().st_size:
                raise OSError("copy verification failed (size mismatch)")
        except Exception:
            if dst.exists():
                dst.unlink()
            raise
        src.unlink()


def quarantine_ops(root: Path, paths: Iterable[Path], stamp: str | None = None) -> list[Op]:
    stamp = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    base = Path(root) / QUARANTINE_DIR / stamp
    taken: set[str] = set()
    ops = []
    for p in paths:
        try:
            rel = p.relative_to(root)
        except ValueError:
            rel = Path("external") / p.name
        dst = unique_path(base / rel, taken)
        taken.add(path_key(dst))
        ops.append(Op("quarantine", p, dst))
    return ops


def ops_from_plan(items) -> list[Op]:
    return [Op(i.action, i.src, i.dst) for i in items if i.enabled]


def apply_ops(history: History, ops: list[Op], label: str, root: Path | str,
              progress: Optional[Progress] = None,
              cancel: Optional[threading.Event] = None) -> ApplyResult:
    res = ApplyResult()
    if not ops:
        return res
    batch = history.begin_batch(label, str(root))
    res.batch_id = batch
    total = len(ops)
    for seq, op in enumerate(ops):
        if cancel is not None and cancel.is_set():
            break
        if progress:
            progress(seq, total, str(op.src))
        try:
            _run_op(history, batch, seq, op)
            res.done += 1
        except SkipOp as e:
            res.skipped.append((str(op.src), str(e)))
        except Exception as e:  # noqa: BLE001 - report and continue with the rest
            res.failed.append((str(op.src), str(e)))
    if progress:
        progress(total, total, "")
    history.discard_if_empty(batch)
    if history.remaining_ops(batch) == 0:
        res.batch_id = None if res.done == 0 else batch
    return res


def _run_op(history: History, batch: int, seq: int, op: Op) -> None:
    if op.kind == "rmdir":
        if op.src.is_symlink() or not op.src.is_dir():
            raise SkipOp("folder no longer exists")
        if any(op.src.iterdir()):
            raise SkipOp("folder is no longer empty")
        op_id = history.add_op(batch, seq, "rmdir", op.src, None)
        try:
            os.rmdir(op.src)
        except Exception:
            history.set_op_status(op_id, "failed")
            raise
        history.set_op_status(op_id, "done")
        return

    src, dst = op.src, op.dst
    if dst is None or str(src) == str(dst):
        raise SkipOp("nothing to do")
    if src.is_symlink() or not src.is_file():
        raise SkipOp("source file no longer exists")
    if dst.exists() and not (same_file(src, dst) and str(src) != str(dst)):
        raise SkipOp("destination already exists (never overwritten)")
    op_id = history.add_op(batch, seq, op.kind, src, dst)  # journal first
    try:
        created = _missing_dirs(dst.parent)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if created:
            history.add_created_dirs(batch, created)
        safe_move(src, dst)
    except Exception:
        history.set_op_status(op_id, "failed")
        raise
    history.set_op_status(op_id, "done")


def undo_batch(history: History, batch_id: int, progress: Optional[Progress] = None,
               cancel: Optional[threading.Event] = None) -> UndoResult:
    res = UndoResult()
    ops = [o for o in history.ops(batch_id) if o["status"] in ACTIVE]
    total = len(ops)
    for n, o in enumerate(reversed(ops)):
        if cancel is not None and cancel.is_set():
            break
        if progress:
            progress(n, total, o["src"])
        src = Path(o["src"])
        dst = Path(o["dst"]) if o["dst"] else None
        try:
            if o["kind"] == "rmdir":
                src.mkdir(parents=True, exist_ok=True)
            else:
                if not dst.exists():
                    if o["status"] == "pending" and src.exists():
                        history.set_op_status(o["id"], "undone")  # crashed before the move happened
                        continue
                    res.skipped.append((str(dst), "file is no longer at the moved location"))
                    continue
                if src.exists():
                    res.skipped.append((str(src), "original location is occupied; left in place"))
                    continue
                src.parent.mkdir(parents=True, exist_ok=True)
                safe_move(dst, src)
            history.set_op_status(o["id"], "undone")
            res.restored += 1
        except Exception as e:  # noqa: BLE001
            res.skipped.append((str(dst or src), str(e)))
    # remove folders this batch created, but only if they are empty now
    for d in sorted(history.created_dirs(batch_id), key=lambda p: len(p.parts), reverse=True):
        try:
            os.rmdir(d)
        except OSError:
            pass
    if history.remaining_ops(batch_id) == 0:
        history.mark_batch_undone(batch_id)
    return res
