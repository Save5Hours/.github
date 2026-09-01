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
    assert "meeting-notes-drive" in src
    assert "googleAccessToken" in src
    assert "Antoine will publish the Drive webhook runbook" in src
    assert "WEBHOOK_SECRET" not in src
    print("colab notebook ok")


if __name__ == "__main__":
    main()
