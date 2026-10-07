"""Duplicate detection: size -> partial hash -> full SHA-256, plus optional perceptual hashes."""
from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Optional

from .filetypes import PIL_EXTS
from .scanner import FileInfo, Progress

PARTIAL_BYTES = 64 * 1024
CHUNK = 1024 * 1024


@dataclass
class DupGroup:
    kind: str                 # "exact" or "similar"
    key: str                  # SHA-256 for exact groups, description for similar groups
    paths: list[Path]
    sizes: list[int]

    @property
    def wasted(self) -> int:
        return sum(self.sizes) - max(self.sizes)


def hash_file(path: Path, partial: bool = False) -> str:
    h = sha256()
    with open(path, "rb") as f:
        if partial:
            h.update(f.read(PARTIAL_BYTES))
        else:
            while chunk := f.read(CHUNK):
                h.update(chunk)
    return h.hexdigest()


def find_exact_duplicates(files: Iterable[FileInfo], progress: Optional[Progress] = None,
                          cancel: Optional[threading.Event] = None) -> list[DupGroup]:
    by_size: dict[int, list[FileInfo]] = defaultdict(list)
    for f in files:
        if f.size > 0:
            by_size[f.size].append(f)
    candidates = [g for g in by_size.values() if len(g) > 1]
    total = sum(len(g) for g in candidates)
    done = 0
    groups: list[DupGroup] = []
    for g in candidates:
        by_partial: dict[str, list[FileInfo]] = defaultdict(list)
        for f in g:
            if cancel is not None and cancel.is_set():
                return _sorted(groups)
            try:
                by_partial[hash_file(f.path, partial=True)].append(f)
            except OSError:
                pass
            done += 1
            if progress:
                progress(done, total, str(f.path))
        for pg in by_partial.values():
            if len(pg) < 2:
                continue
            by_full: dict[str, list[FileInfo]] = defaultdict(list)
            for f in pg:
                if cancel is not None and cancel.is_set():
                    return _sorted(groups)
                try:
                    # small files: the partial hash already covered the whole file
                    key = hash_file(f.path, partial=True) if f.size <= PARTIAL_BYTES else hash_file(f.path)
                except OSError:
                    continue
                by_full[key].append(f)
            for key, fg in by_full.items():
                if len(fg) > 1:
                    fg.sort(key=lambda x: (x.mtime, len(str(x.path))))
                    groups.append(DupGroup("exact", key, [x.path for x in fg], [x.size for x in fg]))
    return _sorted(groups)


def _sorted(groups: list[DupGroup]) -> list[DupGroup]:
    return sorted(groups, key=lambda g: g.wasted, reverse=True)


# ---------------------------------------------------------------- perceptual hashing (optional)
def perceptual_available() -> bool:
    try:
        import imagehash  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


def find_similar_images(files: Iterable[FileInfo], threshold: int = 5,
                        exact_groups: Iterable[DupGroup] = (),
                        progress: Optional[Progress] = None,
                        cancel: Optional[threading.Event] = None) -> list[DupGroup]:
    """Group visually similar images (Hamming distance <= threshold on a 64-bit pHash)."""
    if not perceptual_available():
        return []
    import imagehash
    from PIL import Image

    imgs = [f for f in files if f.ext in PIL_EXTS]
    hashes: list[tuple[FileInfo, int]] = []
    for i, f in enumerate(imgs):
        if cancel is not None and cancel.is_set():
            return []
        try:
            with Image.open(f.path) as im:
                hashes.append((f, int(str(imagehash.phash(im)), 16)))
        except Exception:
            pass
        if progress and i % 20 == 0:
            progress(i, len(imgs), str(f.path))

    # Pigeonhole bucketing: split into threshold+1 chunks; hashes within `threshold` bits
    # must share at least one identical chunk, so only same-bucket pairs need comparing.
    k = threshold + 1
    bounds = [(64 * i // k, 64 * (i + 1) // k) for i in range(k)]
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for idx, (_, h) in enumerate(hashes):
        for ci, (lo, hi) in enumerate(bounds):
            buckets[(ci, (h >> lo) & ((1 << (hi - lo)) - 1))].append(idx)

    parent = list(range(len(hashes)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for members in buckets.values():
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                i, j = members[a], members[b]
                if bin(hashes[i][1] ^ hashes[j][1]).count("1") <= threshold:
                    parent[find(i)] = find(j)

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(hashes)):
        clusters[find(i)].append(i)

    exact_sets = [set(g.paths) for g in exact_groups]
    out: list[DupGroup] = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        fis = sorted((hashes[i][0] for i in members), key=lambda x: (x.mtime, len(str(x.path))))
        paths = {f.path for f in fis}
        if any(paths <= s for s in exact_sets):
            continue  # already reported as byte-identical
        out.append(DupGroup("similar", f"perceptual hash distance <= {threshold}",
                            [f.path for f in fis], [f.size for f in fis]))
    return _sorted(out)
