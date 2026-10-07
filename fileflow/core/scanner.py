"""Real recursive folder scanner."""
from __future__ import annotations

import os
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .filetypes import ext_category
from .utils import QUARANTINE_DIR

# Directories we never descend into (and never count).
SKIP_DIRS = {"$RECYCLE.BIN", "System Volume Information", ".git", "node_modules",
             "__pycache__", ".venv", "venv", QUARANTINE_DIR}
# A folder containing one of these is a project / app: its contents are left alone.
PROJECT_MARKERS = {".git", "package.json", "pyproject.toml", "setup.py", "Cargo.toml", "pom.xml",
                   "build.gradle", "CMakeLists.txt", "Makefile", "go.mod", ".project",
                   "composer.json", "Gemfile"}
PROJECT_MARKER_SUFFIXES = (".sln", ".csproj", ".xcodeproj")

Progress = Callable[[int, int, str], None]


@dataclass(slots=True)
class FileInfo:
    path: Path
    size: int
    mtime: float
    protected: bool = False  # inside a detected project folder

    @property
    def ext(self) -> str:
        return self.path.suffix.lower()


@dataclass
class ScanResult:
    root: Path
    files: list[FileInfo] = field(default_factory=list)
    empty_dirs: list[Path] = field(default_factory=list)  # deepest first
    protected_dirs: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    def largest_files(self, n: int = 100) -> list[FileInfo]:
        return sorted(self.files, key=lambda f: f.size, reverse=True)[:n]

    def folder_sizes(self, n: int = 50) -> list[tuple[Path, int, int]]:
        """(folder, total bytes, file count) for every sub-folder, largest first."""
        sizes: dict[Path, int] = defaultdict(int)
        counts: dict[Path, int] = defaultdict(int)
        for f in self.files:
            p = f.path.parent
            while p != self.root and self.root in p.parents:
                sizes[p] += f.size
                counts[p] += 1
                p = p.parent
        rows = [(p, s, counts[p]) for p, s in sizes.items()]
        return sorted(rows, key=lambda r: r[1], reverse=True)[:n]

    def type_breakdown(self) -> list[tuple[str, int, int]]:
        """(category, file count, bytes), largest first."""
        agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for f in self.files:
            a = agg[ext_category(f.ext)]
            a[0] += 1
            a[1] += f.size
        return sorted(((k, v[0], v[1]) for k, v in agg.items()), key=lambda r: r[2], reverse=True)


def _has_marker(names: set[str]) -> bool:
    if names & PROJECT_MARKERS:
        return True
    return any(n.endswith(PROJECT_MARKER_SUFFIXES) for n in names)


def scan_folder(root: Path | str, progress: Optional[Progress] = None,
                cancel: Optional[threading.Event] = None) -> ScanResult:
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    res = ScanResult(root=root)
    has_content: set[Path] = set()
    children: dict[Path, list[Path]] = {}
    order: list[Path] = []
    protected_flag: dict[Path, bool] = {}
    stack: list[tuple[Path, bool]] = [(root, False)]
    n = 0
    while stack:
        if cancel is not None and cancel.is_set():
            res.cancelled = True
            break
        d, prot = stack.pop()
        order.append(d)
        children[d] = []
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError as e:
            res.errors.append(f"{d}: {e}")
            has_content.add(d)  # unreadable: never call it empty
            continue
        if d != root and not prot and _has_marker({e.name for e in entries}):
            prot = True
            res.protected_dirs.append(d)
        protected_flag[d] = prot
        for e in entries:
            try:
                if e.is_symlink():
                    has_content.add(d)
                    continue
                if e.is_dir(follow_symlinks=False):
                    if e.name in SKIP_DIRS:
                        has_content.add(d)
                        continue
                    child = Path(e.path)
                    children[d].append(child)
                    stack.append((child, prot))
                elif e.is_file(follow_symlinks=False):
                    st = e.stat(follow_symlinks=False)
                    res.files.append(FileInfo(Path(e.path), st.st_size, st.st_mtime, prot))
                    has_content.add(d)
                    n += 1
                    if progress is not None and n % 200 == 0:
                        progress(n, 0, e.path)
                else:
                    has_content.add(d)  # sockets, devices ...
            except OSError as ex:
                res.errors.append(f"{e.path}: {ex}")
                has_content.add(d)
    if progress is not None:
        progress(n, 0, str(root))

    if not res.cancelled:
        empty: dict[Path, bool] = {}
        for d in reversed(order):  # children are always after their parent in `order`
            empty[d] = d not in has_content and all(empty.get(c, False) for c in children[d])
        res.empty_dirs = sorted(
            (d for d in order if d != root and empty.get(d) and not protected_flag.get(d)),
            key=lambda p: len(p.parts), reverse=True)
    return res
