from __future__ import annotations

import hashlib
import os
import shutil
from copy import copy
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from scripts.update_assessment import (
    CHECKED,
    PROPOSAL_SHEET,
    ROOT,
    SOURCE_SHEET,
    STATE,
    SY_SHEET,
    build_assessment,
    read_contracts,
    xml_bytes,
)
from wasm_agent.models import CRITERIA_FILE


@pytest.fixture
def workspace() -> Path:
    directory = ROOT / f".assessment-test-{uuid4().hex}"
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


@pytest.fixture
def source(workspace: Path) -> Path:
    book = Workbook()
    book.active.title = "모델 구조"
    book.create_sheet("질문")
    book.create_sheet("성숙도")
    sheet = book.create_sheet(SOURCE_SHEET)
    book.create_sheet("점수")
    sheet["F4"] = "질문"
    sheet["F4"].font = Font(name="맑은 고딕", bold=True)
    sheet["F4"].fill = PatternFill("solid", fgColor="D9D9D9")
    contracts, _ = read_contracts(ROOT / "docs" / "api-notes.md", CRITERIA_FILE)
    for row, code in enumerate(contracts, 14):
        for col, value in enumerate(
            [code, "영역", "매핑", "System Evidence", f"원문 {code}",
             "1단계", "2단계", "3단계", "4단계", "5단계", "원문 증적"], 2
        ):
            sheet.cell(row, col, value)
    sheet["F14"].font = Font(name="맑은 고딕", size=11)
    sheet["F14"].fill = PatternFill("solid", fgColor="EAF3FB")
    book.worksheets[0]["A1"] = "=1+1"
    book.worksheets[0].merge_cells("B2:C2")
    path = workspace / "source.xlsx"
    book.save(path)
    return path


def assert_preserved(source: Path, output: Path) -> None:
    original, result = load_workbook(source), load_workbook(output)
    assert result.sheetnames[:5] == original.sheetnames
    with ZipFile(source) as old, ZipFile(output) as new:
        modified = {
            "xl/workbook.xml", "xl/_rels/workbook.xml.rels",
            "xl/styles.xml", "[Content_Types].xml",
        }
        for name in set(old.namelist()) - modified:
            assert new.read(name) == old.read(name), name
    for sheet in original:
        saved = result[sheet.title]
        assert list(saved.merged_cells.ranges) == list(sheet.merged_cells.ranges)
        assert (saved.max_row, saved.max_column) == (sheet.max_row, sheet.max_column)
        for row in sheet:
            for cell in row:
                other = saved[cell.coordinate]
                assert other.value == cell.value
                assert other.data_type == cell.data_type
                for attr in ("font", "fill", "border", "alignment", "protection", "number_format"):
                    assert copy(getattr(other, attr)) == copy(getattr(cell, attr))
    for data_only in (False, True):
        book = load_workbook(output, data_only=data_only)
        assert not [(sh.title, c.coordinate) for sh in book for row in sh for c in row
                    if c.data_type == "e"]


def assert_deliverable(path: Path) -> None:
    book = load_workbook(path)
    contracts, _ = read_contracts(ROOT / "docs" / "api-notes.md", CRITERIA_FILE)
    assert len(book.sheetnames) == 7
    sy = book[SY_SHEET]
    assert sy.max_row == 24
    assert len({sy.cell(r, 1).value for r in range(5, 25)}) == 20
    scope_counts = {}
    for row in sy.iter_rows(min_row=5):
        code = row[0].value
        original_row = row[12].value
        original = book[SOURCE_SHEET]
        assert [c.value for c in row[:11]] == [
            original.cell(original_row, col).value for col in range(2, 13)
        ]
        assert row[11].value == SOURCE_SHEET
        assert row[11].hyperlink.target == f"#'{SOURCE_SHEET}'!B{original_row}"
        scope = row[14].value
        scope_counts[scope] = scope_counts.get(scope, 0) + 1
        assert row[13].value == contracts[code]["유형"]
        if scope == "out_of_scope":
            assert row[17].value == "미구현 - 범위 제외"
            assert row[18].value == "null - 범위 제외, 대체 점수 없음"
        else:
            assert code in row[17].value
    assert scope_counts == {"in_scope": 6, "partial": 5, "out_of_scope": 9}
    proposal = book[PROPOSAL_SHEET]
    assert proposal.max_row == 17
    assert len({proposal.cell(r, 1).value for r in range(5, 18)}) == 13
    codes = {sy.cell(r, 1).value for r in range(5, 25)}
    for row in proposal.iter_rows(min_row=5):
        assert row[0].value.startswith("AZ-SY-P")
        assert row[1].value == STATE
        assert set(row[3].value.split(", ")) <= codes
        assert all(row[col].value for col in (2, 4, 5, 6, 8, 12))
        assert row[9].value.date().isoformat() == CHECKED
        for col in (7, 10):
            if row[col].value:
                assert row[col].value.startswith("https://learn.microsoft.com/en-us/")
                assert row[col].hyperlink.target == row[col].value
    for sheet in (sy, proposal):
        assert len(sheet.tables) == 1
        assert sheet.freeze_panes == "B5"
        assert sheet.auto_filter.ref is None
        table = next(iter(sheet.tables.values()))
        assert table.autoFilter.ref == table.ref
        assert len(sheet.merged_cells.ranges) == 2
        assert all(c.alignment.wrap_text for row in sheet for c in row if c.value is not None)
        assert not [c for row in sheet for c in row if c.data_type in {"f", "e"}]


def test_round_trip_preserves_original_and_adds_questions(source: Path, workspace: Path) -> None:
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output = workspace / "assessment.xlsx"
    counts = build_assessment(source, output)
    assert counts == {
        "original_sheets": 5, "sy_questions": 20, "proposals": 13, "source_sha256": before,
    }
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert_preserved(source, output)
    assert_deliverable(output)


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


def test_rejects_source_overwrite(source: Path) -> None:
    before = source.read_bytes()
    with pytest.raises(ValueError, match="덮어쓰기"):
        build_assessment(source, source.parent / "." / source.name)
    assert source.read_bytes() == before


def test_added_colors_precede_office_style_extensions(source: Path, workspace: Path) -> None:
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with ZipFile(source) as original:
        contents = {name: original.read(name) for name in original.namelist()}
    styles = ET.fromstring(contents["xl/styles.xml"])
    colors = styles.find(f"{{{namespace}}}colors")
    assert colors is not None
    styles.remove(colors)
    ET.SubElement(styles, f"{{{namespace}}}extLst")
    contents["xl/styles.xml"] = ET.tostring(styles)
    with ZipFile(source, "w") as modified:
        for name, data in contents.items():
            modified.writestr(name, data)
    output = workspace / "assessment.xlsx"
    build_assessment(source, output)
    with ZipFile(output) as result:
        groups = [node.tag.rsplit("}", 1)[-1] for node in ET.fromstring(result.read("xl/styles.xml"))]
    assert groups[-2:] == ["colors", "extLst"]


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown", "incomplete"])
def test_rejects_invalid_sy(source: Path, workspace: Path, change: str) -> None:
    book = load_workbook(source)
    sheet = book[SOURCE_SHEET]
    if change == "missing":
        sheet["B14"] = None
    elif change == "duplicate":
        sheet["B15"] = sheet["B14"].value
    elif change == "unknown":
        sheet["B14"] = "XX-SY-99"
    else:
        sheet["G14"] = None
    book.save(source)
    output = workspace / "invalid.xlsx"
    with pytest.raises(ValueError):
        build_assessment(source, output)
    assert not output.exists()


def test_invalid_source_and_shape(workspace: Path) -> None:
    output = workspace / "invalid.xlsx"
    with pytest.raises(ValueError, match="유효한"):
        build_assessment(workspace / "missing.xlsx", output)
    invalid = workspace / "empty.xlsx"
    Workbook().save(invalid)
    with pytest.raises(ValueError, match="5개"):
        build_assessment(invalid, output)
    invalid.write_bytes(b"not an XLSX")
    with pytest.raises(ValueError, match="XLSX 구조"):
        build_assessment(invalid, output)
    assert not output.exists()


def test_delivered_workbook_against_real_source() -> None:
    path = os.environ.get("ASSESSMENT_SOURCE")
    if not path:
        pytest.skip("실제 원본 검증은 ASSESSMENT_SOURCE 지정 시 실행")
    source = Path(path)
    output = ROOT / "docs" / "assessment-sy.xlsx"
    assert_preserved(source, output)
    assert_deliverable(output)
