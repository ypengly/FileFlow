"""Extension tables shared by the scanner, categorizer and cleanup finder."""
from __future__ import annotations

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff",
              ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw", ".dng", ".svg", ".ico"}
# Formats Pillow can open reliably for EXIF / perceptual hashing.
PIL_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".3gp"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus", ".aiff"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz"}
DOCUMENT_EXTS = {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".xls", ".xlsx", ".ods",
                 ".csv", ".ppt", ".pptx", ".odp", ".pages", ".numbers", ".key", ".epub", ".tex"}
INSTALLER_EXTS = {".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".apk", ".iso"}
FONT_EXTS = {".ttf", ".otf", ".woff", ".woff2"}
CODE_LANG = {
    ".py": "Python", ".ipynb": "Python", ".js": "JavaScript", ".ts": "JavaScript",
    ".jsx": "JavaScript", ".tsx": "JavaScript", ".java": "Java", ".c": "C_Cpp", ".cpp": "C_Cpp",
    ".h": "C_Cpp", ".hpp": "C_Cpp", ".cs": "CSharp", ".go": "Go", ".rs": "Rust", ".rb": "Ruby",
    ".php": "PHP", ".html": "Web", ".css": "Web", ".sh": "Shell", ".bat": "Shell", ".ps1": "Shell",
    ".sql": "SQL", ".kt": "Kotlin", ".swift": "Swift",
}
CODE_EXTS = set(CODE_LANG)

# The categories shown to the user.
CATEGORIES = ["Documents", "Images", "Videos", "Audio", "Code", "Archives",
              "School", "Work", "Finance", "Projects", "Other"]


def ext_category(ext: str) -> str:
    """Broad type of a file from its (lower-case, dotted) extension."""
    if ext in IMAGE_EXTS:
        return "Images"
    if ext in VIDEO_EXTS:
        return "Videos"
    if ext in AUDIO_EXTS:
        return "Audio"
    if ext in ARCHIVE_EXTS:
        return "Archives"
    if ext in CODE_EXTS:
        return "Code"
    if ext in DOCUMENT_EXTS:
        return "Documents"
    return "Other"
