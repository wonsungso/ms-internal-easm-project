from __future__ import annotations

import hashlib
import os
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock

from easm_agent.models import load_criteria
from easm_agent.proposals import DOMAINS, TITLES
from scripts.assessment_descriptions import ITEM_DETAILS
from scripts.merge_assessment import (
    ROOT,
    SHEET_CRITERIA,
    SOURCE_SHEET,
    Q,
    merge_assessment,
    text_cell,
    xml_bytes,
)
from scripts.proposal_levels import LEVELS

UNTOUCHED = (
    "xl/worksheets/sheet1.xml", "xl/worksheets/sheet3.xml",
    "xl/styles.xml", "xl/sharedStrings.xml", "xl/theme/theme1.xml", "docMetadata/LabelInfo.xml",
)


def test_office_compatibility_prefixes_survive_serialization() -> None:
    raw = (
        b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        b'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        b'xmlns:x15="http://schemas.microsoft.com/office/spreadsheetml/2010/11/main" '
        b'xmlns:xr="http://schemas.microsoft.com/office/spreadsheetml/2014/revision" '
        b'mc:Ignorable="x15 xr"><mc:AlternateContent><mc:Choice Requires="x15"/>'
        b'<mc:Choice xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main" Requires="x14"/>'
        b'</mc:AlternateContent></workbook>'
    )
    serialized = xml_bytes(ET.fromstring(raw), raw)
    namespaces = dict(value for _, value in ET.iterparse(BytesIO(serialized), events=("start-ns",)))
    assert {"mc", "x15", "xr", "x14"} <= namespaces.keys()
    root = ET.fromstring(serialized)
    compatibility = "http://schemas.openxmlformats.org/markup-compatibility/2006"
    assert root.get(f"{{{compatibility}}}Ignorable") == "x15 xr"
    choice = root.find(f"{{{compatibility}}}AlternateContent/{{{compatibility}}}Choice")
    assert choice is not None and choice.get("Requires") == "x15"


def test_rejects_source_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "model.xlsx"
    source.write_bytes(b"not used")
    with pytest.raises(ValueError, match="덮어쓰기"):
        merge_assessment(source, tmp_path / "." / "model.xlsx")
    assert source.read_bytes() == b"not used"


@pytest.fixture
def source() -> Path:
    path = os.environ.get("ASSESSMENT_SOURCE")
    if not path:
        pytest.skip("실제 원본 검증은 ASSESSMENT_SOURCE 지정 시 실행")
    return Path(path)


def test_merged_workbook_keeps_original_and_adds_proposals_in_domain_blocks(
    source: Path, tmp_path: Path,
) -> None:
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "merged.xlsx"
    assert merge_assessment(source, output)["merged_proposals"] == 12
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    with ZipFile(source) as old, ZipFile(output) as new:
        assert old.namelist() == new.namelist()
        for name in UNTOUCHED:
            assert old.read(name) == new.read(name), name
    original = load_workbook(source)[SOURCE_SHEET]
    merged_book = load_workbook(output)
    assert merged_book.sheetnames == load_workbook(source).sheetnames
    merged = merged_book[SOURCE_SHEET]
    assert merged.max_row == original.max_row + 11
    original_rows = [
        [cell.value for cell in row] for row in original.iter_rows(min_row=1)
        if row[1].value != "OE-SY-15"
    ]
    kept = [
        [cell.value for cell in row] for row in merged.iter_rows(min_row=1)
        if str(row[1].value) not in DOMAINS
    ]
    assert len(kept) == len(original_rows)
    for number, (old, new) in enumerate(zip(original_rows, kept, strict=True), 1):
        if number >= 5 and "-SY-" not in str(old[1]):
            assert new[:5] == old[:5]
            assert new[5].startswith(old[5])
    seen = {}
    for row in merged.iter_rows(min_row=5):
        code = row[1].value
        if code in DOMAINS:
            seen[code] = row
            assert row[2].value == DOMAINS[code][0]
            assert row[4].value == "System Evidence" and TITLES[code] in row[5].value
            assert [row[col].value for col in range(6, 11)] == list(LEVELS[code][:5])
            assert row[11].value == LEVELS[code][5]
            assert row[13].value in (None, "")
            assert all(len(text) <= 70 and "\n" not in text for text in LEVELS[code])
    assert seen.keys() == DOMAINS.keys()
    covered = set()
    for token in str(merged.data_validations.dataValidation[0].sqref).split():
        start, _, end = token.partition(":")
        covered.update(range(int(start[1:]), int((end or start)[1:]) + 1))
    for row in seen.values():
        assert row[1].row in covered
    assert covered == set(range(5, merged.max_row + 1))
    sheet5 = merged_book.worksheets[4]
    assert [c.value for r in sheet5.iter_rows(max_row=58) for c in r if str(c.value).startswith("=")] == [
        c.value for r in load_workbook(source).worksheets[4].iter_rows() for c in r
        if str(c.value).startswith("=")
    ]


def test_delivered_workbook_preserves_user_formatting_and_is_idempotent(tmp_path: Path) -> None:
    delivered = ROOT / "docs" / "assessment-result-template.xlsx"
    rebuilt = tmp_path / "rebuilt.xlsx"
    merge_assessment(delivered, rebuilt)
    with ZipFile(delivered) as old, ZipFile(rebuilt) as new:
        assert old.namelist() == new.namelist()
        for name in UNTOUCHED:
            assert old.read(name) == new.read(name), name
    before, after = load_workbook(delivered, rich_text=True), load_workbook(rebuilt, rich_text=True)
    for old_sheet, new_sheet in zip(before, after, strict=True):
        for row in old_sheet:
            for cell in row:
                updated = new_sheet[cell.coordinate]
                assert cell.style_id == updated.style_id
                assert cell.value == updated.value


def test_delivered_criteria_and_scoring_include_every_system_evidence() -> None:
    book = load_workbook(ROOT / "docs" / "assessment-result-template.xlsx")
    sheet = book[SOURCE_SHEET]
    rows = {row[1].value: row for row in sheet if "-SY-" in str(row[1].value)}
    assert len(rows) == 31
    for code, config in load_criteria()["items"].items():
        assert [rows[code][i].value for i in range(6, 11)] == list(config["levels"].values())
    formulas = [cell.value for row in book.worksheets[4].iter_rows(min_row=64, max_row=69) for cell in row if cell.data_type == "f"]
    for row in rows.values():
        assert sum(f"'{SOURCE_SHEET}'!M{row[1].row}" in formula for formula in formulas) == 1
    assert str(sheet.data_validations.dataValidation[0].sqref) == "M5:M89"
    assert "N/A" in sheet.data_validations.dataValidation[0].formula1
    assert sorted(int(code.rsplit("-", 1)[1]) for code in rows) == list(range(1, 32))
    assert "실행 로그" in rows["OE-SY-22"][5].value
    assert "관리 ID" in rows["OE-SY-23"][5].value
    assert "조건부 접근" not in str(book.worksheets[1]["H8"].value)


def test_only_implemented_evidence_has_bold_titles_and_bullet_descriptions() -> None:
    book = load_workbook(ROOT / "docs" / "assessment-result-template.xlsx", rich_text=True)
    sheet = book[SOURCE_SHEET]
    rows = {row[1].value: row for row in sheet.iter_rows(min_row=5) if row[1].value}
    assert len(rows) == 85
    assert len(ITEM_DETAILS) == 22
    assert ITEM_DETAILS.keys() == load_criteria()["items"].keys()
    for code, row in rows.items():
        content = row[5].value
        if code not in ITEM_DETAILS:
            assert isinstance(content, str)
            assert "\n- " not in content
            continue
        assert isinstance(content, CellRichText)
        assert len(content) == 2 and all(isinstance(part, TextBlock) for part in content)
        assert content[0].text and content[0].font.b is True
        assert content[1].font.b is False
        bullets = content[1].text.splitlines()[1:]
        assert bullets and all(line.startswith("- ") for line in bullets)
        assert "\n".join(line[2:] for line in bullets) == ITEM_DETAILS[code]
        assert not any(line.endswith(("합니다.", "않습니다.", "아닙니다.")) for line in bullets)
        assert row[5].alignment.wrap_text
    summary = "\n".join(str(cell.value) for row in book.worksheets[1] for cell in row)
    assert not any(detail in summary for detail in ITEM_DETAILS.values())


def test_legacy_audit_score_and_notes_follow_the_audit_not_the_removed_risk_item(
    source: Path, tmp_path: Path,
) -> None:
    book = load_workbook(source)
    sheet = book[SOURCE_SHEET]
    scored, output = tmp_path / "scored.xlsx", tmp_path / "updated.xlsx"
    risk_title = next(row[5].value for row in sheet if row[1].value == "OE-SY-15")
    with ZipFile(source) as archive, ZipFile(scored, "w") as out:
        raw = archive.read(SHEET_CRITERIA)
        root = ET.fromstring(raw)
        for row in sheet:
            if row[1].value not in ("OE-SY-15", "OE-SY-16"):
                continue
            number = row[1].row
            xml_row = root.find(f"{Q}sheetData/{Q}row[@r='{number}']")
            score, note = (5, "retired risk") if row[1].value == "OE-SY-15" else (2, "audit evidence")
            for column, value in (("M", score), ("N", note)):
                ref = f"{column}{number}"
                old = xml_row.find(f"{Q}c[@r='{ref}']")
                style = old.get("s", "0") if old is not None else "0"
                if old is not None:
                    xml_row.remove(old)
                if column == "M":
                    cell = ET.SubElement(xml_row, f"{Q}c", {"r": ref, "s": style})
                    ET.SubElement(cell, f"{Q}v").text = str(value)
                else:
                    xml_row.append(text_cell(ref, style, value))
        for entry in archive.infolist():
            out.writestr(entry, xml_bytes(root, raw) if entry.filename == SHEET_CRITERIA else archive.read(entry.filename))
    merge_assessment(scored, output)
    sheet = load_workbook(output)[SOURCE_SHEET]
    audit = [row for row in sheet if row[1].value == "OE-SY-22"]
    assert len(audit) == 1
    assert (audit[0][12].value, audit[0][13].value) == (2, "audit evidence")
    assert not any(row[5].value == risk_title for row in sheet)
