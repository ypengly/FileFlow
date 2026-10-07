"""Rule-based smart categories. Works fully offline, no AI needed."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .filetypes import (CODE_LANG, FONT_EXTS, INSTALLER_EXTS, ext_category)


@dataclass(frozen=True)
class CustomRule:
    keyword: str
    dest: tuple[str, ...]


@dataclass(frozen=True)
class Classification:
    parts: tuple[str, ...]  # destination folder, relative to the destination root
    category: str           # one of filetypes.CATEGORIES (or a custom name)
    reason: str
    fallback: bool = False  # True when nothing matched ("Other")


SCREENSHOT = {"screenshot", "screenshots", "screencap", "screenshare"}
TRAVEL = {"vacation", "trip", "holiday", "holidays", "travel", "tour", "journey"}

# (keyword tokens, destination, category, reason) - first match wins, documents only.
DOC_RULES = [
    ({"invoice", "invoices", "receipt", "receipts", "bill", "bills", "billing"},
     ("Documents", "Finance", "Invoices"), "Finance", "looks like an invoice/receipt"),
    ({"tax", "taxes", "bank", "statement", "payslip", "salary", "budget", "expenses", "insurance"},
     ("Documents", "Finance"), "Finance", "finance keyword"),
    ({"homework", "assignment", "lecture", "syllabus", "exam", "thesis", "essay",
      "coursework", "quiz", "lesson"},
     ("Documents", "School"), "School", "school keyword"),
    ({"resume", "cv", "contract", "proposal", "meeting", "minutes", "agenda", "report", "offer"},
     ("Documents", "Work"), "Work", "work keyword"),
    ({"notes", "note", "todo", "readme", "ideas"},
     ("Projects", "Notes"), "Projects", "looks like project notes"),
    ({"project", "projects", "draft", "spec"},
     ("Projects",), "Projects", "project keyword"),
]


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def classify(path: Path, when: datetime, rules=()) -> Classification:
    name = path.name.lower()
    parent = path.parent.name.lower()
    ext = path.suffix.lower()

    for r in rules:  # user-defined rules always win
        k = r.keyword.lower().strip()
        if k and r.dest and (k in name or k in parent):
            return Classification(r.dest, r.dest[0], f'custom rule "{r.keyword}"')

    toks = tokenize(path.stem)
    ptoks = tokenize(path.parent.name)
    cat = ext_category(ext)

    if cat == "Images":
        if toks & SCREENSHOT:
            return Classification(("Pictures", "Screenshots"), "Images", "screenshot")
        if (toks | ptoks) & TRAVEL:
            return Classification(("Pictures", "Vacation"), "Images", "travel/vacation keyword")
        if "wallpaper" in toks or "wallpapers" in toks:
            return Classification(("Pictures", "Wallpapers"), "Images", "wallpaper")
        return Classification(("Pictures", str(when.year)), "Images", f"image dated {when.year}")
    if cat == "Videos":
        return Classification(("Videos",), "Videos", "video file")
    if cat == "Audio":
        return Classification(("Audio",), "Audio", "audio file")
    if cat == "Archives":
        return Classification(("Archives",), "Archives", "archive")
    if cat == "Code":
        return Classification(("Code", CODE_LANG[ext]), "Code", f"{CODE_LANG[ext]} source")
    if cat == "Documents":
        for kw, dest, category, why in DOC_RULES:
            if toks & kw:
                return Classification(dest, category, why)
        return Classification(("Documents",), "Documents", "document")
    if ext in INSTALLER_EXTS:
        return Classification(("Other", "Installers"), "Other", "installer")
    if ext in FONT_EXTS:
        return Classification(("Other", "Fonts"), "Other", "font")
    return Classification(("Other",), "Other", "unrecognised type", fallback=True)
