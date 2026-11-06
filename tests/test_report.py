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
from openpyxl.utils.cell import range_boundaries
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
from wasm_agent.report_template import CRITERIA_SHEET, RESULT_SHEET

ROOT = Path(__file__).parents[1]
EXTRA_SHEETS = [
    "수집결과 근거", "수집 Raw 데이터", "수집이슈 Raw 데이터", "필드누락사유",
]
SHEETS = [
    "1. 모델 구조", "2. 질문 및 확인사항", "3. 성숙도 정의", CRITERIA_SHEET, "5. 점수 산정 방식",
    RESULT_SHEET, *[f"{index}. {title}" for index, title in enumerate(EXTRA_SHEETS, 7)],
]
TITLES = {title: f"{index}. {title}" for index, title in enumerate(EXTRA_SHEETS, 7)}
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
    values = {"se_code": "BI-SY-11", "scope": "partial", "metric_value": 0, "level": "N/A",
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
    header = 4 if sheet.title == RESULT_SHEET else 3 if sheet.title == TITLES["수집결과 근거"] else 1
    if sheet.title == RESULT_SHEET and row == 2:
        row = next(number for number in range(5, sheet.max_row + 1) if sheet.cell(number, 9).value is not None)
    elif header == 3 and row == 2:
        row = 4
    return {sheet.cell(header, col).value: sheet.cell(row, col) for col in range(1, sheet.max_column + 1)}


def records(sheet: Worksheet) -> list[dict]:
    return [record(sheet, row) for row in range(
        4 if sheet.title == TITLES["수집결과 근거"] else 2, sheet.max_row + 1,
    )]


def raw_bounds(book, title: str) -> tuple[Worksheet, tuple[int, int, int, int]]:
    sheet = book[TITLES["수집 Raw 데이터"]]
    label = "구성 관측" if title == "제안 Raw 데이터" else title.removesuffix(" Raw 데이터")
    heading = next(cell.row for cell in sheet["A"] if str(cell.value).startswith(label + " - "))
    table = next(table for table in sheet.tables.values() if range_boundaries(table.ref)[1] == heading + 1)
    return sheet, range_boundaries(table.ref)


def raw_record(book, title: str) -> dict:
    sheet, (_, header, last_column, _) = raw_bounds(book, title)
    return {sheet.cell(header, column).value: sheet.cell(header + 1, column)
            for column in range(1, last_column + 1)}


def xml_text(path: Path) -> str:
    with ZipFile(path) as archive:
        return "".join(archive.read(name).decode() for name in archive.namelist() if name.endswith(".xml"))


def all_cells(book):
    return [cell for sheet in book.worksheets[5:] for row in sheet.iter_rows() for cell in row]


# --- CLI and raw_data.json ---

def test_fixture_cli_is_offline_and_writes_only_workbook_and_raw_data(tmp_path: Path) -> None:
    with NO_AZURE:
        assert main([
            "collect", "--config", str(ROOT / "custom-config.yaml"),
            "--fixture", str(ROOT / "tests" / "fixtures" / "three_subscriptions.json"),
            "--output-dir", str(tmp_path),
        ]) == 0
    runs = list(tmp_path.iterdir())
    assert len(runs) == 1 and runs[0].is_dir()
    assert re.fullmatch(r"\d{8}T\d{12}Z(?:-\d+)?", runs[0].name)
    names = sorted(path.name for path in runs[0].iterdir())
    assert len(names) == 2
    assert names == [f"raw-data-{runs[0].name}.json", f"report-{runs[0].name}.xlsx"]
    result = load_result(tmp_path)
    assert result["mode"] == "fixture"
    agents = result["collection"]["agents"]
    assert len(agents) == 3 and len(result["findings"]) == 22
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
    assert workbook.parent.parent == output and workbook.name == report_name(data, workbook.parent.name)
    assert {path.name for path in workbook.parent.iterdir()} == {workbook.name, raw_name(data, workbook.parent.name)}
    assert workbook.stem.removeprefix("report-") == workbook.parent.name
    assert latest_raw(output).stem.removeprefix("raw-data-") == workbook.parent.name
    assert load_result(output)["collection"]["collected_at"] == data.model_dump(mode="json")["collected_at"]
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


def test_legacy_audit_code_migrates_without_reusing_retired_risk_score(tmp_path: Path) -> None:
    data = sample().model_dump(mode="json")
    data["agent_ca_policies"] = []
    data["risky_agents"] = []
    data["agents"][0]["se_codes"] = ["OE-SY-15", "OE-SY-16"]
    data["issues"].append({
        "collector": "risky_agents", "target": "tenant", "reason": "license_missing", "detail": "legacy",
    })
    payload = {
        "schema_version": 1, "collection": data, "mode": "fixture",
        "findings": [
            finding(se_code="OE-SY-15", level="L1", metric_value=0).model_dump(mode="json"),
            finding(se_code="OE-SY-16", level="L3", metric_value=365).model_dump(mode="json"),
        ],
    }
    (tmp_path / raw_name(sample())).write_text(json.dumps(payload), encoding="utf-8")
    result = load_result(tmp_path)
    assert [(row["se_code"], row["level"], row["metric_value"]) for row in result["findings"]] == [
        ("OE-SY-22", "L3", 365),
    ]
    assert "risky_agents" not in result["collection"] and "agent_ca_policies" not in result["collection"]
    assert result["collection"]["agents"][0]["se_codes"] == ["OE-SY-22"]
    assert not any(row["collector"] == "risky_agents" for row in result["collection"]["issues"])
    with NO_AZURE:
        assert main(["package", "--output-dir", str(tmp_path)]) == 0
    headers = load_workbook(tmp_path / report_name(sample())).sheetnames
    assert "위험Agent Raw 데이터" not in headers and "조건부접근 Raw 데이터" not in headers


def test_previous_operate_codes_migrate_once_and_keep_audit_score(tmp_path: Path) -> None:
    data = sample().model_dump(mode="json")
    data["facts"]["proposal_incomplete"] = ["OE-SY-18"]
    codes = ["OE-SY-15", "OE-SY-17", "OE-SY-18", "OE-SY-19", "OE-SY-20"]
    payload = {
        "schema_version": 1, "collection": data, "mode": "fixture",
        "findings": [finding(se_code=code, level="L3").model_dump(mode="json") for code in codes],
    }
    source = tmp_path / raw_name(sample())
    source.write_text(json.dumps(payload), encoding="utf-8")
    result = load_result(tmp_path)
    expected = ["OE-SY-22", "OE-SY-23", "OE-SY-24", "OE-SY-25", "OE-SY-26"]
    assert [row["se_code"] for row in result["findings"]] == expected
    assert result["collection"]["facts"]["proposal_incomplete"] == ["OE-SY-24"]
    assert result["collection"]["facts"]["assessment_revision"] == 5
    with NO_AZURE:
        assert main(["package", "--output-dir", str(tmp_path)]) == 0
    assert [row["se_code"] for row in load_result(tmp_path)["findings"]] == expected


def test_current_operate_codes_are_not_interpreted_as_legacy_audit(tmp_path: Path) -> None:
    write_reports(sample(), [
        finding(se_code="OE-SY-22", level="L3", metric_value=365),
        finding(se_code="OE-SY-23", level="L2", metric_value=0.5),
    ], tmp_path)
    result = load_result(tmp_path)
    assert [(row["se_code"], row["metric_value"]) for row in result["findings"]] == [
        ("OE-SY-22", 365), ("OE-SY-23", 0.5),
    ]


# --- evidence attachment and provenance ---

def test_revision_three_build_migration_drops_red_team_without_reusing_its_score(tmp_path: Path) -> None:
    data = sample().model_dump(mode="json")
    data["facts"]["assessment_revision"] = 3
    data["agents"][0]["se_codes"] = ["BI-SY-11", "BI-SY-12", "BI-SY-13", "BI-SY-14"]
    payload = {
        "schema_version": 1, "collection": data, "mode": "fixture",
        "findings": [
            finding(se_code="BI-SY-11", level="L5").model_dump(mode="json"),
            finding(se_code="BI-SY-12", level="L2").model_dump(mode="json"),
            finding(se_code="BI-SY-13", level="L3").model_dump(mode="json"),
            finding(se_code="BI-SY-14", level="L1").model_dump(mode="json"),
        ],
    }
    (tmp_path / raw_name(sample())).write_text(json.dumps(payload), encoding="utf-8")
    result = load_result(tmp_path)
    expected = [("BI-SY-14", "L2"), ("BI-SY-15", "L3"), ("BI-SY-16", "L1")]
    assert [(row["se_code"], row["level"]) for row in result["findings"]] == expected
    assert result["collection"]["agents"][0]["se_codes"] == [code for code, _ in expected]
    with NO_AZURE:
        assert main(["package", "--output-dir", str(tmp_path)]) == 0
    assert [(row["se_code"], row["level"]) for row in load_result(tmp_path)["findings"]] == expected


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
    assert json.loads(raw_record(book, "Agent Raw 데이터")["evidence_refs"].value) == ["evidence:" + identifier]
    values = [c.value for sheet in book for row in sheet.iter_rows()
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
    refs = json.loads(raw_record(load_workbook(workbook), "Agent Raw 데이터")["evidence_refs"].value)
    assert refs == result["collection"]["agents"][0]["evidence_refs"]
    assert len(refs) == len(bad) + 1


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
    assert {path.name for path in workbook.parent.iterdir()} == {workbook.name, latest_raw(output).name}
    assert list(output.iterdir()) == [workbook.parent]
    assert latest_raw(output).name == f"raw-data-{workbook.parent.name}.json"
    assert after["manifest"]["files"][0]["sha256"] == hashlib.sha256(workbook.read_bytes()).hexdigest()
    assert json.loads(raw_record(load_workbook(workbook), "Agent Raw 데이터")["evidence_refs"].value) == (
        after["collection"]["agents"][0]["evidence_refs"]
    )


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
    originals = {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    data.agents[0].agent_name = "new name"
    with patch("wasm_agent.report.os.replace", side_effect=OSError("locked")), pytest.raises(OSError):
        write_reports(data, [], output)
    assert {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()} == originals
    assert not [path for path in output.rglob("*") if "pending" in path.name]


def test_failed_replace_on_first_write_leaves_empty_output(tmp_path: Path) -> None:
    output = tmp_path / "fresh"
    with patch("wasm_agent.report.os.replace", side_effect=OSError("locked")), pytest.raises(OSError):
        write_reports(sample(), [], output)
    assert list(output.iterdir()) == []


def test_repeated_collection_timestamp_creates_distinct_runs_without_overwrite(tmp_path: Path) -> None:
    data = sample()
    first = write_reports(data, [], tmp_path)
    original = first.read_bytes()
    data.agents[0].agent_name = "second run"
    second = write_reports(data, [], tmp_path)
    assert first.parent != second.parent and first.name != second.name
    assert first.stem.removeprefix("report-") == first.parent.name
    assert second.stem.removeprefix("report-") == second.parent.name
    assert first.read_bytes() == original
    assert latest_raw(tmp_path).parent == second.parent
    assert load_result(first.parent)["collection"]["agents"][0]["agent_name"] == "테스트 Agent"
    assert load_result(second.parent)["collection"]["agents"][0]["agent_name"] == "second run"


def test_run_collision_uses_sequence_and_latest_discovery_is_numeric(tmp_path: Path) -> None:
    from wasm_agent.report import create_run_directory

    fixed = datetime(2026, 11, 5, 1, 2, 3, 456789, tzinfo=UTC)
    with patch("wasm_agent.report.datetime", wraps=datetime) as clock:
        clock.now.return_value = fixed
        runs = [create_run_directory(tmp_path) for _ in range(12)]
    for run in runs:
        (run / raw_name(sample())).write_text("{}", encoding="utf-8")
    assert len(set(runs)) == 12
    assert runs[-1].name.endswith("-11")
    assert latest_raw(tmp_path).parent == runs[-1]


def test_new_report_names_match_run_stamp_including_collision_suffix(tmp_path: Path) -> None:
    fixed = datetime(2026, 11, 5, 1, 2, 3, 456789, tzinfo=UTC)
    with patch("wasm_agent.report.datetime", wraps=datetime) as clock:
        clock.now.return_value = fixed
        first = write_reports(sample(), [], tmp_path)
        second = write_reports(sample(), [], tmp_path)
    assert second.parent.name == first.parent.name + "-1"
    for path in (first, second):
        assert path.name == f"report-{path.parent.name}.xlsx"
        assert latest_raw(path.parent).name == f"raw-data-{path.parent.name}.json"
    assert latest_raw(tmp_path).parent == second.parent


def test_downloaded_microsecond_raw_file_can_be_found_in_flat_folder(tmp_path: Path) -> None:
    path = tmp_path / "raw-data-20261105T010203456789Z-10.json"
    path.write_text("{}", encoding="utf-8")
    assert latest_raw(tmp_path) == path


def test_latest_raw_supports_legacy_files_without_searching_unrelated_folders(tmp_path: Path) -> None:
    legacy = tmp_path / "raw-data-20261104T000000Z.json"
    legacy.write_text("{}", encoding="utf-8")
    ignored = tmp_path / "unrelated"
    ignored.mkdir()
    (ignored / "raw-data-20990101T000000Z.json").write_text("{}", encoding="utf-8")
    assert latest_raw(tmp_path) == legacy
    current = tmp_path / "20261105T000000000001Z"
    current.mkdir()
    (current / "raw-data-20200101T000000Z.json").write_text("{}", encoding="utf-8")
    assert latest_raw(tmp_path).parent == current


def test_package_rebuilds_explicit_legacy_directory_without_nesting(tmp_path: Path) -> None:
    path = write_reports(sample(), [], tmp_path, new_run=False)
    with NO_AZURE:
        assert main(["package", "--output-dir", str(tmp_path)]) == 0
    assert set(tmp_path.iterdir()) == {path, tmp_path / raw_name(sample())}


# --- workbook structure ---

def test_workbook_sheets_tables_borders_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    write_workbook(sample(), [finding()], path, "fixture", [])
    book = load_workbook(path)
    assert book.sheetnames == SHEETS
    for sheet in book.worksheets[6:]:
        assert sheet.freeze_panes == (
            "A3" if sheet.title == TITLES["수집 Raw 데이터"] else
            "A4" if sheet.title == TITLES["수집결과 근거"] else "A2"
        )
        assert len(sheet.tables) == (12 if sheet.title == TITLES["수집 Raw 데이터"] else 1)
        # Excel repairs a file that has both a table and a sheet-level autoFilter on one range.
        assert not sheet.auto_filter.ref
        assert all(
            cell.font.name == "Arial"
            and cell.hyperlink is None for row in sheet for cell in row if cell.value is not None
        )
        assert all(cell.font.size == 10 for row in sheet for cell in row if cell.value is not None)
        assert sheet.sheet_view.zoomScale == 80
        for table in sheet.tables.values():
            _, header, last_column, last_row = range_boundaries(table.ref)
            columns = [column.name for column in table.tableColumns]
            assert columns == [sheet.cell(header, column).value for column in range(1, last_column + 1)]
            assert len(set(columns)) == len(columns) and all(isinstance(value, str) for value in columns)
            assert sheet.cell(header, 1).fill.fgColor.rgb == "00D9D9D9"
            for row in sheet.iter_rows(min_row=header, max_row=last_row, max_col=last_column):
                for cell in row:
                    for side in ("left", "right", "top", "bottom"):
                        outer = (
                            (side == "left" and cell.column == 1)
                            or (side == "right" and cell.column == last_column)
                            or (side == "top" and cell.row == header)
                            or (side == "bottom" and cell.row == last_row)
                        )
                        if sheet.title == TITLES["수집결과 근거"] and (cell.row > header or side == "right"):
                            outer = False
                        assert getattr(cell.border, side).style == ("medium" if outer else "thin")
    validations = book[RESULT_SHEET].data_validations.dataValidation
    assert len(validations) == 1
    assert validations[0].type == "whole" and validations[0].operator == "between"
    assert validations[0].formula1 == "1" and validations[0].formula2 == "5"
    assert validations[0].allow_blank is True
    assert validations[0].showErrorMessage is True and "L5" in validations[0].sqref
    checklist = book[RESULT_SHEET]
    assert checklist["L4"].value == "평가 점수\n(1~5)" and checklist["B4"].value == "No"
    assert checklist["I4"].font.bold is True
    assert checklist.freeze_panes == "G5" and checklist.auto_filter.ref == "B4:M89"
    assert all(checklist.cell(row, 12).alignment.horizontal == "center" for row in range(4, 90))
    for row in range(5, checklist.max_row + 1):
        if checklist.cell(row, 7).value == "수집됨":
            assert checklist.row_dimensions[row].height == 110
    proposals = book[TITLES["수집결과 근거"]]
    assert proposals.row_dimensions[4].height == 60 and proposals["F4"].fill.patternType is None
    assert "수집된 설정·값·건수" in proposals["A1"].value
    assert all("개선 제안 목록이 아님" not in str(cell.value) for cell in all_cells(book))
    assert all(proposals.cell(3, column).comment for column in range(1, 10))


def test_workbook_values_keep_types_and_checklist_labels(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    write_workbook(sample(), [finding()], path)
    book = load_workbook(path)
    agent = raw_record(book, "Agent Raw 데이터")
    assert set(AgentEvidence.model_fields) <= agent.keys()
    assert (agent["agent_id"].value, agent["agent_id"].data_type, agent["agent_id"].number_format) == (
        "000001", "s", "@")
    assert (agent["cost_30d"].value, agent["cost_30d"].data_type) == (0, "n")
    assert (agent["guardrail_applied"].value, agent["guardrail_applied"].data_type) == (False, "b")
    assert agent["calls_90d"].value is None
    raw = json.loads(agent["원본 JSON"].value)
    assert raw["cost_30d"] == 0 and raw["calls_90d"] is None and raw["guardrail_applied"] is False
    assert raw["owner"].startswith("identity-") and raw["tags"]["secret"] == "[REDACTED]"
    logs = raw_record(book, "로그 Raw 데이터")
    assert (logs["retention_days"].value, logs["enabled"].data_type) == (0, "b")
    evaluation = raw_record(book, "평가 Raw 데이터")
    assert [evaluation[k].value for k in ("passed_items", "failed_items", "errored_items")] == [0, 3, 2]
    checklist = record(book[RESULT_SHEET])
    assert (checklist["판정"].value, checklist["지표"].value) == ("판정 보류", "0.00%")
    assert "원인" not in checklist and checklist["평가 점수\n(1~5)"].value is None
    assert "조회 권한 부족" in checklist["근거"].value
    assert len(records(book[TITLES["수집이슈 Raw 데이터"]])) == 2
    assert next(iter(raw_record(book, "모델배포 Raw 데이터").values())).value.startswith("수집된 데이터 없음")


def test_missing_metric_is_not_converted_to_zero_and_null_differs_from_zero(tmp_path: Path) -> None:
    data = sample()
    data.agents[0].unavailable("model", "permission_denied", "관리자가 조회 역할을 확인해야 합니다.")
    data.evaluations[0].failed_items = None
    path = tmp_path / "null.xlsx"
    write_workbook(data, [finding(se_code="DS-SY-06", metric_value=None)], path)
    book = load_workbook(path)
    assert record(book[RESULT_SHEET])["지표"].value == "확인 자료 없음 - 분모 확인 안됨"
    evaluation = raw_record(book, "평가 Raw 데이터")
    assert evaluation["failed_items"].value is None and evaluation["passed_items"].value == 0
    missing = records(book[TITLES["필드누락사유"]])
    model = next(row for row in missing if row["field"].value == "model")
    assert model["reason"].value == "permission_denied" and "조회 역할" in model["설명"].value
    calls = next(row for row in missing if row["field"].value == "calls_90d")
    assert calls["reason"].value == "not_found" and "원본 값이 null" in calls["설명"].value
    assert not any(row["field"].value in ("cost_30d", "guardrail_applied") for row in missing)


def test_result_categories_do_not_hide_partial_collection_or_failed_queries(tmp_path: Path) -> None:
    path = tmp_path / "categories.xlsx"
    write_workbook(sample(), [
        finding(),
        finding(se_code="DS-SY-06", metric_value=None),
    ], path)
    sheet = load_workbook(path)[RESULT_SHEET]
    rows = {sheet.cell(row, 2).value: row for row in range(5, sheet.max_row + 1)}
    assert {sheet.cell(row, 7).value for row in range(5, sheet.max_row + 1)} == {
        "수집됨", "수집하지 않음", "인터뷰 필요",
    }
    assert sheet.cell(rows["BI-SY-11"], 7).value == "수집됨"
    assert "일부 수집" in sheet.cell(rows["BI-SY-11"], 10).value
    assert sheet.cell(rows["DS-SY-06"], 7).value == "수집하지 않음"
    assert "조회 권한 부족" in sheet.cell(rows["DS-SY-06"], 10).value
    assert sheet.cell(rows["DS-SY-06"], 12).value is None
    assert sheet.cell(rows["DM-PR-01"], 7).value == "인터뷰 필요"
    assert sheet.cell(rows["DM-PR-01"], 12).value is None
    assert sheet.cell(rows["DM-SY-01"], 12).value is None


def test_merged_raw_preserves_evidence_references_without_a_reference_sheet(tmp_path: Path) -> None:
    data = sample()
    for field in ("agents", "evaluations", "costs", "logs"):
        for item in getattr(data, field):
            item.evidence_refs = ["fixture://" + field]
    path = tmp_path / "raw.xlsx"
    write_workbook(data, [], path)
    book = load_workbook(path)
    assert not any("증거참조" in title or "읽는법" in title for title in book.sheetnames)
    for field, title in (
        ("agents", "Agent Raw 데이터"), ("evaluations", "평가 Raw 데이터"),
        ("costs", "비용 Raw 데이터"), ("logs", "로그 Raw 데이터"),
    ):
        original = json.loads(raw_record(book, title)["원본 JSON"].value)
        assert original["evidence_refs"] == ["fixture://" + field]


def test_empty_collection_has_placeholder_rows_without_fabricated_zero_values(tmp_path: Path) -> None:
    path = tmp_path / "empty.xlsx"
    write_workbook(Collection(collected_at=datetime(2026, 11, 3, tzinfo=UTC)), [], path)
    book = load_workbook(path)
    for title in ("Agent Raw 데이터", "평가 Raw 데이터"):
        sheet, (_, header, last_column, last_row) = raw_bounds(book, title)
        assert "수집된 데이터 없음" in sheet.cell(header + 1, 1).value
        assert all(cell.value != 0 for row in sheet.iter_rows(
            min_row=header + 1, max_row=last_row, max_col=last_column,
        ) for cell in row)
    for title in ("수집이슈 Raw 데이터",):
        sheet = book[TITLES[title]]
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
    agent = raw_record(book, "Agent Raw 데이터")
    assert agent["agent_name"].value == text and agent["agent_name"].data_type == "s"
    assert record(book[RESULT_SHEET])["근거"].value.endswith("판정 근거: " + text)
    assert json.loads(raw_record(book, "Agent Raw 데이터")["evidence_refs"].value) == [text]
    amount = raw_record(book, "비용 Raw 데이터")["amount"]
    assert amount.value == -12.5 and amount.data_type == "n"
    assert all(cell.data_type != "f" and cell.hyperlink is None for cell in all_cells(book))
    with ZipFile(path) as archive:
        names = archive.namelist()
        assert not any("externalLink" in name or "vbaProject" in name for name in names)
        sheets = [
            archive.read(f"xl/worksheets/sheet{index}.xml").decode()
            for index in range(6, len(SHEETS) + 1)
        ]
    assert len(sheets) == len(SHEETS) - 5 and not any(re.search(r"<f[\s>/]", xml) for xml in sheets)


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
