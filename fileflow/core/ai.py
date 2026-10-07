"""Optional AI folder hints for files the rules could not classify.

Disabled unless FILEFLOW_AI_KEY is set. Only *file names* are sent (never contents or full paths)
to an OpenAI-compatible chat endpoint. Everything else in FileFlow works without this module.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

from .scanner import FileInfo
from .utils import sanitize_parts


class AIError(Exception):
    pass


def ai_configured() -> bool:
    return bool(os.environ.get("FILEFLOW_AI_KEY"))


def _chat(messages: list[dict]) -> str:
    base = os.environ.get("FILEFLOW_AI_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("FILEFLOW_AI_MODEL", "gpt-4o-mini")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps({"model": model, "messages": messages, "temperature": 0}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ.get('FILEFLOW_AI_KEY', '')}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]
    except Exception as e:
        raise AIError(str(e)) from e


def ai_hints_for(files: list[FileInfo], batch: int = 40) -> dict[Path, tuple[str, ...]]:
    """Map each file path to a suggested destination folder (tuple of parts)."""
    if not ai_configured():
        raise AIError("FILEFLOW_AI_KEY is not set")
    by_name: dict[str, list[Path]] = {}
    for f in files:
        by_name.setdefault(f.path.name, []).append(f.path)
    names = list(by_name)
    hints: dict[Path, tuple[str, ...]] = {}
    system = ("You organise files. Given a JSON list of file names, reply with ONLY a JSON object "
              "mapping each file name to a folder path such as 'Documents/Travel' (max 3 levels, "
              "no drive letters). Use 'Other' if unsure.")
    for i in range(0, len(names), batch):
        chunk = names[i:i + batch]
        text = _chat([{"role": "system", "content": system},
                      {"role": "user", "content": json.dumps(chunk)}])
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        try:
            mapping = json.loads(text)
        except json.JSONDecodeError as e:
            raise AIError("AI returned invalid JSON") from e
        for name, dest in mapping.items():
            if name in by_name and isinstance(dest, str):
                parts = sanitize_parts(re.split(r"[\\/]+", dest))
                if parts:
                    for p in by_name[name]:
                        hints[p] = parts
    return hints
