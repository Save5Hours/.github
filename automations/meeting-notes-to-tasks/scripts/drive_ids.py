"""Parse Google Drive folder/file IDs from URLs, logs, and HQ fields."""

from __future__ import annotations

import re

FOLDER_RE = re.compile(
    r"(?:drive\.google\.com/drive/(?:u/\d+/)?folders/|FOLDER_ID\s+|FOLDER_URL\s+\S*?folders/)"
    r"([a-zA-Z0-9_-]{10,})",
    re.I,
)
DOC_RE = re.compile(
    r"(?:docs\.google\.com/document/d/|drive\.google\.com/file/d/|FILE_ID\s+|FILE_URL\s+\S*?/(?:d|file)/)"
    r"([a-zA-Z0-9_-]{10,})",
    re.I,
)
BARE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{10,}$")


def is_real_drive_id(value: str) -> bool:
    text = (value or "").strip()
    return bool(text) and not text.lower().startswith("inline-") and text.upper() != "REPLACE_ME_GEMINI_NOTES_FOLDER_ID"


def folder_id_from(text: str) -> str:
    match = FOLDER_RE.search(text or "")
    if match:
        return match.group(1)
    return ""


def file_id_from(text: str) -> str:
    match = DOC_RE.search(text or "")
    if match:
        candidate = match.group(1)
        if is_real_drive_id(candidate):
            return candidate
    return ""


def parse_drive_refs(*parts: str) -> dict[str, str]:
    blob = "\n".join(p for p in parts if p)
    folder = folder_id_from(blob)
    file_id = file_id_from(blob)
    for part in parts:
        raw = (part or "").strip()
        if not raw:
            continue
        if folder_id_from(raw) or file_id_from(raw):
            continue
        if BARE_ID_RE.match(raw) and is_real_drive_id(raw):
            if not file_id:
                file_id = raw
    return {"folder_id": folder, "file_id": file_id}


def export_url(file_id: str) -> str:
    return f"https://docs.google.com/document/d/{file_id}/export?format=txt"
