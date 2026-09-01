#!/usr/bin/env python3
"""Unit tests for gcloud Drive → public-drive-doc helper (no live Google/n8n)."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gcloud-drive-verify.py"
NOTES = ROOT / "fixtures" / "drive-verify-notes.txt"


def load_mod():
    spec = importlib.util.spec_from_file_location("gcloud_drive_verify", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class FakeResp:
    def __init__(self, payload: dict, status: int = 200):
        self.status = status
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def main() -> None:
    mod = load_mod()
    notes = NOTES.read_text(encoding="utf-8")
    assert "Antoine will publish the Drive webhook runbook" in notes
    assert mod.PUBLIC_WEBHOOK.endswith("/webhook/public-drive-doc")
    assert "meeting-notes" not in Path(mod.PUBLIC_WEBHOOK).name
    assert "paella" not in notes.lower()

    assert mod.run("", notes) == 2

    captured: dict = {}

    def fake_urlopen(req, timeout=60):
        captured.setdefault("urls", []).append(req.full_url)
        captured.setdefault("headers", []).append({str(k).lower(): v for k, v in req.header_items()})
        captured.setdefault("bodies", []).append(req.data)
        if "googleapis.com" in req.full_url:
            return FakeResp(
                {
                    "id": "1GcloudVerifyFileIdNotInline",
                    "name": mod.TITLE,
                    "webViewLink": "https://docs.google.com/document/d/1GcloudVerifyFileIdNotInline/edit",
                    "mimeType": "application/vnd.google-apps.document",
                }
            )
        return FakeResp({}, status=200)

    with mock.patch.object(mod.urllib.request, "urlopen", fake_urlopen):
        with mock.patch("sys.stdout", io.StringIO()) as out:
            code = mod.run("fake-token", notes)
            printed = out.getvalue()
    assert code == 0
    assert "fake-token" not in printed
    assert any("upload/drive/v3/files" in url for url in captured["urls"])
    assert any(url.endswith("/webhook/public-drive-doc") for url in captured["urls"])
    assert not any(url.rstrip("/").endswith("/webhook/meeting-notes") for url in captured["urls"])
    n8n_headers = captured["headers"][1]
    assert "x-webhook-secret" not in n8n_headers
    body = json.loads(captured["bodies"][1].decode("utf-8"))
    assert body["fileId"] == "1GcloudVerifyFileIdNotInline"
    assert "Antoine will publish" in body["text"]
    print("gcloud drive verify ok")


if __name__ == "__main__":
    main()
