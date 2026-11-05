from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from wasm_agent.cli import main
from wasm_agent.models import (
    AgentEvidence,
    Collection,
    CostRecord,
    EvaluationRun,
    Finding,
    Issue,
    LogSetting,
)
from wasm_agent.report import (
    digest,
    json_bytes,
    latest_raw,
    load_result,
    raw_name,
    report_name,
    write_reports,
)
from wasm_agent.report_excel import write_workbook

ROOT = Path(__file__).parents[1]
SHEETS = [
    "읽는법", "진단 체크리스트", "추가 제안 현황", "Agent Raw 데이터", "제안 Raw 데이터", "평가 Raw 데이터",
    "모델배포 Raw 데이터",
    "비용 Raw 데이터", "로그 Raw 데이터", "보안 Raw 데이터", "보안점수 Raw 데이터", "정책할당 Raw 데이터",
    "예산 Raw 데이터", "Blueprint Raw 데이터", "AgentID Raw 데이터", "조건부접근 Raw 데이터",
    "위험Agent Raw 데이터", "수집이슈 Raw 데이터",
    "필드누락사유", "증거참조", "증거 첨부 상태", "수집 메타데이터",
]
SECRETS = (
    "secret-value", "nested-secret", "facts-secret", "private-person", "private-sponsor",
    "private-owner", "someone@example.invalid", "do-not-export", "api-key-in-evidence",
)
NO_AZURE = patch("wasm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("no Azure calls"))


def sample() -> Collection:
    when = datetime(2026, 11, 3, tzinfo=UTC)
    return Collection(
        collected_at=when, subscriptions=["000123"],
        agents=[AgentEvidence(
            collected_at=when, platform="manual", agent_id="000001", agent_name="테스트 Agent",
            subscription_id="000123", detection_confidence="manual",
            owner="private-person", sponsor="private-sponsor", cost_30d=0, guardrail_applied=False,
            tags={"secret": "secret-value", "access_token": "nested-secret",
                  "contact": "someone@example.invalid"},
            evidence_refs=[r"C:\evidence\20261103\raw.json"],
        )],
        evaluations=[EvaluationRun(
            subscription_id="000123", project_id="000456", run_id="000789", status="failed",
            passed_items=0, failed_items=3, errored_items=2, total_items=5,
        )],
        costs=[CostRecord(subscription_id="000123", resource_id="000456", amount=0, currency="USD")],
        logs=[LogSetting(subscription_id="000123", resource_id="000456", enabled=False, retention_days=0)],
        issues=[Issue(collector=name, target="000123", reason="permission_denied", detail="조회 권한 없음")
                for name in ("cost", "logs")],
        facts={"api_key": "facts-secret", "nested": {"owner": "private-owner"}},
    )


def finding(**changes: object) -> Finding:
    values = {"se_code": "BI-SY-08", "scope": "partial", "metric_value": 0, "level": "N/A",
              "reason": "permission_denied", "rationale": "근거가 부족합니다.",
              "next_step": "조회 권한을 확인하세요.", **changes}
    return Finding.model_validate(values)


def prepared(tmp_path: Path, mode: str = "live") -> tuple[Collection, Path, Path, Path]:
    """Write a report whose evidence reference points at a real file below the evidence root."""
    output = tmp_path / "output"
    root = tmp_path / "evidence" / "run"
    root.mkdir(parents=True)
    source = root / "response.json"
    source.write_text(json.dumps({
        "api_key": "api-key-in-evidence", "value": 2, "email": "someone@example.invalid",
        "response": {"status": "completed", "value": None},
    }), encoding="utf-8")
    data = sample()
    data.agents[0].evidence_refs = [str(source.resolve())]
    data.facts["evidence_directory"] = str(root)
    rows = [finding(evidence_refs=[str(source.resolve())])]
    workbook = write_reports(data, rows, output, mode)
    return data, output, source, workbook


def record(sheet: Worksheet, row: int = 2) -> dict:
    return {sheet.cell(1, col).value: sheet.cell(row, col) for col in range(1, sheet.max_column + 1)}


def records(sheet: Worksheet) -> list[dict]:
    return [record(sheet, row) for row in range(2, sheet.max_row + 1)]


def xml_text(path: Path) -> str:
    with ZipFile(path) as archive:
        return "".join(archive.read(name).decode() for name in archive.namelist() if name.endswith(".xml"))


def all_cells(book):
    return [cell for sheet in book for row in sheet.iter_rows() for cell in row]


# --- CLI and raw_data.json ---

def test_fixture_cli_is_offline_and_writes_only_workbook_and_raw_data(tmp_path: Path) -> None:
    with NO_AZURE:
        assert main([
            "collect", "--config", str(ROOT / "config" / "config.yaml"),
            "--fixture", str(ROOT / "tests" / "fixtures" / "three_subscriptions.json"),
            "--output-dir", str(tmp_path),
        ]) == 0
    names = sorted(path.name for path in tmp_path.iterdir())
    assert len(names) == 2
    assert re.fullmatch(r"raw-data-\d{8}T\d{6}Z\.json", next(n for n in names if n.startswith("raw-data-")))
    assert re.fullmatch(r"report-\d{8}T\d{6}Z\.xlsx", next(n for n in names if n.startswith("report-")))
    result = load_result(tmp_path)
    assert result["mode"] == "fixture"
    agents = result["collection"]["agents"]
    assert len(agents) == 3 and len(result["findings"]) == 6
    assert {
        "collected_at", "tenant_id", "subscription_id", "resource_group", "platform",
        "agent_id", "agent_name", "resource_id", "hosting_type", "owner", "sponsor",
        "tags", "model", "tools", "created_at", "last_used_at", "cost_30d", "usage_30d",
        "evaluated_before_deploy", "guardrail_applied", "detection_confidence", "evidence_refs",
        "se_codes", "field_status",
    } <= set(agents[0])


def test_raw_data_keeps_machine_contract_and_manifest_matches_files(tmp_path: Path) -> None:
    data, output, source, workbook = prepared(tmp_path)
    before = data.model_dump(mode="json")
    assert workbook == output / report_name(data)
    assert {path.name for path in output.iterdir()} == {workbook.name, raw_name(data)}
    assert workbook.name[len("report-"):-len(".xlsx")] == raw_name(data)[len("raw-data-"):-len(".json")]
    result = load_result(output)
    assert set(result) == {
        "schema_version", "collection", "findings", "mode", "evidence", "provenance", "manifest",
    }
    row = result["findings"][0]
    assert (row["level"], row["reason"], row["scope"]) == ("N/A", "permission_denied", "partial")
    manifest = result["manifest"]
    assert manifest["credentials_included"] is False and manifest["mode"] == "live"
    payload = workbook.read_bytes()
    assert manifest["files"] == [{
        "path": workbook.name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
    }]
    rest = {key: value for key, value in result.items() if key != "manifest"}
    assert manifest["data_sha256"] == hashlib.sha256(json_bytes(rest)).hexdigest()
    assert data.model_dump(mode="json") == before and source.exists()


def test_load_result_rejects_missing_or_unsupported_files(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_result(tmp_path)
    (tmp_path / "raw-data-20261104T000000Z.json").write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
    with pytest.raises(ValueError, match="스키마"):
        load_result(tmp_path)


# --- evidence attachment and provenance ---

def test_attached_evidence_is_masked_embedded_and_referenced_by_hash(tmp_path: Path) -> None:
    data, output, source, workbook = prepared(tmp_path)
    result = load_result(output)
    identifier, payload = next(iter(result["evidence"].items()))
    assert len(result["evidence"]) == 1 and identifier == digest(payload)
    assert payload["api_key"] == "[REDACTED]" and payload["response"] == {"status": "completed", "value": None}
    assert result["collection"]["agents"][0]["evidence_refs"] == ["evidence:" + identifier]
    assert result["findings"][0]["evidence_refs"] == ["evidence:" + identifier]
    assert result["collection"]["facts"]["evidence_directory"] == "embedded:evidence"
    assert result["provenance"]["unattached_evidence"] == []
    assert result["provenance"]["references"][0]["reference"] == str(source.resolve())
    book = load_workbook(workbook)
    status = record(book["증거 첨부 상태"])
    assert (status["id"].value, status["status"].value) == (identifier, "attached")
    assert status["reference"].value == str(source.resolve())
    assert "raw-data" in status["detail"].value
    assert record(book["증거참조"])["evidence_ref"].value == "evidence:" + identifier
    values = [c.value for sheet in book if sheet.title != "증거 첨부 상태" for row in sheet.iter_rows()
              for c in row if isinstance(c.value, str)]
    assert not any(str(source) in value for value in values)


def test_unsafe_missing_or_unsupported_references_are_reported_as_unattached(tmp_path: Path) -> None:
    data, output, source, _ = prepared(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text('{"password": "never"}', encoding="utf-8")
    text = source.parent / "note.txt"
    text.write_text("{}", encoding="utf-8")
    bad = [str(outside), str(text), str(source.parent / "missing.json"), "fixture://missing",
           "../outside.json", "%2e%2e/outside.json", "//server/share/e.json", "file:///C:/s.json"]
    data.agents[0].evidence_refs.extend(bad)
    workbook = write_reports(data, [], output)
    result = load_result(output)
    missing = result["provenance"]["unattached_evidence"]
    assert {item["reference"] for item in missing} == set(bad)
    assert all(item["status"] == "not_found" and "파일 확인불가" in item["detail"] for item in missing)
    assert len(result["evidence"]) == 1 and "never" not in json.dumps(result)
    sheet = load_workbook(workbook)["증거 첨부 상태"]
    states = sorted(row["status"].value for row in records(sheet))
    assert states == ["attached"] + ["not_found"] * len(bad)
    assert all("파일 확인불가" in r["detail"].value for r in records(sheet) if r["status"].value == "not_found")


def test_symlink_evidence_is_never_embedded(tmp_path: Path) -> None:
    data, output, source, _ = prepared(tmp_path)
    link = source.parent / "alias.json"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlink permission unavailable")
    data.agents[0].evidence_refs = [str(link)]
    write_reports(data, [], tmp_path / "linked")
    result = load_result(tmp_path / "linked")
    assert result["evidence"] == {}
    assert len(result["provenance"]["unattached_evidence"]) == 1


def test_cached_evidence_is_replayed_after_source_files_are_gone(tmp_path: Path) -> None:
    data, output, source, _ = prepared(tmp_path)
    first = load_result(output)
    source.unlink()
    write_reports(data, [], output)
    again = load_result(output)
    assert again["evidence"] == first["evidence"]
    assert again["collection"]["agents"][0]["evidence_refs"] == first["collection"]["agents"][0]["evidence_refs"]
    assert again["provenance"]["unattached_evidence"] == []


def test_new_evidence_content_replaces_previous_cache(tmp_path: Path) -> None:
    data, output, source, _ = prepared(tmp_path)
    old = next(iter(load_result(output)["evidence"]))
    source.write_text('{"response": {"new": true}}', encoding="utf-8")
    write_reports(data, [], output)
    result = load_result(output)
    assert list(result["evidence"].values()) == [{"response": {"new": True}}]
    assert old not in result["evidence"]


# --- package CLI ---

def test_package_cli_rebuilds_workbook_from_raw_data_without_azure_or_evidence(tmp_path: Path) -> None:
    _, output, source, workbook = prepared(tmp_path)
    before = load_result(output)
    source.unlink()
    workbook.unlink()
    with NO_AZURE:
        assert main(["package", "--output-dir", str(output)]) == 0
    after = load_result(output)
    for key in ("collection", "findings", "evidence", "provenance", "mode"):
        assert after[key] == before[key]
    assert {path.name for path in output.iterdir()} == {workbook.name, latest_raw(output).name}
    assert re.fullmatch(r"raw-data-\d{8}T\d{6}Z\.json", latest_raw(output).name)
    assert after["manifest"]["files"][0]["sha256"] == hashlib.sha256(workbook.read_bytes()).hexdigest()
    status = record(load_workbook(workbook)["증거 첨부 상태"])
    assert status["status"].value == "attached"


def test_package_cli_rejects_mode_mismatch_and_missing_raw_data(tmp_path: Path) -> None:
    _, output, _, workbook = prepared(tmp_path, "fixture")
    payload = workbook.read_bytes()
    with NO_AZURE:
        assert main(["package", "--output-dir", str(output), "--mode", "live"]) == 1
        assert workbook.read_bytes() == payload
        assert main(["package", "--output-dir", str(tmp_path / "empty")]) == 1
        assert main(["package", "--output-dir", str(output), "--mode", "fixture"]) == 0
    assert load_result(output)["mode"] == "fixture"


# --- atomic output ---

def test_failed_replace_preserves_existing_files_and_leaves_no_pending_files(tmp_path: Path) -> None:
    data, output, _, _ = prepared(tmp_path)
    (output / "unrelated.txt").write_bytes(b"keep")
    originals = {path.name: path.read_bytes() for path in output.iterdir()}
    data.agents[0].agent_name = "new name"
    with patch("wasm_agent.report.os.replace", side_effect=OSError("locked")), pytest.raises(OSError):
        write_reports(data, [], output)
    assert {path.name: path.read_bytes() for path in output.iterdir()} == originals
    assert not [path for path in output.iterdir() if "pending" in path.name]


def test_failed_replace_on_first_write_leaves_empty_output(tmp_path: Path) -> None:
    output = tmp_path / "fresh"
    with patch("wasm_agent.report.os.replace", side_effect=OSError("locked")), pytest.raises(OSError):
        write_reports(sample(), [], output)
    assert list(output.iterdir()) == []


# --- workbook structure ---

def test_workbook_sheets_tables_borders_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    write_workbook(sample(), [finding()], path, "fixture", [])
    book = load_workbook(path)
    assert book.sheetnames == SHEETS
    for sheet in book:
        assert sheet.freeze_panes == "A2"
        assert len(sheet.tables) == 1
        # Excel repairs a file that has both a table and a sheet-level autoFilter on one range.
        assert not sheet.auto_filter.ref
        table = next(iter(sheet.tables.values()))
        columns = [column.name for column in table.tableColumns]
        headers = [sheet.cell(1, col).value for col in range(1, sheet.max_column + 1)]
        assert columns == headers and len(set(columns)) == len(columns)
        assert all(isinstance(header, str) for header in headers)
        assert table.ref.endswith(str(sheet.max_row))
        assert all(cell.font.name == "Arial" and cell.hyperlink is None for row in sheet for cell in row)
        assert all(cell.font.size == 14 for row in sheet for cell in row if cell.value is not None)
        for cell in (c for row in sheet.iter_rows() for c in row if c.value is not None):
            border = cell.border
            assert all(getattr(border, side).style == "thin" for side in ("left", "right", "top", "bottom"))
    validations = book["진단 체크리스트"].data_validations.dataValidation
    assert len(validations) == 1
    assert validations[0].formula1 == '"미검토,검토중,확인완료"'
    assert validations[0].showErrorMessage is True and "J2" in validations[0].sqref
    assert book["진단 체크리스트"]["J1"].value == "수동검토상태"
    assert book["진단 체크리스트"]["B1"].value == "진단 영역"
    assert record(book["읽는법"], 4)["설명"].value == "fixture"


def test_workbook_values_keep_types_and_checklist_labels(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    write_workbook(sample(), [finding()], path)
    book = load_workbook(path)
    agent = record(book["Agent Raw 데이터"])
    assert set(AgentEvidence.model_fields) <= agent.keys()
    assert (agent["agent_id"].value, agent["agent_id"].data_type, agent["agent_id"].number_format) == (
        "000001", "s", "@")
    assert (agent["cost_30d"].value, agent["cost_30d"].data_type) == (0, "n")
    assert (agent["guardrail_applied"].value, agent["guardrail_applied"].data_type) == (False, "b")
    assert agent["calls_90d"].value is None
    raw = json.loads(agent["원본 JSON"].value)
    assert raw["cost_30d"] == 0 and raw["calls_90d"] is None and raw["guardrail_applied"] is False
    assert raw["owner"].startswith("identity-") and raw["tags"]["secret"] == "[REDACTED]"
    logs = record(book["로그 Raw 데이터"])
    assert (logs["retention_days"].value, logs["enabled"].data_type) == (0, "b")
    evaluation = record(book["평가 Raw 데이터"])
    assert [evaluation[k].value for k in ("passed_items", "failed_items", "errored_items")] == [0, 3, 2]
    checklist = record(book["진단 체크리스트"])
    assert (checklist["판정"].value, checklist["지표"].value) == ("판정 보류", "0.00%")
    assert (checklist["원인"].value, checklist["수동검토상태"].value) == ("조회 권한 부족", "미검토")
    guide = {row[0].value: row[1].value for row in book["읽는법"].iter_rows(min_row=2)}
    assert guide["수집 실패 집계 - 조회 권한 부족"] == 2
    assert book["모델배포 Raw 데이터"]["A2"].value.startswith("수집된 데이터 없음")


def test_missing_metric_is_not_converted_to_zero_and_null_differs_from_zero(tmp_path: Path) -> None:
    data = sample()
    data.agents[0].unavailable("model", "permission_denied", "관리자가 조회 역할을 확인해야 합니다.")
    data.evaluations[0].failed_items = None
    path = tmp_path / "null.xlsx"
    write_workbook(data, [finding(se_code="DS-SY-06", metric_value=None)], path)
    book = load_workbook(path)
    assert record(book["진단 체크리스트"])["지표"].value == "확인 자료 없음 - 분모 확인 안됨"
    evaluation = record(book["평가 Raw 데이터"])
    assert evaluation["failed_items"].value is None and evaluation["passed_items"].value == 0
    missing = records(book["필드누락사유"])
    model = next(row for row in missing if row["field"].value == "model")
    assert model["reason"].value == "permission_denied" and "조회 역할" in model["설명"].value
    calls = next(row for row in missing if row["field"].value == "calls_90d")
    assert calls["reason"].value == "not_found" and "원본 값이 null" in calls["설명"].value
    assert not any(row["field"].value in ("cost_30d", "guardrail_applied") for row in missing)


def test_empty_collection_has_placeholder_rows_without_fabricated_zero_values(tmp_path: Path) -> None:
    path = tmp_path / "empty.xlsx"
    write_workbook(Collection(collected_at=datetime(2026, 11, 3, tzinfo=UTC)), [], path)
    book = load_workbook(path)
    for title in ("Agent Raw 데이터", "평가 Raw 데이터", "수집이슈 Raw 데이터", "증거참조", "증거 첨부 상태"):
        sheet = book[title]
        assert sheet.tables and "수집된 데이터 없음" in sheet["A2"].value
        assert all(cell.value != 0 for row in sheet.iter_rows(min_row=2) for cell in row)


# --- zip level safety, masking and limits ---

@pytest.mark.parametrize("text", [
    '=HYPERLINK("https://example.invalid","click")', "+SUM(1,2)", "-1+2", "@SUM(1,2)",
])
def test_user_strings_never_become_formulas_or_external_links(tmp_path: Path, text: str) -> None:
    data = sample()
    data.agents[0].agent_name = data.agents[0].agent_id = text
    data.agents[0].evidence_refs = [text]
    data.costs[0].amount = -12.5
    path = tmp_path / "book.xlsx"
    write_workbook(data, [finding(rationale=text, next_step=text)], path)
    book = load_workbook(path)
    agent = record(book["Agent Raw 데이터"])
    assert agent["agent_name"].value == text and agent["agent_name"].data_type == "s"
    assert record(book["진단 체크리스트"])["근거"].value == text
    assert record(book["증거참조"])["evidence_ref"].value == text
    amount = record(book["비용 Raw 데이터"])["amount"]
    assert amount.value == -12.5 and amount.data_type == "n"
    assert all(cell.data_type != "f" and cell.hyperlink is None for cell in all_cells(book))
    with ZipFile(path) as archive:
        names = archive.namelist()
        assert not any("externalLink" in name or "vbaProject" in name for name in names)
        sheets = [archive.read(name).decode() for name in names if name.startswith("xl/worksheets/sheet")]
    assert len(sheets) == len(SHEETS) and not any(re.search(r"<f[\s>/]", xml) for xml in sheets)


def test_secrets_tokens_emails_and_owners_never_reach_any_output_file(tmp_path: Path) -> None:
    _, output, _, workbook = prepared(tmp_path)
    raw = latest_raw(output).read_text(encoding="utf-8")
    xml = xml_text(workbook)
    for secret in SECRETS:
        assert secret not in raw and secret not in xml
    assert "[REDACTED]" in raw and "identity-" in raw


def test_oversized_strings_fail_explicitly_without_creating_output(tmp_path: Path) -> None:
    data = sample()
    data.agents[0].agent_name = "가" * 32768
    with pytest.raises(ValueError, match="Excel 셀 길이 오류.*32768"):
        write_workbook(data, [], tmp_path / "too-long.xlsx")
    assert not (tmp_path / "too-long.xlsx").exists()
    with pytest.raises(ValueError, match="Excel 셀 길이 오류"):
        write_reports(data, [], tmp_path / "output")
    assert not list((tmp_path / "output").glob("*.xlsx")) and not list((tmp_path / "output").glob("raw-data-*.json"))
