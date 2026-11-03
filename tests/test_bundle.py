from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import load_workbook

from wasm_agent.cli import main
from wasm_agent.evidence import redact
from wasm_agent.models import AgentEvidence, Collection, Finding
from wasm_agent.report import load_result, write_reports
from wasm_agent.report_bundle import RESULT_FILES, create_bundle
from wasm_agent.report_data import snapshot_path


@pytest.fixture(autouse=True)
def isolated_result_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "wasm_agent.report_data.STATE_ROOT",
        tmp_path.parent / (tmp_path.name + "-runtime"),
    )


def prepared(tmp_path: Path, mode: str = "live") -> tuple[Collection, Path, Path]:
    output = tmp_path / "output"
    evidence = tmp_path / "evidence" / "run"
    evidence.mkdir(parents=True)
    source = evidence / "response.json"
    source.write_text(json.dumps({
        "api_key": "do-not-export", "value": 2, "email": "someone@example.invalid",
        "response": {"status": "completed", "note": "<script>alert(1)</script>", "value": None},
        "messages": ["private evaluation conversation"],
    }), encoding="utf-8")
    now = datetime.now(UTC)
    data = Collection(
        collected_at=now,
        agents=[AgentEvidence(
            collected_at=now, platform="foundry", agent_id="a", agent_name="A",
            detection_confidence="tag", evidence_refs=[str(source.resolve())],
        )],
        facts={"evidence_directory": str(evidence), "data_mode": mode},
    )
    write_reports(data, [Finding(
        se_code="DS-SY-06", scope="partial", level="N/A", reason="permission_denied", rationale="조회 보류",
        evidence_refs=[str(source.resolve())],
    )], output, mode)
    return data, output, source


def test_bundle_is_portable_masked_and_excludes_authentication(tmp_path: Path) -> None:
    data, output, source = prepared(tmp_path)
    archive = create_bundle(data, output)
    assert {path.name for path in output.iterdir()} == {"report.html", "report.xlsx", "results.zip"}
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == set(RESULT_FILES)
        assert len(bundle.namelist()) == 3
        result = json.loads(bundle.read("data.json"))
        identifier, payload = next(iter(result["evidence"].items()))
        assert payload == redact(json.loads(source.read_text(encoding="utf-8")))
        text = bundle.read("report.html").decode()
        assert "do-not-export" not in text
        assert "someone@example.invalid" not in text
        assert "private evaluation conversation" not in text
        assert "<script>" not in text
        assert f'href=\'#evidence-{identifier}\'' in text
        assert f'<details id="evidence-{identifier}">' in text
        raw = re.search(r"<pre>(.*?)</pre>", text, flags=re.DOTALL)
        assert raw is not None
        assert json.loads(html.unescape(raw[1])) == payload
        anchors = set(re.findall(r'id="(evidence-[a-f0-9]{64})"', text))
        links = set(re.findall(r"href=['\"]#(evidence-[a-f0-9]{64})['\"]", text))
        assert links == anchors == {"evidence-" + key for key in result["evidence"]}
        assert "report.xlsx" in text
        assert "report.md" not in text and "customer_summary.csv" not in text
        assert result["collection"]["agents"][0]["evidence_refs"] == ["evidence:" + identifier]
        assert result["findings"][0]["metric_value"] is None
        assert result["findings"][0]["level"] == "N/A"
        assert result["findings"][0]["reason"] == "permission_denied"
        assert result["schema_version"] == 1
        assert result["manifest"]["credentials_included"] is False
        assert result["provenance"]["unattached_evidence"] == []
        assert result["provenance"]["references"][0]["reference"] == str(source.resolve())
        for entry in result["manifest"]["files"]:
            assert entry["sha256"] == hashlib.sha256(bundle.read(entry["path"])).hexdigest()
        assert bundle.testzip() is None
        book = load_workbook(BytesIO(bundle.read("report.xlsx")))
        values = [cell.value for sheet in book for row in sheet for cell in row
                  if isinstance(cell.value, str)]
        assert any("evidence:" + identifier in value for value in values)
        assert any("data.json" in value for value in values)
        assert not any(str(source) in value for value in values)
        assert all(cell.hyperlink is None and cell.data_type != "f"
                   for sheet in book for row in sheet for cell in row)
        book.close()


def test_bundle_reports_external_or_missing_references(tmp_path: Path) -> None:
    data, output, _ = prepared(tmp_path)
    private = tmp_path / "outside.json"
    private.write_text('{"password":"never"}', encoding="utf-8")
    data.agents[0].evidence_refs.extend([str(private), "fixture://missing", "../outside.json"])
    write_reports(data, [], output)
    with zipfile.ZipFile(create_bundle(data, output)) as bundle:
        result = json.loads(bundle.read("data.json"))
        assert len(result["provenance"]["unattached_evidence"]) == 3
        assert len(result["evidence"]) == 1
        assert "파일 확인불가" in bundle.read("report.html").decode()


def test_bundle_fails_explicitly_if_required_report_is_missing(tmp_path: Path) -> None:
    data, output, _ = prepared(tmp_path)
    (output / "report.html").unlink()
    with pytest.raises(ValueError, match="필수 결과"):
        create_bundle(data, output)
    assert not (output / "results.zip").exists()


def test_fixture_bundle_is_not_labeled_as_live(tmp_path: Path) -> None:
    data, output, _ = prepared(tmp_path, "fixture")
    archive = create_bundle(data, output, "fixture")
    assert archive.name == "results.zip"
    with zipfile.ZipFile(archive) as bundle:
        result = json.loads(bundle.read("data.json"))
        assert result["mode"] == result["manifest"]["mode"] == "fixture"


@pytest.mark.parametrize("zip_only", [False, True])
def test_package_cli_uses_saved_results_without_azure_or_evidence(
    tmp_path: Path, zip_only: bool,
) -> None:
    data, output, source = prepared(tmp_path)
    create_bundle(data, output)
    before = load_result(output)
    source.unlink()
    if zip_only:
        snapshot_path(output).unlink()
    with patch("wasm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("no Azure calls")):
        assert main(["package", "--output-dir", str(output)]) == 0
    after = load_result(output)
    assert after["evidence"] == before["evidence"]
    assert after["findings"] == before["findings"]
    assert after["collection"] == before["collection"]
    assert after["provenance"] == before["provenance"]
    assert {path.name for path in output.iterdir()} == {"report.html", "report.xlsx", "results.zip"}
    with zipfile.ZipFile(output / "results.zip") as bundle:
        assert set(bundle.namelist()) == set(RESULT_FILES)
        assert "#evidence-" in bundle.read("report.html").decode()


def test_package_cli_cannot_relabel_recorded_fixture_as_live(tmp_path: Path) -> None:
    _, output, _ = prepared(tmp_path, "fixture")
    assert main(["package", "--output-dir", str(output), "--mode", "live"]) == 1
    assert not (output / "results.zip").exists()


def test_unknown_files_and_previous_zip_are_preserved_on_atomic_failure(tmp_path: Path) -> None:
    data, output, _ = prepared(tmp_path)
    archive = create_bundle(data, output)
    original = archive.read_bytes()
    for name in ("setup.json", "private.pem", "old.zip"):
        (output / name).write_bytes(b"unknown")
    with patch("wasm_agent.report_bundle.os.replace", side_effect=OSError("locked")):
        with pytest.raises(OSError):
            create_bundle(data, output)
    assert archive.read_bytes() == original
    assert {path.name for path in output.iterdir()} == {
        "report.html", "report.xlsx", "results.zip", "setup.json", "private.pem", "old.zip",
    }
    create_bundle(data, output)
    assert archive.name == "results.zip" and (output / "old.zip").read_bytes() == b"unknown"
    assert not list(output.glob(".results.*"))
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == set(RESULT_FILES)


def test_legacy_package_migration_and_compact_result_priority(tmp_path: Path) -> None:
    data, output, _ = prepared(tmp_path)
    result = load_result(output)
    snapshot_path(output).unlink()
    (output / "collection.json").write_text(data.model_dump_json(), encoding="utf-8")
    (output / "findings.json").write_text(json.dumps(result["findings"]), encoding="utf-8")
    assert main(["package", "--output-dir", str(output)]) == 0
    (output / "collection.json").write_text("invalid", encoding="utf-8")
    assert load_result(output)["schema_version"] == 1
    assert main(["package", "--output-dir", str(output)]) == 0


def test_symlink_evidence_is_never_embedded(tmp_path: Path) -> None:
    data, output, source = prepared(tmp_path)
    link = source.parent / "alias.json"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlink permission unavailable")
    data.agents[0].evidence_refs = [str(link)]
    write_reports(data, [], output)
    result = load_result(output)
    assert result["evidence"] == {}
    assert len(result["provenance"]["unattached_evidence"]) == 1


def test_snapshot_is_single_file_and_refs_are_normalized_without_changing_raw_json(
    tmp_path: Path,
) -> None:
    data, output, source = prepared(tmp_path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["original_path"] = str(source.resolve())
    source.write_text(json.dumps(raw), encoding="utf-8")
    data.facts["original_reference"] = str(source.resolve())
    write_reports(data, [], output)
    result = load_result(output)
    identifier = next(iter(result["evidence"]))
    assert result["collection"]["facts"]["original_reference"] == "evidence:" + identifier
    assert result["evidence"][identifier]["original_path"] == str(source.resolve())
    assert result["evidence"][identifier] == redact(raw)
    assert len(list(snapshot_path(output).parent.glob("*.json"))) == 1
    source.unlink()
    write_reports(data, [], output)
    assert load_result(output)["evidence"] == result["evidence"]


def test_atomic_report_failure_preserves_existing_reports_and_snapshot(tmp_path: Path) -> None:
    data, output, _ = prepared(tmp_path)
    create_bundle(data, output)
    originals = {path: path.read_bytes() for path in output.iterdir()}
    snapshot = snapshot_path(output).read_bytes()
    data.agents[0].agent_name = "new name"
    with patch("wasm_agent.report.os.replace", side_effect=OSError("locked")):
        with pytest.raises(OSError):
            write_reports(data, [], output)
    assert {path: path.read_bytes() for path in output.iterdir()} == originals
    assert snapshot_path(output).read_bytes() == snapshot


def test_imported_zip_overrides_stale_snapshot_when_packaging(tmp_path: Path) -> None:
    old, output, old_source = prepared(tmp_path)
    create_bundle(old, output)
    stale_snapshot = snapshot_path(output).read_bytes()
    newer, incoming, incoming_source = prepared(tmp_path / "external")
    newer.collected_at = old.collected_at + timedelta(minutes=8)
    newer.agents[0].agent_name = "newer imported Agent"
    incoming_source.write_text('{"response": {"latest": 34}}', encoding="utf-8")
    findings = [Finding(
        se_code="BI-SY-08", scope="partial", level="N/A", reason="not_found",
        rationale="새 ZIP의 평가 결과", evidence_refs=[str(incoming_source.resolve())],
    )]
    write_reports(newer, findings, incoming)
    create_bundle(newer, incoming)
    imported = load_result(incoming)
    shutil.copyfile(incoming / "results.zip", output / "results.zip")
    old_source.unlink()
    incoming_source.unlink()
    assert snapshot_path(output).read_bytes() == stale_snapshot
    assert "newer imported Agent" not in (output / "report.html").read_text(encoding="utf-8")
    assert load_result(output)["collection"] == imported["collection"]
    with patch("wasm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("no Azure calls")):
        assert main(["package", "--output-dir", str(output)]) == 0
    result = load_result(output)
    for field in ("collection", "findings", "evidence", "provenance"):
        assert result[field] == imported[field]
    assert result["collection"]["agents"][0]["agent_name"] == "newer imported Agent"
    snapshot = json.loads(snapshot_path(output).read_text(encoding="utf-8"))
    assert snapshot["collection"] == imported["collection"]
    assert "newer imported Agent" in (output / "report.html").read_text(encoding="utf-8")
    assert {path.name for path in output.iterdir()} == {"report.html", "report.xlsx", "results.zip"}
    with zipfile.ZipFile(output / "results.zip") as bundle:
        assert set(bundle.namelist()) == set(RESULT_FILES)


def test_write_reports_then_bundle_uses_pending_snapshot_not_previous_zip(tmp_path: Path) -> None:
    data, output, source = prepared(tmp_path)
    create_bundle(data, output)
    old = load_result(output)
    data.collected_at += timedelta(minutes=8)
    data.agents[0].agent_name = "new collection"
    source.write_text('{"response": {"new": true}}', encoding="utf-8")
    write_reports(data, [], output)
    assert load_result(output)["collection"] == old["collection"]
    create_bundle(data, output)
    result = load_result(output)
    assert result["collection"]["agents"][0]["agent_name"] == "new collection"
    assert result["collection"]["collected_at"] != old["collection"]["collected_at"]
    assert result["findings"] == []
    assert list(result["evidence"].values()) == [{"response": {"new": True}}]
