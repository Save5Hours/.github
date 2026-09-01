#!/usr/bin/env python3
"""Sanity-check the Apps Script Drive webhook (no secrets)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apps-script-drive-webhook.js"
SETUP = ROOT / "scripts" / "n8n-publish-apps-script-source.py"
NOTES = ROOT / "fixtures" / "drive-verify-notes.txt"


def load_publisher():
    spec = importlib.util.spec_from_file_location("n8n_publish_apps_script_source", SETUP)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


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
    setup = SETUP.read_text(encoding="utf-8")
    assert "URLSearchParams" in setup
    assert 'get("id")' in setup
    assert "docs.new" in setup
    assert "VERIFY_NOTES" in setup
    html = load_publisher().setup_html(src)
    notes = NOTES.read_text(encoding="utf-8").strip()
    assert "docs.new" in html
    assert "not docs.new" in html
    assert 'a[href="https://docs.new"]' in html
    assert "urlEl.focus()" in html
    assert "paste that URL here" in html
    assert "gcloud-auth-code" in html
    assert 'id="gcloudcode"' in html
    assert "gcloudform" in html
    assert "el.value.replace(/\\s+/g, '')" in html
    assert "asGcloudCode" in html
    assert "sendGcloudCode" in html
    assert "gcloudCodeRe" in html
    assert "Sample notes are filled" in html
    assert "option1b" in html
    assert "novalidate" in html
    assert 'id="copyauth"' in html
    assert "open on a phone already signed into Google" in html
    assert "not Cloud CLI" in html
    assert "Cloud Platform admin" in html
    assert "does not rotate every few minutes" in html
    assert 'id="setupqr"' in html
    assert "Scan on a phone signed into Google" in html
    assert "<svg" in html
    assert load_publisher().DRIVE_SETUP_PAGE in html
    docurl = next(part for part in html.split("<input") if 'id="docurl"' in part)
    assert "required" not in docurl.split(">")[0]
    assert "Drive path verification" in html
    assert notes.splitlines()[0] in html
    assert "Antoine will publish the Drive webhook runbook" in html
    payload = load_publisher().workflow_payload(src)
    methods = {n["parameters"]["path"]: n["parameters"]["httpMethod"] for n in payload["nodes"]}
    assert methods["gcloud-auth-code"] == "POST"
    assert methods["gcloud-auth-url"] == "GET"
    assert methods["drive-setup"] == "GET"
    fake = "https://accounts.google.com/o/oauth2/auth?response_type=code&client_id=test"
    linked = load_publisher().setup_html(src, fake)
    assert 'id="gcloudauth"' in linked
    assert "accounts.google.com/o/oauth2/auth" in linked
    assert "Prefer Option 1" in linked
    assert "gcloud-auth-url" in linked
    assert "cache: 'no-store'" in linked
    assert "setInterval(refreshAuth" in linked
    assert "document.hidden" in linked
    assert "visibilitychange" in linked
    assert 'id="gcloudauth"' in html
    old = "https://accounts.google.com/o/oauth2/auth?state=old&code_challenge=aaaa"
    new = "https://accounts.google.com/o/oauth2/auth?state=new&code_challenge=bbbb"
    assert load_publisher().extract_gcloud_auth_url(f"{old}\n{new}") == new
    wrapped = (
        "    https://accounts.google.com/o/oauth2/auth?response_type=code&client_id=32555\n"
        "940559.apps.googleusercontent.com&redirect_uri=https%3A%2F%2Fsdk.cloud.google.co\n"
        "m%2Fauthcode.html&scope=openid+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive\n"
        "&state=abc&prompt=consent&token_usage=remote&access_type=offline&code_challenge=\n"
        "3-tRYFPjpI8rNIPfuT0yg9Pr_WmhOeYeU_cX\n"
        "UlU9XBs&code_challenge_method=S256\n"
        "Once finished, enter the verification code provided in your browser:"
    )
    unwrapped = load_publisher().extract_gcloud_auth_url(wrapped)
    assert "code_challenge=3-tRYFPjpI8rNIPfuT0yg9Pr_WmhOeYeU_cXUlU9XBs" in unwrapped
    assert "code_challenge_method=S256" in unwrapped
    assert load_publisher().extract_gcloud_auth_url("") == ""
    print("apps script ok")


if __name__ == "__main__":
    main()
