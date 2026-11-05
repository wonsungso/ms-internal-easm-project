from __future__ import annotations

import hashlib
import os
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook

from scripts.merge_assessment import ROOT, SOURCE_SHEET, merge_assessment, xml_bytes
from scripts.proposal_levels import LEVELS
from wasm_agent.proposals import DOMAINS, TITLES

UNTOUCHED = (
    "xl/worksheets/sheet1.xml", "xl/worksheets/sheet3.xml", "xl/worksheets/sheet5.xml",
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
    assert merge_assessment(source, output)["merged_proposals"] == 13
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    with ZipFile(source) as old, ZipFile(output) as new:
        assert old.namelist() == new.namelist()
        for name in UNTOUCHED:
            assert old.read(name) == new.read(name), name
    original = load_workbook(source)[SOURCE_SHEET]
    merged_book = load_workbook(output)
    assert merged_book.sheetnames == load_workbook(source).sheetnames
    merged = merged_book[SOURCE_SHEET]
    assert merged.max_row == original.max_row + 13
    original_rows = [
        [cell.value for cell in row] for row in original.iter_rows(min_row=1)
    ]
    kept = [
        [cell.value for cell in row] for row in merged.iter_rows(min_row=1)
        if str(row[1].value) not in DOMAINS
    ]
    assert kept == original_rows
    seen = {}
    for row in merged.iter_rows(min_row=5):
        code = row[1].value
        if code in DOMAINS:
            seen[code] = row
            assert row[2].value == DOMAINS[code][0]
            assert row[4].value == "System Evidence" and TITLES[code] in row[5].value
            assert [row[col].value for col in range(6, 11)] == list(LEVELS[code][:5])
            assert row[11].value == LEVELS[code][5]
            assert row[13].value == "초안 - 점수 산정 제외"
            assert all(len(text) <= 70 and "\n" not in text for text in LEVELS[code])
    assert seen.keys() == DOMAINS.keys()
    covered = set()
    for token in str(merged.data_validations.dataValidation[0].sqref).split():
        start, _, end = token.partition(":")
        covered.update(range(int(start[1:]), int((end or start)[1:]) + 1))
    for row in seen.values():
        assert row[1].row not in covered
    assert {r for r in range(5, merged.max_row + 1)} - covered == {row[1].row for row in seen.values()}
    sheet5 = merged_book.worksheets[4]
    assert [c.value for r in sheet5.iter_rows() for c in r if str(c.value).startswith("=")] == [
        c.value for r in load_workbook(source).worksheets[4].iter_rows() for c in r
        if str(c.value).startswith("=")
    ]


def test_delivered_merged_workbook_matches_current_source(source: Path, tmp_path: Path) -> None:
    delivered = ROOT / "docs" / "assessment-template.xlsx"
    rebuilt = tmp_path / "rebuilt.xlsx"
    merge_assessment(source, rebuilt)
    with ZipFile(delivered) as old, ZipFile(rebuilt) as new:
        assert old.namelist() == new.namelist()
        assert all(old.read(name) == new.read(name) for name in old.namelist())
