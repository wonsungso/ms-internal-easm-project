from __future__ import annotations

import json
from copy import copy
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook

from wasm_agent.models import (
    AgentEvidence,
    Collection,
    CostRecord,
    EvaluationRun,
    Finding,
    Issue,
    LogSetting,
)
from wasm_agent.reporting.reports import write_reports
from wasm_agent.reporting.workbook import portable_workbook, write_workbook


def snapshot() -> Collection:
    return Collection(
        collected_at=datetime(2026, 11, 3, tzinfo=UTC),
        subscriptions=["000123"],
        agents=[AgentEvidence(
            collected_at=datetime(2026, 11, 3, tzinfo=UTC),
            platform="manual", agent_id="000001", agent_name="테스트 Agent",
            subscription_id="000123", detection_confidence="manual",
            owner="private-person", sponsor="private-sponsor",
            cost_30d=0, guardrail_applied=False,
            tags={"secret": "secret-value", "access_token": "nested-secret"},
            evidence_refs=[r"C:\evidence\20261103\raw.json"],
        )],
        evaluations=[EvaluationRun(
            subscription_id="000123", project_id="000456", run_id="000789",
            status="failed", passed_items=0, failed_items=3, errored_items=2, total_items=5,
        )],
        costs=[CostRecord(
            subscription_id="000123", resource_id="000456", amount=0, currency="USD",
        )],
        logs=[LogSetting(
            subscription_id="000123", resource_id="000456", enabled=False, retention_days=0,
        )],
        issues=[
            Issue(collector="cost", target="000123", reason="permission_denied",
                  detail="조회 권한 없음"),
            Issue(collector="logs", target="000123", reason="permission_denied",
                  detail="조회 권한 없음"),
        ],
        facts={"api_key": "facts-secret", "nested": {"owner": "private-owner"}},
    )


def record(sheet, row: int = 2) -> dict:
    return {
        sheet.cell(1, column).value: sheet.cell(row, column)
        for column in range(1, sheet.max_column + 1)
    }


def test_snapshot_saved_reloaded_tables_types_and_checklist(tmp_path: Path) -> None:
    data = snapshot()
    before = data.model_dump(mode="json")
    finding = Finding(
        se_code="BI-SY-08", scope="partial", metric_value=0, level="N/A",
        reason="permission_denied", rationale="근거가 부족합니다.",
        next_step="조회 권한을 확인하세요.", evidence_refs=[r"C:\evidence\finding.json"],
    )
    write_reports(data, [finding], tmp_path, "fixture")
    path = tmp_path / "report.xlsx"
    book = load_workbook(path)
    assert {
        "읽는법", "진단 체크리스트", "Agent 원시데이터", "평가 원시데이터",
        "모델배포 원시데이터", "비용 원시데이터", "로그 원시데이터",
        "보안 원시데이터", "수집이슈 원시데이터", "필드누락사유", "증거참조",
        "수집 메타데이터",
    } == set(book.sheetnames)
    for sheet in book:
        assert sheet.freeze_panes == "A2"
        assert len(sheet.tables) == 1
        assert sheet.auto_filter.ref
        assert next(iter(sheet.tables.values())).autoFilter.ref
        assert all(cell.font.name == "Arial" for row in sheet for cell in row)
        assert all(cell.data_type != "f" and cell.hyperlink is None for row in sheet for cell in row)
    agent = record(book["Agent 원시데이터"])
    assert set(AgentEvidence.model_fields) <= agent.keys()
    assert agent["agent_id"].value == "000001"
    assert agent["agent_id"].data_type == "s"
    assert agent["agent_id"].number_format == "@"
    assert agent["cost_30d"].value == 0
    assert agent["cost_30d"].data_type == "n"
    assert agent["guardrail_applied"].value is False
    assert agent["guardrail_applied"].data_type == "b"
    assert agent["calls_90d"].value is None
    raw = json.loads(agent["원본 JSON"].value)
    assert raw["cost_30d"] == 0
    assert raw["calls_90d"] is None
    assert raw["guardrail_applied"] is False
    assert raw["owner"].startswith("identity-")
    assert raw["tags"]["secret"] == "[REDACTED]"
    assert record(book["로그 원시데이터"])["retention_days"].value == 0
    assert record(book["로그 원시데이터"])["enabled"].data_type == "b"
    evaluation = record(book["평가 원시데이터"])
    assert evaluation["failed_items"].value == 3
    assert evaluation["errored_items"].value == 2
    assert evaluation["passed_items"].value == 0
    checklist = record(book["진단 체크리스트"])
    assert checklist["판정"].value == "판정 보류"
    assert checklist["지표"].value == "0.00%"
    assert checklist["원인"].value == "조회 권한 부족"
    assert checklist["수동검토상태"].value == "미검토"
    validations = book["진단 체크리스트"].data_validations.dataValidation
    assert len(validations) == 1
    assert validations[0].formula1 == '"미검토,검토중,확인완료"'
    assert validations[0].showErrorMessage is True
    assert "I2" in validations[0].sqref
    missing = [record(book["필드누락사유"], row)
               for row in range(2, book["필드누락사유"].max_row + 1)]
    assert any(row["field"].value == "calls_90d" and
               "원본 값이 null" in row["설명"].value for row in missing)
    assert book["모델배포 원시데이터"]["A2"].value.startswith("수집된 데이터 없음")
    guide = {row[0].value: row[1].value for row in book["읽는법"].iter_rows(min_row=2)}
    assert guide["수집 실패 집계 - 조회 권한 부족"] == 2
    assert record(book["증거참조"])["evidence_ref"].value == r"C:\evidence\20261103\raw.json"
    with ZipFile(path) as archive:
        assert not any("externalLink" in name or "vbaProject" in name for name in archive.namelist())
        xml = "".join(archive.read(name).decode() for name in archive.namelist()
                      if name.endswith(".xml"))
        for secret in ("secret-value", "nested-secret", "facts-secret", "private-person",
                       "private-sponsor", "private-owner"):
            assert secret not in xml
    assert data.model_dump(mode="json") == before


@pytest.mark.parametrize("text", [
    '=HYPERLINK("https://example.invalid","click")', "+SUM(1,2)", "-1+2", "@SUM(1,2)",
])
def test_user_strings_never_become_formulas(tmp_path: Path, text: str) -> None:
    data = snapshot()
    data.agents[0].agent_name = text
    data.agents[0].agent_id = text
    data.agents[0].evidence_refs = [text]
    data.costs[0].amount = -12.5
    finding = Finding(
        se_code="DS-SY-06", scope="partial", level="N/A", rationale=text, next_step=text,
    )
    path = tmp_path / "snapshot.xlsx"
    write_workbook(data, [finding], path)
    book = load_workbook(path, data_only=False)
    assert record(book["Agent 원시데이터"])["agent_name"].value == text
    assert record(book["Agent 원시데이터"])["agent_name"].data_type == "s"
    assert record(book["진단 체크리스트"])["근거"].value == text
    assert record(book["증거참조"])["evidence_ref"].value == text
    amount = record(book["비용 원시데이터"])["amount"]
    assert amount.value == -12.5 and amount.data_type == "n"
    assert all(cell.data_type != "f" for sheet in book for row in sheet for cell in row)


def test_null_counts_and_explicit_field_status_remain_distinct(tmp_path: Path) -> None:
    data = snapshot()
    data.agents[0].unavailable("model", "permission_denied", "관리자가 조회 역할을 확인해야 합니다.")
    data.evaluations[0].failed_items = None
    path = tmp_path / "null.xlsx"
    write_workbook(data, [], path)
    book = load_workbook(path)
    assert record(book["평가 원시데이터"])["failed_items"].value is None
    assert record(book["평가 원시데이터"])["passed_items"].value == 0
    rows = [record(book["필드누락사유"], row)
            for row in range(2, book["필드누락사유"].max_row + 1)]
    model = next(row for row in rows if row["field"].value == "model")
    assert model["reason"].value == "permission_denied"
    assert "조회 역할" in model["설명"].value


def test_oversized_strings_fail_explicitly_without_silent_truncation(tmp_path: Path) -> None:
    data = snapshot()
    data.agents[0].agent_name = "가" * 32768
    with pytest.raises(ValueError, match="Excel 셀 길이 오류.*32768"):
        write_workbook(data, [], tmp_path / "too-long.xlsx")
    assert not (tmp_path / "too-long.xlsx").exists()


def test_empty_collection_has_tables_without_fabricated_zero_values(tmp_path: Path) -> None:
    data = Collection(collected_at=datetime(2026, 11, 3, tzinfo=UTC))
    path = tmp_path / "empty.xlsx"
    write_workbook(data, [], path)
    book = load_workbook(path)
    for title in ("Agent 원시데이터", "평가 원시데이터", "수집이슈 원시데이터", "증거참조"):
        sheet = book[title]
        assert sheet.tables
        assert "수집된 데이터 없음" in sheet["A2"].value
        assert all(cell.value != 0 for row in sheet.iter_rows(min_row=2) for cell in row)


def test_portable_workbook_rewrites_paths_and_preserves_snapshot(tmp_path: Path) -> None:
    data = snapshot()
    source = r"C:\evidence\20261103\raw-abcdef.json"
    target = "evidence/20261103/raw-abcdef.json"
    shorter = r"C:\evidence\20261103"
    data.agents[0].evidence_refs = [source]
    data.facts["references"] = [source]
    data.agents[0].agent_name = "=SUM(1,2)"
    finding = Finding(
        se_code="BI-SY-08", scope="partial", level="N/A",
        rationale=f"근거: {source}", evidence_refs=[source],
    )
    path = tmp_path / "report.xlsx"
    write_workbook(data, [finding], path)
    payload = path.read_bytes()
    result = portable_workbook(payload, {shorter: "wrong-prefix", source: target})
    book = load_workbook(BytesIO(result))
    original = load_workbook(BytesIO(payload))
    assert book.sheetnames == original.sheetnames
    agent = record(book["Agent 원시데이터"])
    assert json.loads(agent["evidence_refs"].value) == [target]
    raw = json.loads(agent["원본 JSON"].value)
    assert raw["evidence_refs"] == [target]
    assert raw["tags"]["secret"] == "[REDACTED]"
    assert raw["owner"].startswith("identity-")
    assert agent["agent_name"].value == "=SUM(1,2)"
    assert agent["agent_name"].data_type == "s"
    assert agent["guardrail_applied"].value is False
    assert agent["guardrail_applied"].data_type == "b"
    assert agent["cost_30d"].value == 0
    assert agent["cost_30d"].data_type == "n"
    assert agent["agent_id"].value == "000001"
    assert agent["agent_id"].number_format == "@"
    assert record(book["증거참조"])["evidence_ref"].value == target
    assert record(book["진단 체크리스트"])["근거"].value == f"근거: {target}"
    for sheet in book:
        old = original[sheet.title]
        assert sheet.freeze_panes == old.freeze_panes
        assert sheet.auto_filter.ref == old.auto_filter.ref
        assert sheet.tables.keys() == old.tables.keys()
        assert sheet.data_validations == old.data_validations
        for row in sheet:
            for cell in row:
                assert copy(cell.font) == copy(old[cell.coordinate].font)
                assert copy(cell.alignment) == copy(old[cell.coordinate].alignment)
                assert cell.number_format == old[cell.coordinate].number_format
                assert cell.data_type != "f"
                assert cell.hyperlink is None
                if isinstance(cell.value, str):
                    assert source not in cell.value
                    assert json.dumps(source)[1:-1] not in cell.value
                    assert "wrong-prefix" not in cell.value
    with ZipFile(BytesIO(result)) as archive:
        assert not any("externalLink" in name or "vbaProject" in name for name in archive.namelist())
        xml = "".join(archive.read(name).decode() for name in archive.namelist()
                      if name.endswith(".xml"))
        assert "secret-value" not in xml
        assert "facts-secret" not in xml
    bundle = BytesIO()
    with ZipFile(bundle, "w") as archive:
        archive.writestr("report.xlsx", result)
        archive.writestr(target, "{}")
    with ZipFile(bundle) as archive:
        packaged = load_workbook(BytesIO(archive.read("report.xlsx")))
        packaged_ref = record(packaged["증거참조"])["evidence_ref"].value
        assert packaged_ref in archive.namelist()
    assert path.read_bytes() == payload


@pytest.mark.parametrize("target", ["=1+2", "+1", "-1", "@test"])
def test_portable_workbook_neutralizes_replacement_formula_strings(
    tmp_path: Path, target: str,
) -> None:
    data = snapshot()
    source = data.agents[0].evidence_refs[0]
    path = tmp_path / "report.xlsx"
    write_workbook(data, [], path)
    result = portable_workbook(path.read_bytes(), {source: target})
    book = load_workbook(BytesIO(result))
    ref = record(book["증거참조"])["evidence_ref"]
    assert ref.value == target
    assert ref.data_type == "s"
    assert json.loads(record(book["Agent 원시데이터"])["evidence_refs"].value) == [target]
    assert all(cell.data_type != "f" for sheet in book for row in sheet for cell in row)


def test_portable_workbook_replacements_are_simultaneous_and_length_checked(tmp_path: Path) -> None:
    data = snapshot()
    source = data.agents[0].evidence_refs[0]
    target = "evidence/20261103/raw-abcd.json"
    path = tmp_path / "report.xlsx"
    write_workbook(data, [], path)
    result = portable_workbook(path.read_bytes(), {
        source: target, target: "must-not-cascade", "": "ignored",
    })
    book = load_workbook(BytesIO(result))
    assert record(book["증거참조"])["evidence_ref"].value == target
    with pytest.raises(ValueError, match="Excel 셀 길이 오류"):
        portable_workbook(path.read_bytes(), {source: "가" * 32768})
