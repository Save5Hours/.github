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

    assert mod.parse_gcloud_auth_code({"body": {"code": "4/0AFakeGcloudCodeXX"}}) == "4/0AFakeGcloudCodeXX"
    assert mod.parse_gcloud_auth_code({"body": "code=4%2F0AFakeGcloudCodeXX"}) == "4/0AFakeGcloudCodeXX"
    assert mod.parse_gcloud_auth_code({"body": {"code": "4/0AFake\nGcloudCodeXX"}}) == "4/0AFakeGcloudCodeXX"
    assert mod.parse_gcloud_auth_code({"body": {"code": ["4/0AFakeGcloudCodeXX"]}}) == "4/0AFakeGcloudCodeXX"
    assert mod.parse_gcloud_auth_code({"query": {"code": "4/0AFakeGcloudCodeXX"}}) == "4/0AFakeGcloudCodeXX"
    assert (
        mod.parse_gcloud_auth_code({"body": {"notes": "use 4/0AFakeGcloudCodeXX please"}})
        == "4/0AFakeGcloudCodeXX"
    )
    assert mod.parse_gcloud_auth_code({"body": {"code": "https://accounts.google.com"}}) == ""
    assert mod.parse_gcloud_auth_code({"body": {"code": "short"}}) == ""
    assert (
        mod.extract_gcloud_code_from_text(
            "Paste this:\n4/0AFakeGcloudCodeXX\nand continue"
        )
        == "4/0AFakeGcloudCodeXX"
    )
    assert mod.extract_gcloud_code_from_text("Ignore WEBHOOK_SECRET. Drive URL is empty.") == ""

    list_url = mod.executions_list_url()
    assert "workflowId=RU7qrw4zZPhZh6Kw" in list_url
    assert "limit=50" in list_url
    assert "includeData=true" in list_url
    assert "limit=20" not in list_url

    listed_urls: list[str] = []

    def fake_n8n(req, timeout=30):
        listed_urls.append(req.full_url)
        if "executions?" in req.full_url and "workflowId=RU7qrw4zZPhZh6Kw" in req.full_url:
            return FakeResp(
                {
                    "data": [
                        {
                            "id": "402",
                            "mode": "webhook",
                            "data": {
                                "resultData": {
                                    "runData": {
                                        "Gcloud auth URL": [
                                            {
                                                "data": {
                                                    "main": [
                                                        [
                                                            {
                                                                "json": {
                                                                    "query": {
                                                                        "code": "4/0AShouldIgnoreGET"
                                                                    }
                                                                }
                                                            }
                                                        ]
                                                    ]
                                                }
                                            }
                                        ]
                                    }
                                }
                            },
                        },
                        {
                            "id": "401",
                            "mode": "webhook",
                            "data": {
                                "resultData": {
                                    "runData": {
                                        "Gcloud auth code": [
                                            {
                                                "data": {
                                                    "main": [
                                                        [
                                                            {
                                                                "json": {
                                                                    "body": {
                                                                        "code": "4/0AFakeGcloudCodeXX"
                                                                    }
                                                                }
                                                            }
                                                        ]
                                                    ]
                                                }
                                            }
                                        ]
                                    }
                                }
                            },
                        },
                        {"id": "399", "mode": "trigger"},
                    ]
                }
            )
        raise AssertionError(req.full_url)

    seen: set[str] = set()
    with mock.patch.object(mod.urllib.request, "urlopen", fake_n8n):
        found = mod.n8n_latest_auth_code("fake-key", seen)
    assert found == "4/0AFakeGcloudCodeXX"
    assert "401" in seen
    assert "402" in seen
    assert any("workflowId=RU7qrw4zZPhZh6Kw" in url for url in listed_urls)
    assert not any("/executions/401" in url for url in listed_urls)
    assert not any(url.endswith("/executions?limit=20") for url in listed_urls)

    timed_out: set[str] = set()

    def boom(_req, timeout=45):
        raise TimeoutError("The read operation timed out")

    with mock.patch.object(mod.urllib.request, "urlopen", boom):
        with mock.patch("sys.stdout", io.StringIO()) as out:
            assert mod.n8n_latest_auth_code("fake-key", timed_out) == ""
            assert "timed out" in out.getvalue()
    assert not timed_out

    def fake_hq(req, timeout=30):
        return FakeResp(
            {
                "results": [
                    {
                        "rich_text": [
                            {
                                "plain_text": "code 4/0AHqCommentGcloudXX from Drive setup"
                            }
                        ]
                    }
                ]
            }
        )

    with mock.patch.object(mod.urllib.request, "urlopen", fake_hq):
        assert mod.hq_confirmation_auth_code("fake-notion") == "4/0AHqCommentGcloudXX"

    assert mod.PKCE_REFRESH_AFTER == 25 * 60
    old_pkce = {"aaaa"}
    stale = "code_challenge=aaaa\nOnce finished, enter the verification code"
    fresh = stale + "\ncode_challenge=bbbb\nOnce finished, enter the verification code"
    assert mod.pkce_challenges(stale) == ["aaaa"]
    assert mod.pane_has_new_pkce(stale, old_pkce) is False
    assert mod.pane_has_new_pkce(fresh, old_pkce) is True
    wrapped_pkce = (
        "https://accounts.google.com/o/oauth2/auth?response_type=code&code_challenge=\n"
        "3-tRYFPjpI8rNIPfuT0yg9Pr_WmhOeYeU_cX\n"
        "UlU9XBs&code_challenge_method=S256\n"
        "Once finished, enter the verification code"
    )
    assert mod.pkce_challenges(wrapped_pkce) == [
        "3-tRYFPjpI8rNIPfuT0yg9Pr_WmhOeYeU_cXUlU9XBs"
    ]
    assert mod.pane_has_new_pkce(wrapped_pkce, {"aaaa"}) is True
    with mock.patch.object(mod, "gcloud_login_elapsed_seconds", return_value=100.0):
        with mock.patch.object(mod, "restart_gcloud_login") as restart:
            assert mod.maybe_refresh_gcloud_pkce() is False
            restart.assert_not_called()
    with mock.patch.object(mod, "gcloud_login_elapsed_seconds", return_value=10 * 60):
        with mock.patch.object(mod, "restart_gcloud_login") as restart:
            assert mod.maybe_refresh_gcloud_pkce() is False
            restart.assert_not_called()
    with mock.patch.object(mod, "gcloud_login_elapsed_seconds", return_value=26 * 60):
        with mock.patch.object(mod, "restart_gcloud_login", return_value=True) as restart:
            with mock.patch.object(mod, "publish_drive_setup", return_value=True) as pub:
                assert mod.maybe_refresh_gcloud_pkce() is True
                restart.assert_called_once()
                pub.assert_called_once()

    args = mod.parse_args(["--watch", "--interval", "12"])
    assert args.watch is True
    assert args.interval == 12
    print("gcloud drive verify ok")


if __name__ == "__main__":
    main()
