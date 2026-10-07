from __future__ import annotations

import os
import re
from pathlib import Path

QUARANTINE_DIR = "_FileFlow_Quarantine"

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def human_size(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"  # pragma: no cover


def path_key(p: Path | str) -> str:
    """Case-insensitive comparison key (conservative on every platform)."""
    return os.path.normcase(str(p)).casefold()


def same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def sanitize_part(s: str) -> str:
    s = _ILLEGAL.sub("", str(s)).strip().strip(".").strip()[:80].strip()
    if not s or s in (".", ".."):
        return ""
    if s.split(".")[0].upper() in _RESERVED:
        s = "_" + s
    return s


def sanitize_parts(parts, max_depth: int = 3) -> tuple[str, ...]:
    cleaned = [p for p in (sanitize_part(x) for x in parts) if p]
    return tuple(cleaned[:max_depth])


def unique_path(p: Path, taken: set[str] | None = None) -> Path:
    """Return p, or 'name (n).ext' if p exists or is already claimed."""
    taken = taken if taken is not None else set()
    cand, i = p, 1
    while cand.exists() or path_key(cand) in taken:
        cand = p.with_name(f"{p.stem} ({i}){p.suffix}")
        i += 1
    return cand
