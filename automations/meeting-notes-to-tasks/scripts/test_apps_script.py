#!/usr/bin/env python3
"""Sanity-check the Apps Script Drive webhook (no secrets)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apps-script-drive-webhook.js"


def main() -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    assert "function verifyDrivePath(" in src
    assert "PUBLIC_WEBHOOK" in src
    assert "public-drive-doc" in src
    assert "meeting-notes-drive" in src
    assert "postWithRetry_" in src
    assert "Utilities.sleep" in src
    assert "not registered" in src
    assert "ScriptApp.getOAuthToken" in src
    assert "ANYONE_WITH_LINK" in src
    assert "WEBHOOK_SECRET_PASTE" in src
    assert 'WEBHOOK_SECRET_PASTE = ""' in src
    public_idx = src.index("PUBLIC_WEBHOOK")
    drive_idx = src.index("DEFAULT_WEBHOOK")
    assert public_idx < drive_idx
    post_idx = src.index("function postNote_")
    public_post = src.index("postWithRetry_(PUBLIC_WEBHOOK", post_idx)
    drive_post = src.index("postWithRetry_(webhookUrl", post_idx)
    assert public_post < drive_post
    print("apps script ok")


if __name__ == "__main__":
    main()
