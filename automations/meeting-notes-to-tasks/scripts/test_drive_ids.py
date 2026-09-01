#!/usr/bin/env python3
"""Unit tests for Drive URL / log parsing."""

from __future__ import annotations

from drive_ids import file_id_from, folder_id_from, is_real_drive_id, parse_drive_refs


def main() -> None:
    folder_url = "https://drive.google.com/drive/folders/1AbCdefghijKLmnopQRstuVWXyz0123456"
    doc_url = "https://docs.google.com/document/d/1DocVerifyFileIdNotInline99/edit"
    log = "HTTP 200\nFOLDER_URL " + folder_url + "\nFILE_ID 1DriveVerifyFileIdNotInline\n"
    assert folder_id_from(folder_url) == "1AbCdefghijKLmnopQRstuVWXyz0123456"
    assert file_id_from(doc_url) == "1DocVerifyFileIdNotInline99"
    assert (
        file_id_from("https://docs.google.com/document/u/0/d/1DocVerifyFileIdNotInline99/edit")
        == "1DocVerifyFileIdNotInline99"
    )
    parsed = parse_drive_refs(log, doc_url)
    assert parsed["folder_id"] == "1AbCdefghijKLmnopQRstuVWXyz0123456"
    assert parsed["file_id"] == "1DriveVerifyFileIdNotInline"
    assert parse_drive_refs("inline-15616df3") == {"folder_id": "", "file_id": ""}
    assert not is_real_drive_id("inline-15616df3")
    assert is_real_drive_id("1DriveVerifyFileIdNotInline")
    assert parse_drive_refs("1BareFileIdFromHqTask")["file_id"] == "1BareFileIdFromHqTask"
    assert parse_drive_refs("apps-script-source")["file_id"] == ""
    assert parse_drive_refs("drive-setup")["file_id"] == ""
    print("drive id parse ok")


if __name__ == "__main__":
    main()
