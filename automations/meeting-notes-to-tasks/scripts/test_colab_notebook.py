#!/usr/bin/env python3
"""Sanity-check the Colab Drive verify notebook (no secrets)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NB = ROOT / "scripts" / "colab_drive_verify.ipynb"


def main() -> None:
    nb = json.loads(NB.read_text(encoding="utf-8"))
    src = "".join(nb["cells"][1]["source"])
    md = "".join(nb["cells"][0]["source"])
    assert "meeting-notes-drive" in src
    assert "public-drive-doc" in src
    assert "MediaInMemoryUpload" in src
    assert "googleAccessToken" in src
    assert "post_with_retry" in src
    assert "if public.status_code >= 300 and token" in src
    assert "drive_ok" in src
    assert "Antoine will publish the Drive webhook runbook" in src
    assert "WEBHOOK_SECRET" not in src
    assert "You do **not** need an n8n login or `WEBHOOK_SECRET`" in md
    print("colab notebook ok")


if __name__ == "__main__":
    main()
