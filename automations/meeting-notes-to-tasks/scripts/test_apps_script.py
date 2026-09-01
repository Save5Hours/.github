#!/usr/bin/env python3
"""Sanity-check the optional Apps Script Drive webhook (no secrets)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apps-script-drive-webhook.js"
NOTES = ROOT / "fixtures" / "drive-verify-notes.txt"


def main() -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    notes = NOTES.read_text(encoding="utf-8").strip()
    assert "everyMinutes(5)" in src
    assert "function installSyncTrigger(" in src
    assert "function syncFolderDocs_(" in src
    assert "function checkNewMeetingNotes(" in src
    assert "WEBHOOK_SECRET_PASTE" in src
    assert 'WEBHOOK_SECRET_PASTE = ""' in src
    assert "/webhook/meeting-notes-drive" in src
    assert "googleAccessToken" in src
    assert "ScriptApp.getOAuthToken" in src
    assert "public-drive-doc" not in src
    assert "gcloud" not in src.lower()
    assert "gcloud" not in src.lower()
    assert "postWithRetry_" in src
    assert "Utilities.sleep" in src
    assert "not registered" in src
    assert "fileId: file.getId()" in src
    assert "text: text" in src
    for line in notes.splitlines():
        if line.strip():
            assert line in src, line
    print("apps script ok")


if __name__ == "__main__":
    main()
