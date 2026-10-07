"""Image metadata (EXIF) - optional, needs Pillow."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .filetypes import PIL_EXTS

try:  # Pillow is optional at import time
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


@dataclass
class ImageInfo:
    taken: datetime | None = None
    camera: str | None = None
    size: tuple[int, int] | None = None


def pillow_available() -> bool:
    return Image is not None


def image_info(path: Path) -> ImageInfo:
    info = ImageInfo()
    if Image is None or path.suffix.lower() not in PIL_EXTS:
        return info
    try:
        with Image.open(path) as im:
            info.size = im.size
            exif = im.getexif()
            raw = None
            try:
                raw = exif.get_ifd(0x8769).get(36867)  # DateTimeOriginal
            except Exception:
                pass
            raw = raw or exif.get(306)  # DateTime
            if raw:
                try:
                    info.taken = datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S")
                except ValueError:
                    pass
            cam = exif.get(272)
            if cam:
                info.camera = str(cam).strip()
    except Exception:
        pass
    return info


def file_date(path: Path, mtime: float, info: ImageInfo | None = None) -> datetime:
    if info is not None and info.taken is not None:
        return info.taken
    return datetime.fromtimestamp(mtime)
