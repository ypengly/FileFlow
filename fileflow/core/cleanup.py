"""Cleanup suggestions. These are only *suggestions*; nothing is ever removed automatically."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .filetypes import INSTALLER_EXTS
from .scanner import ScanResult

TEMP_EXTS = {".tmp", ".temp", ".crdownload", ".part", ".partial", ".download", ".swp"}
TEMP_NAMES = {"thumbs.db", ".ds_store"}
OLD_EXTS = {".bak", ".old", ".orig"}
INSTALLER_AGE_DAYS = 90


@dataclass
class Suggestion:
    path: Path
    kind: str     # temp | obsolete | empty_file | empty_dir
    reason: str
    size: int = 0


def find_cleanup(scan: ScanResult, now: float | None = None) -> list[Suggestion]:
    now = now if now is not None else time.time()
    out: list[Suggestion] = []
    for f in scan.files:
        if f.protected:
            continue
        name = f.path.name.lower()
        ext = f.ext
        if f.size == 0:
            out.append(Suggestion(f.path, "empty_file", "empty (0 byte) file", 0))
        elif ext in TEMP_EXTS or name in TEMP_NAMES or name.startswith("~$"):
            out.append(Suggestion(f.path, "temp", "temporary file", f.size))
        elif ext in OLD_EXTS:
            out.append(Suggestion(f.path, "obsolete", f"{ext} backup/leftover file", f.size))
        elif ext in INSTALLER_EXTS and (now - f.mtime) > INSTALLER_AGE_DAYS * 86400:
            days = int((now - f.mtime) // 86400)
            out.append(Suggestion(f.path, "obsolete", f"installer untouched for {days} days", f.size))
    for d in scan.empty_dirs:
        out.append(Suggestion(d, "empty_dir", "empty folder", 0))
    return out
