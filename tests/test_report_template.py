from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from shutil import copyfile
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.utils import range_boundaries

from wasm_agent import report_template
from wasm_agent.models import DEFAULT_TAGS, Collection, Finding, load_criteria
from wasm_agent.proposals import evaluate_proposals
from wasm_agent.report_excel import _emphasize_evidence, _evidence_needs_expansion, write_workbook
from wasm_agent.report_template import (
    COLLECTION_METHODS,
    CRITERIA_SHEET,
    RESULT_SHEET,
    assessment_template_path,
)


@pytest.fixture
def output(tmp_path: Path) -> Path:
    path = tmp_path / "report.xlsx"
    findings = [
        Finding(se_code=code, scope="partial", level="L2", rationale="실제 구성 확인",
                evidence_refs=["fixture://observed"], metric_value=0.25)
        for code in ("BI-SY-11", "DS-SY-06")
    ]
    write_workbook(Collection(collected_at=datetime.now(UTC)), findings, path, "fixture")
    return path


def test_original_sheets_metadata_and_cached_formulas_are_preserved(output: Path) -> None:
    source_path = assessment_template_path()
    before, after = load_workbook(source_path), load_workbook(output)
    assert after.sheetnames[:5] == before.sheetnames
    with ZipFile(source_path) as source, ZipFile(output) as target:
        for index in range(1, 6):
            name = f"xl/worksheets/sheet{index}.xml"
            assert target.read(name) == re.sub(rb'\btabSelected="1"', b'tabSelected="0"', source.read(name))
        for name in source.namelist():
            if name.startswith("docProps/") or name in ("xl/calcChain.xml", "xl/sharedStrings.xml"):
                assert target.read(name) == source.read(name)
    cached_source, cached_output = load_workbook(source_path, data_only=True), load_workbook(output, data_only=True)
    for index in range(5):
        for row in before.worksheets[index]:
            for cell in row:
                target = after.worksheets[index][cell.coordinate]
                assert cell.value == target.value and cell._style == target._style
                assert cached_source.worksheets[index][cell.coordinate].value == cached_output.worksheets[index][
                    cell.coordinate
                ].value


def test_result_preserves_source_columns_and_inserts_collection_methods(output: Path) -> None:
    book = load_workbook(output)
    source, result = book[CRITERIA_SHEET], book[RESULT_SHEET]
    assert book.active.title == RESULT_SHEET
    assert {str(merged) for merged in result.merged_cells.ranges} == {"B2:N2", "B3:N3"}
    for index, sheet in enumerate(book, 1):
        assert sheet.title.startswith(f"{index}. ")
    for row in range(1, source.max_row + 1):
        assert result.row_dimensions[row].height == (
            45 if row in (2, 3) else 120 if result.cell(row, 7).value == "수집됨" else source.row_dimensions[row].height
        )
        for column in range(1, 7):
            old, new = source.cell(row, column), result.cell(row, column)
            code = source.cell(row, 2).value
            if row in (2, 3) and column == 2:
                assert "점검 요약" in new.value if row == 2 else "해석 주의" in new.value
            elif column == 6 and code in COLLECTION_METHODS:
                lines = new.value.splitlines()
                assert lines[1] == f"- [{COLLECTION_METHODS[code]}]"
                assert "\n".join(lines[:1] + lines[2:]) == old.value
            else:
                assert old.value == new.value
            assert old._style == new._style
            assert old.number_format == new.number_format
    for name in ("A", "B", "C", "D", "E", "F"):
        assert result.column_dimensions[name].width == source.column_dimensions[name].width
    rows = {result.cell(row, 2).value: row for row in range(5, result.max_row + 1)}
    for code in ("BI-SY-11", "DS-SY-06"):
        assert result.cell(rows[code], 9).value == f"Level 2 ({source.cell(rows[code], 8).value})"
        assert "실제 구성 확인" in result.cell(rows[code], 10).value
    assert result.cell(rows["DM-PR-01"], 7).value == "인터뷰 필요"
    assert result.cell(rows["DM-PR-01"], 9).value is None
    assert result.cell(rows["DM-SY-01"], 7).value == "수집하지 않음"
    assert result.cell(rows["DM-SY-01"], 9).value is None
    assert book.sheetnames[6:] == [
        "7. 수집결과 근거", "8. 수집 Raw 데이터", "9. 수집이슈 Raw 데이터", "10. 필드누락사유",
    ]


def test_result_preserves_bold_titles_and_regular_bullet_descriptions(output: Path) -> None:
    book = load_workbook(output, rich_text=True)
    implemented = load_criteria()["items"]
    for row in range(5, book[RESULT_SHEET].max_row + 1):
        source = book[CRITERIA_SHEET].cell(row, 6).value
        result = book[RESULT_SHEET].cell(row, 6).value
        code = book[RESULT_SHEET].cell(row, 2).value
        if code not in COLLECTION_METHODS:
            assert result == source
        else:
            lines = str(result).splitlines()
            assert lines[1] == f"- [{COLLECTION_METHODS[code]}]"
            assert "\n".join(lines[:1] + lines[2:]) == str(source)
        if code not in implemented:
            assert isinstance(result, str)
            continue
        assert isinstance(result, CellRichText)
        assert result[0].font.b is True
        assert result[1].font.b is False
        assert all(line.startswith("- ") for line in str(result).splitlines()[1:])
        assert all(not block.font.b for block in result[1:] if isinstance(block, TextBlock))


def test_collection_methods_match_all_readme_rows() -> None:
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    methods = {}
    for line in readme.splitlines():
        if re.match(r"\| \[[A-Z]{2}-SY-\d{2}\]", line):
            fields = line.split("|")
            code = re.search(r"\[([A-Z]{2}-SY-\d{2})\]", fields[1])[1]
            methods[code] = fields[4].strip()
    assert len(methods) == 31
    assert COLLECTION_METHODS == methods


@pytest.mark.parametrize(("text", "expanded"), [
    ("짧은 근거", False), ("a" * 180, False), ("a" * 181, True),
    ("가" * 90, False), ("가" * 91, True), ("첫 줄\n둘째 줄\n셋째 줄", True),
])
def test_long_evidence_uses_wrapping_and_explicit_newlines(text: str, expanded: bool) -> None:
    assert _evidence_needs_expansion(text, 90, 33.75, 10) is expanded


def test_uncollected_long_evidence_is_height120_without_changing_short_rows(tmp_path: Path) -> None:
    path = tmp_path / "long-uncollected.xlsx"
    write_workbook(Collection(collected_at=datetime.now(UTC)), [Finding(
        se_code="DS-SY-06", scope="partial", level="N/A", reason="permission_denied",
        rationale="조회 실패의 상세 근거입니다. " * 20,
    )], path)
    sheet = load_workbook(path)[RESULT_SHEET]
    rows = {sheet.cell(row, 2).value: row for row in range(5, 90)}
    row = rows["DS-SY-06"]
    assert sheet.cell(row, 7).value == "수집하지 않음"
    assert sheet.row_dimensions[row].height == 120
    source = load_workbook(assessment_template_path())[CRITERIA_SHEET]
    short = rows["DM-SY-01"]
    assert sheet.row_dimensions[short].height == source.row_dimensions[short].height


def test_unknown_result_code_fails_explicitly_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "invalid.xlsx"
    with pytest.raises(ValueError, match="템플릿에 없는 SE 코드"):
        write_workbook(Collection(collected_at=datetime.now(UTC)), [
            Finding(se_code="UNKNOWN", scope="partial", level="L2", rationale="fixture"),
        ], path)
    assert not path.exists()


def test_historical_grade_is_not_described_with_new_api_thresholds(tmp_path: Path) -> None:
    path = tmp_path / "historical.xlsx"
    data = Collection(collected_at=datetime.now(UTC), facts={
        "assessment_revision": 5, "entra_blueprints_complete": True,
    })
    finding = Finding(
        se_code="DS-SY-05", scope="in_scope", level="L2", rationale="수집 당시 평가 근거",
        next_step="수집 당시 다음 단계",
    )
    write_workbook(data, [finding], path)
    sheet = load_workbook(path)[RESULT_SHEET]
    row = next(row for row in range(5, sheet.max_row + 1) if sheet.cell(row, 2).value == "DS-SY-05")
    assert "수집 당시 기준의 등급" in sheet.cell(row, 9).value
    assert sheet.cell(row, 12).value == "수집 당시 다음 단계"
    assert finding.level == "L2"


def test_historical_terms_are_localized_without_rewriting_original_evidence(tmp_path: Path) -> None:
    finding = Finding(
        se_code="OE-SY-20", scope="in_scope", level="L3", metric_value=0.8,
        level_criterion="소유자·후원자 모두 연결 비율 80% 이상",
        rationale="소유자와 후원자가 연결됨",
    )
    path = tmp_path / "localized.xlsx"
    write_workbook(Collection(collected_at=datetime.now(UTC)), [finding], path)
    sheet = load_workbook(path)[RESULT_SHEET]
    row = next(row for row in range(5, 90) if sheet.cell(row, 2).value == "OE-SY-20")
    assert "스폰서" in sheet.cell(row, 9).value and "후원자" not in sheet.cell(row, 9).value
    assert "스폰서" in sheet.cell(row, 10).value and "후원자" not in sheet.cell(row, 10).value
    assert finding.rationale == "소유자와 후원자가 연결됨"


def test_all_findings_link_to_the_matching_detail_row_and_preserve_existing_metrics(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "three_subscriptions.json"
    data = Collection.model_validate_json(fixture.read_text(encoding="utf-8"))
    data.proposals = evaluate_proposals(data, DEFAULT_TAGS)
    findings = [
        Finding(se_code=code, scope=config["scope"], level="L2", rationale="보존할 판정 근거")
        for code, config in load_criteria()["items"].items()
    ]
    path = tmp_path / "linked.xlsx"
    write_workbook(data, findings, path)
    book = load_workbook(path, rich_text=True)
    results, details = book[RESULT_SHEET], book["7. 수집결과 근거"]
    table = next(table for table in details.tables.values() if table.ref.startswith("A3:"))
    last_detail = range_boundaries(table.ref)[3]
    detail_rows = {details.cell(row, 1).value: row for row in range(4, last_detail + 1)}
    assert len(detail_rows) == len(findings) == 22
    expected_metrics = {item.code: item.metrics for item in data.proposals}
    for code, row in detail_rows.items():
        if code in expected_metrics:
            assert json.loads(details.cell(row, 7).value) == expected_metrics[code]
    linked = 0
    for row in range(5, results.max_row + 1):
        code = results.cell(row, 2).value
        evidence = results.cell(row, 10)
        link = results.cell(row, 11)
        assert evidence.hyperlink is None
        if code not in detail_rows:
            assert link.value is None and link.hyperlink is None
            continue
        assert isinstance(evidence.value, (str, CellRichText))
        assert evidence.font.bold is False
        assert not str(evidence.value).endswith("\n수집결과")
        assert "보존할 판정 근거" in str(evidence.value)
        assert link.value == "수집결과" and link.font.u == "single"
        assert link.font.color.rgb == "FF0563C1"
        assert link.alignment.horizontal == "center"
        assert link.hyperlink.target is None and link.hyperlink.id is None
        assert link.hyperlink.location == f"'7. 수집결과 근거'!A{detail_rows[code]}"
        linked += 1
    assert linked == 22


@pytest.mark.parametrize("level", ["L1", "L2", "L3", "L4", "L5", "N/A"])
def test_result_level_display_preserves_machine_grade(tmp_path: Path, level: str) -> None:
    finding = Finding(
        se_code="DS-SY-06", scope="partial", level=level, rationale="fixture",
        next_step="L5 운영 증적을 지속 확인" if level == "L5" else "부족 증적 확인",
    )
    path = tmp_path / "levels.xlsx"
    write_workbook(Collection(
        collected_at=datetime.now(UTC), facts={"deployment_inventory_complete": True},
    ), [finding], path)
    sheet = load_workbook(path)[RESULT_SHEET]
    row = next(row for row in range(5, sheet.max_row + 1) if sheet.cell(row, 2).value == finding.se_code)
    source = load_workbook(assessment_template_path())[CRITERIA_SHEET]
    assert sheet.cell(row, 9).value == (
        "판정 보류" if level == "N/A" else f"Level {level[1:]} ({source.cell(row, 6 + int(level[1:])).value})"
    )
    assert finding.level == level
    score = sheet.cell(row, 13)
    assert score.value == (None if level == "N/A" else int(level[1:]))
    if level != "N/A":
        assert score.data_type == "n"
    rich_sheet = load_workbook(path, rich_text=True)[RESULT_SHEET]
    judgment = rich_sheet.cell(row, 9).value
    action = rich_sheet.cell(row, 12).value
    if level == "N/A":
        assert judgment == "판정 보류" and action == finding.next_step
    else:
        assert isinstance(judgment, CellRichText)
        assert [(part.text, part.font.b) for part in judgment if isinstance(part, TextBlock)] == [
            ("Level " + level[1:], True),
        ]
        if level == "L5":
            assert action is None
            assert finding.next_step == "L5 운영 증적을 지속 확인"
        else:
            next_level = int(level[1:]) + 1
            assert isinstance(action, CellRichText)
            assert str(action) == f"Level {next_level}: {source.cell(row, 6 + next_level).value}"
            assert [(part.text, part.font.b) for part in action if isinstance(part, TextBlock)] == [
                (f"Level {next_level}", True),
            ]


@pytest.mark.parametrize(("text", "bold"), [
    ("API 충족 1 / 대상 3, 비율 33.33%", ["1", "3", "33.33%"]),
    ("비용 -1,234.50, 보존 90일, 비율 0/0개", ["-1,234.50", "90", "0/0"]),
    ("westus2, DS-SY-07, L4, /subscriptions/123, 2026-11-09", []),
    ("수집 결과 없음", []),
    (" 1\n2 ", ["1", "2"]),
    ("수집 결과: 1개\n관련리소스: resource\n판정 근거: 100%",
     ["수집 결과:", "1", "관련리소스:", "판정 근거:", "100%"]),
    ("일반 설명의 수집 결과: 문구는 그대로", []),
])
def test_evidence_emphasizes_labels_and_numbers_without_changing_text(text: str, bold: list[str]) -> None:
    content = _emphasize_evidence(text)
    assert str(content) == text
    assert [
        part.text.strip() for part in content if isinstance(part, TextBlock) and part.font.b
    ] == bold
    assert not any(isinstance(part, str) and part.isspace() for part in content)


def test_evidence_labels_and_numbers_are_bold_and_cause_column_is_removed(tmp_path: Path) -> None:
    path = tmp_path / "rich.xlsx"
    data = Collection(collected_at=datetime.now(UTC), facts={"deployment_inventory_complete": True})
    write_workbook(data, [Finding(
        se_code="DS-SY-06", level="L2", scope="partial", metric_value=0,
        rationale="실제 근거: 충족 1 / 대상 3, 비율 33.33%", reason="permission_denied",
    )], path)
    sheet = load_workbook(path, rich_text=True)[RESULT_SHEET]
    row = next(row for row in range(5, sheet.max_row + 1) if sheet.cell(row, 2).value == "DS-SY-06")
    assert sheet.max_column == 14
    assert [sheet.cell(4, column).value for column in range(9, 15)] == [
        "판정", "근거", "수집결과", "다음조치", "평가 점수\n(1~5)", "검토메모",
    ]
    evidence = sheet.cell(row, 10).value
    assert isinstance(evidence, CellRichText)
    bold = [part for part in evidence if isinstance(part, TextBlock) and part.font.b]
    labels = {"수집 결과:", "관련 리소스:", "판정 근거:"}
    assert labels | {"1", "3", "33.33%"} <= {part.text for part in bold}
    assert all(part.text in labels or re.fullmatch(r"[0-9.,%/ +\-]+", part.text) for part in bold)
    assert sheet.cell(row, 10).font.bold is False
    assert "평가 범위:" not in str(evidence) and "세부 조회 상태:" not in str(evidence)
    assert "조회 권한 부족" in str(evidence)
    assert "실제 근거" in str(evidence)
    assert sheet.cell(row, 13).alignment.horizontal == "center"


def test_installed_template_location_is_supported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = assessment_template_path()
    installed = tmp_path / "prefix" / "share" / "wasm-agent" / report_template.TEMPLATE_NAME
    installed.parent.mkdir(parents=True)
    copyfile(source, installed)
    monkeypatch.setattr(report_template, "__file__", str(tmp_path / "site-packages" / "wasm_agent" / "module.py"))
    monkeypatch.setattr(report_template.sysconfig, "get_path", lambda name: str(tmp_path / "prefix"))
    assert assessment_template_path() == installed


def test_missing_template_does_not_silently_change_report_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(report_template, "__file__", str(tmp_path / "site-packages" / "wasm_agent" / "module.py"))
    monkeypatch.setattr(report_template.sysconfig, "get_path", lambda name: str(tmp_path / "prefix"))
    with pytest.raises(FileNotFoundError, match="평가 결과 템플릿"):
        assessment_template_path()
