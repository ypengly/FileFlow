"""Builds the Preview Plan. Pure computation: touches nothing on disk."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .categorizer import classify
from .filetypes import IMAGE_EXTS
from .metadata import file_date, image_info
from .renamer import suggest_name
from .scanner import Progress, ScanResult
from .utils import path_key, same_file

SYSTEM_NAMES = {"desktop.ini", "thumbs.db"}


@dataclass
class PlanItem:
    src: Path
    dst: Path
    action: str          # "move" | "rename" | "move+rename"
    reason: str
    category: str = ""
    enabled: bool = True


def _action(src: Path, dst: Path) -> str:
    if src.parent == dst.parent:
        return "rename"
    return "move+rename" if src.name != dst.name else "move"


def resolve_conflicts(items: list[PlanItem]) -> None:
    """Make every destination unique and never equal to an existing, different file."""
    claimed: set[str] = set()
    for it in items:
        dst, i = it.dst, 1
        while path_key(dst) in claimed or (dst.exists() and not same_file(it.src, dst)):
            dst = it.dst.with_name(f"{it.dst.stem} ({i}){it.dst.suffix}")
            i += 1
        it.dst = dst
        it.action = _action(it.src, dst)
        claimed.add(path_key(dst))


def build_plan(scan: ScanResult, dest_root: Path | str | None = None, rules=(),
               scope: str = "loose", suggest_renames: bool = True,
               ai_hints: dict | None = None, progress: Optional[Progress] = None,
               cancel: Optional[threading.Event] = None) -> list[PlanItem]:
    """scope: 'loose' = only files directly in the scanned folder, 'all' = every file."""
    dest_root = Path(dest_root) if dest_root else scan.root
    ai_hints = ai_hints or {}
    items: list[PlanItem] = []
    total = len(scan.files)
    for i, fi in enumerate(scan.files):
        if cancel is not None and cancel.is_set():
            break
        if progress and i % 100 == 0:
            progress(i, total, str(fi.path))
        if fi.protected:
            continue  # files inside project folders are never touched
        if scope == "loose" and fi.path.parent != scan.root:
            continue
        if fi.path.name.startswith(".") or fi.path.name.lower() in SYSTEM_NAMES:
            continue
        info = image_info(fi.path) if fi.ext in IMAGE_EXTS else None
        when = file_date(fi.path, fi.mtime, info)
        cls = classify(fi.path, when, rules)
        if cls.fallback and fi.path in ai_hints:
            parts = ai_hints[fi.path]
            cls = type(cls)(parts, parts[0], "AI suggestion")
        name, reason = fi.path.name, cls.reason
        if suggest_renames:
            s = suggest_name(fi.path, when)
            if s:
                name = s[0]
                reason = f"{cls.reason}; {s[1]}"
        dst = dest_root.joinpath(*cls.parts) / name
        if dst == fi.path:
            continue  # already where it belongs
        items.append(PlanItem(fi.path, dst, _action(fi.path, dst), reason, cls.category))
    resolve_conflicts(items)
    return items


def summarize(items: list[PlanItem]) -> str:
    active = [i for i in items if i.enabled]
    moved = sum(1 for i in active if i.action in ("move", "move+rename"))
    renamed = sum(1 for i in active if i.action in ("rename", "move+rename"))
    text = f"{moved} file{'s' if moved != 1 else ''} will be moved"
    if renamed:
        text += f", {renamed} renamed"
    return text


def format_preview(items: list[PlanItem], dest_root: Path | str | None = None) -> str:
    """Plain-text preview in the format from the spec."""
    active = [i for i in items if i.enabled]
    lines = [summarize(active), ""]
    for it in active:
        base = Path(dest_root) if dest_root else None
        try:
            rel = it.dst.relative_to(base) if base else it.dst
        except ValueError:
            rel = it.dst
        target = rel.parent.as_posix() + "/" if it.dst.name == it.src.name else rel.as_posix()
        lines += [it.src.name, f"→ {target}", ""]
    return "\n".join(lines).rstrip() + "\n"
