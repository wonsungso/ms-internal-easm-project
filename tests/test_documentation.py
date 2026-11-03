from __future__ import annotations

import json
import re
import struct
from pathlib import Path


def test_screenshot_guide_references_all_captured_images() -> None:
    docs = Path(__file__).parents[1] / "docs"
    guide = docs / "sp-authentication.md"
    manifest = json.loads((docs / "images" / "setup" / "manifest.json").read_text(encoding="utf-8"))
    references = {
        (guide.parent / value).resolve()
        for value in re.findall(r"!\[[^\]]*\]\(([^)]+\.png)\)", guide.read_text(encoding="utf-8"))
    }
    expected = {(docs / "images" / "setup" / image["file"]).resolve() for image in manifest["images"]}
    assert len(expected) == 6
    assert references == expected
    for path in references:
        assert path.is_file(), path


def test_captured_images_are_real_pngs_with_highlight_metadata() -> None:
    directory = Path(__file__).parents[1] / "docs" / "images" / "setup"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["highlight_color"] == "#d40000"
    assert manifest["account_banner_excluded"] is True
    assert manifest["credentials_modified"] is False
    assert set(manifest["credential_counts_after_cancel"].values()) == {0}
    for image in manifest["images"]:
        data = (directory / image["file"]).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert data[12:16] == b"IHDR"
        width, height = struct.unpack(">II", data[16:24])
        assert width >= 300 and height >= 300
        assert image["highlight_count"] > 0
    assert manifest["images"][0]["client_id_masked"] is True
    assert manifest["images"][2]["add_disabled"] is True
    assert manifest["images"][5]["add_disabled"] is True


def test_chatbot_guide_uses_real_masked_highlighted_screenshots() -> None:
    docs = Path(__file__).parents[1] / "docs"
    manifest = json.loads((docs / "images" / "chatbots" / "manifest.json").read_text(encoding="utf-8"))
    guide = (docs / "chatbot-samples.md").read_text(encoding="utf-8")
    assert manifest["account_identifiers_masked"] is True
    assert manifest["synthetic_conversations_only"] is True
    for image in manifest["images"]:
        assert image["file"] in guide
        data = (docs / "images" / "chatbots" / image["file"]).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert image["highlight_count"] > 0
    root = (docs.parent / "README.md").read_text(encoding="utf-8")
    assert "Step" not in root and "오프라인 검증" not in root
    assert "collection-items.md" in root
