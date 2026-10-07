"""Rename assistant: suggests cleaner names. Never renames anything itself."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .filetypes import IMAGE_EXTS, VIDEO_EXTS

GENERIC_FOLDERS = {"downloads", "pictures", "photos", "images", "dcim", "camera", "documents",
                   "desktop", "temp", "tmp", "new folder", "untitled folder", "camera roll",
                   "screenshots", "videos", "misc", "stuff", "files", "backup"}
CAMERA_RE = re.compile(r"^(img|dsc[nf]?|pxl|mvimg|pic|photo|image|vid|mov|wp)[-_ ]?\d[\d_-]*$", re.I)
WHATSAPP_RE = re.compile(r"^whatsapp (image|video)", re.I)
SCREENSHOT_RE = re.compile(r"^(screenshot|screen shot|capture)\b", re.I)


def folder_label(folder: Path) -> str | None:
    """A meaningful folder name (e.g. 'Cambodia Trip') -> 'Cambodia_Trip'; generic ones -> None."""
    name = folder.name
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not words or name.lower() in GENERIC_FOLDERS or re.fullmatch(r"[\d\W]+\w{0,3}", name):
        return None
    return "_".join(w[:1].upper() + w[1:] for w in words)[:40]


def tidy(stem: str) -> str:
    s = re.sub(r"^copy[ _]of[\s_-]+", "", stem, flags=re.I)
    s = re.sub(r"[\s_-]+copy(\s*\(\d+\))?$", "", s, flags=re.I)
    s = re.sub(r"_{2,}", "_", s)
    s = re.sub(r"-{2,}", "-", s)
    s = re.sub(r"\s{2,}", " ", s)
    s = s.strip(" _-.")
    return s or stem


def suggest_name(path: Path, when: datetime) -> tuple[str, str] | None:
    """Return (new filename, reason) or None when the current name is already fine."""
    stem, ext = path.stem, path.suffix.lower()
    date = when.strftime("%Y-%m-%d")
    if ext in IMAGE_EXTS or ext in VIDEO_EXTS:
        kind = "Video" if ext in VIDEO_EXTS else "Photo"
        new = None
        if SCREENSHOT_RE.match(stem):
            new, why = f"{date}_Screenshot_{when:%H%M%S}", "screenshot -> dated name"
        elif CAMERA_RE.match(stem) or WHATSAPP_RE.match(stem):
            digits = re.findall(r"\d+", stem)
            num = digits[-1][-6:] if digits else ""
            label = folder_label(path.parent) or kind
            new = f"{date}_{label}" + (f"_{num}" if num else "")
            why = "camera-style name -> dated name"
        if new:
            return new + ext, why
    new = tidy(stem) + ext
    if new != path.name:
        return new, "tidied name"
    return None
