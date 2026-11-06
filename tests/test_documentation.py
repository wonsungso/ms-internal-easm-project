from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from urllib.parse import unquote


def test_screenshot_guide_references_all_captured_images() -> None:
    docs = Path(__file__).parents[1] / "docs"
    guide = docs.parent / "README.md"
    manifest = json.loads((docs / "manifest.json").read_text(encoding="utf-8"))["authentication"]
    references = {
        (guide.parent / value).resolve()
        for value in re.findall(r"!\[[^\]]*\]\(([^)]+\.png)\)", guide.read_text(encoding="utf-8"))
    }
    expected = {(docs / image["file"]).resolve() for image in manifest["images"]}
    assert len(expected) == 13
    assert expected <= references
    for path in references:
        assert path.is_file(), path


def test_captured_images_are_real_pngs_with_highlight_metadata() -> None:
    directory = Path(__file__).parents[1] / "docs"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["authentication"]
    assert manifest["highlight_color"] == "#d40000"
    assert manifest["account_banner_excluded"] is True
    assert manifest["account_identifiers_masked"] is True
    assert "가렸고" in manifest["display_text_editing"]
    assert manifest["application_and_sp_created"] is True
    assert manifest["credentials_modified"] is True
    assert manifest["credential_counts_before_cleanup"] == {"certificates": 1, "client_secrets": 0}
    assert manifest["collection"]["administrator_fallback"] is False
    assert manifest["collection"]["collect_exit"] == 0
    assert manifest["collection"]["issues_preserved"] == 0
    assert manifest["collection"]["agents_found"] == 10
    assert manifest["collection"]["entra_with_consent"]["blueprints"] == 9
    assert manifest["collection"]["entra_with_consent"]["agent_identities"] == 9
    assert manifest["collection"]["mandatory_findings"] == 22
    assert manifest["collection"]["configured_graph_permissions"] == 3
    assert manifest["collection"]["verified_azure_role_assignments"] == 15
    assert manifest["collection"]["assessment_revision"] == 5
    assert manifest["collection"]["identity_mismatch_exit"] == 1
    assert manifest["collection"]["package_exit"] == 0
    for key in ("temporary_app_deleted", "temporary_sp_deleted", "reader_assignments_deleted", "private_key_deleted"):
        assert manifest["cleanup"][key] is True
    for image in manifest["images"]:
        data = (directory / image["file"]).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert data[12:16] == b"IHDR"
        width, height = struct.unpack(">II", data[16:24])
        assert width >= 300 and height >= (
            120 if image.get("capture_element") == "confirmation_dialog" else 300
        )
        assert image["highlight_count"] > 0
    assert manifest["images"][1]["client_id_masked"] is True
    assert manifest["images"][2]["certificate_registered"] is True
    assert manifest["images"][4]["subscription_and_principal_masked"] is True
    assert manifest["images"][5]["configured_permission_count"] == 3
    assert manifest["images"][6]["consent_granted"] is True
    assert {image["file"] for image in manifest["images"] if image.get("captured_on") == "2026-11-05"} >= {
        "imgs/14-cost-reader.png", "imgs/15-log-reader.png", "imgs/16-security-reader.png",
        "imgs/17-foundry-reader.png", "imgs/18-foundry-permissions.png", "imgs/19-entra-confirm.png",
    }


def test_screenshot_notes_match_the_documented_example() -> None:
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "`wasmagent-diagnostic`" in readme
    assert "docs/imgs/12-entra-consent.png" in readme
    step3 = readme.split("## Step 3.", 1)[1].split("## Step 4.", 1)[0]
    for image in ("10-reader-role.png", "17-foundry-reader.png", "12-entra-consent.png"):
        assert f"(docs/imgs/{image})" in step3
    for filename in ("setup.sh", "setup_account.py", "foundry-reader.json"):
        assert f"https://github.com/wonsungso/ms-internal-wasm-project/raw/refs/heads/main/scripts/{filename}" in step3
    assert "bash setup.sh login" in step3 and "bash setup.sh apply" in step3
    assert "bash scripts/setup.sh login" not in step3


def test_summary_table_links_resolve_to_checklist_sections_with_images() -> None:
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    detail = (root / "docs" / "checklist.md").read_text(encoding="utf-8")

    def anchor(heading: str) -> str:
        return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")

    anchors = {anchor(h) for h in re.findall(r"^## (.+)$", detail, re.M)}
    links = re.findall(r"^\| \[([A-Z]{2}-SY-[P\d]+)\]\(docs/checklist\.md#([^)]+)\)", readme, re.M)
    assert len(links) == 31
    assert {target for _, target in links} == anchors
    implemented = re.findall(r"^- \*\*구현:\*\* (?!❌)", detail, re.M)
    assert len(implemented) == 22
    assert len(re.findall(r"^!\[[^\]]+\]\(portal/imgs/[^)]+\.png\)$", detail, re.M)) == 22
    assert "<img" not in readme and not re.search(r"^\|.*!\[", readme, re.M)


def test_summary_marks_added_items_only_in_the_rightmost_column() -> None:
    from wasm_agent.proposals import TITLES

    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    assert "| 수집 | 신규 추가 |" in readme
    rows = re.findall(r"^\| \[([A-Z]{2}-SY-\d+)\].+$", readme, re.M)
    assert len(rows) == 31
    marked = set()
    for line in readme.splitlines():
        match = re.match(r"^\| \[([A-Z]{2}-SY-\d+)\]", line)
        if match:
            last = line.split("|")[-2].strip()
            assert last in ("", "✓")
            if last:
                marked.add(match[1])
    assert marked == TITLES.keys()
    assert "추가 제안 13개" not in readme and "점수 산정에는 포함하지 않음" not in readme


def test_chatbot_guide_uses_real_masked_highlighted_screenshots() -> None:
    docs = Path(__file__).parents[1] / "docs"
    demo = docs.parent / "demo"
    manifest = json.loads((docs / "manifest.json").read_text(encoding="utf-8"))["chatbots"]
    guide = (demo / "README.md").read_text(encoding="utf-8")
    assert manifest["account_identifiers_masked"] is True
    assert manifest["synthetic_conversations_only"] is True
    for image in manifest["images"]:
        assert image["file"] in guide
        data = (demo / image["file"]).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert image["highlight_count"] > 0
    root = (docs.parent / "README.md").read_text(encoding="utf-8")
    assert re.search(r"^## (?:Step )?1\.", root, re.M)
    assert "오프라인 검증" not in root
    assert "docs/guide.md" not in root
    assert "고객사 담당자" in root and "MS WASM 관리자" in root


def test_consolidated_document_links_and_collapsed_demo_are_preserved() -> None:
    root = Path(__file__).parents[1]
    docs = root / "docs"
    assert {path.name for path in docs.glob("*.md")} == {"api-notes.md", "checklist.md"}
    for path in [root / "README.md", *docs.glob("*.md"), *(root / "demo").glob("*.md")]:
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            target = unquote(target.split("#", 1)[0].strip("<>"))
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            assert (path.parent / target).exists(), (path.name, target)
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert readme.count("<details>") == 3
    assert "<details open" not in readme
    assert "수집은 나중에 수동 실행" in readme
    assert "raw-data-<타임스탬프>.json" in readme and "report-<타임스탬프>.xlsx" in readme
    assert "results.zip" not in readme and "report.html" not in readme
    assert "docs/assessment-result-template.xlsx" in readme
    assert "bash demo/run.sh --apply --collect" in readme
    assert "bash demo/run.sh --apply\n" in readme
    manifests = json.loads((docs / "manifest.json").read_text(encoding="utf-8"))
    assert (docs / "imgs").is_dir() and not list(docs.glob("*.png"))
    assert {path.name for path in (docs / "imgs").glob("*.png")} == {
        Path(image["file"]).name for image in manifests["authentication"]["images"]
    }
    assert not (docs / "images").exists()
