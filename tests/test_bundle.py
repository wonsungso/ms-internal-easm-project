from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wasm_agent.models import AgentEvidence, Collection
from wasm_agent.reporting.bundle import RESULT_FILES, create_bundle


def prepared(tmp_path: Path) -> tuple[Collection, Path, Path]:
    output = tmp_path / "output"
    output.mkdir()
    evidence = tmp_path / "evidence" / "run"
    evidence.mkdir(parents=True)
    source = evidence / "response.json"
    source.write_text(json.dumps({"api_key": "do-not-export", "value": 2}), encoding="utf-8")
    now = datetime.now(UTC)
    data = Collection(
        collected_at=now,
        agents=[AgentEvidence(
            collected_at=now, platform="foundry", agent_id="a", agent_name="A",
            detection_confidence="tag", evidence_refs=[str(source.resolve())],
        )],
        facts={"evidence_directory": str(evidence)},
    )
    for name in RESULT_FILES:
        if name.endswith(".json"):
            (output / name).write_text(json.dumps({"evidence_refs": [str(source.resolve())]}), encoding="utf-8")
        else:
            (output / name).write_text('<a href="../evidence/run/response.json">증거</a>', encoding="utf-8")
    return data, output, source


def test_bundle_is_portable_masked_and_excludes_authentication(tmp_path: Path) -> None:
    data, output, source = prepared(tmp_path)
    (output / "setup.json").write_text('{"credentials":"never"}', encoding="utf-8")
    (output / "private.pem").write_text("PRIVATE KEY", encoding="utf-8")
    (output / "old.zip").write_bytes(b"old")
    archive = create_bundle(data, output)
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert {"setup.json", "private.pem", "old.zip"}.isdisjoint(names)
        assert "evidence/run/response.json" in names
        assert "do-not-export" not in bundle.read("evidence/run/response.json").decode()
        assert b'href="evidence/run/response.json"' in bundle.read("report.html")
        assert json.loads(bundle.read("collection.json"))["evidence_refs"] == ["evidence/run/response.json"]
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["credentials_included"] is False
        assert manifest["unattached_evidence"] == []
        assert all(entry["sha256"] for entry in manifest["files"])
        assert str(source).encode() not in bundle.read("inventory.json")
        assert bundle.testzip() is None


def test_bundle_reports_external_or_missing_references(tmp_path: Path) -> None:
    data, output, _ = prepared(tmp_path)
    private = tmp_path / "outside.json"
    private.write_text('{"password":"never"}', encoding="utf-8")
    data.agents[0].evidence_refs.extend([str(private), "fixture://missing"])
    with zipfile.ZipFile(create_bundle(data, output)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        assert len(manifest["unattached_evidence"]) == 2
        assert all(not name.endswith("outside.json") for name in bundle.namelist())


def test_bundle_fails_explicitly_if_required_report_is_missing(tmp_path: Path) -> None:
    data, output, _ = prepared(tmp_path)
    (output / "report.html").unlink()
    with pytest.raises(ValueError, match="필수 결과"):
        create_bundle(data, output)
    assert not list(output.glob("wasm-agent-*.zip"))


def test_fixture_bundle_is_not_labeled_as_live(tmp_path: Path) -> None:
    data, output, _ = prepared(tmp_path)
    archive = create_bundle(data, output, "fixture")
    assert archive.name.startswith("wasm-agent-example-")
    with zipfile.ZipFile(archive) as bundle:
        assert json.loads(bundle.read("manifest.json"))["mode"] == "fixture"


def test_package_cli_uses_saved_results_without_azure(tmp_path: Path) -> None:
    from unittest.mock import patch

    from wasm_agent.cli import main
    from wasm_agent.reporting.reports import write_reports

    data, output, _ = prepared(tmp_path)
    data.facts["data_mode"] = "live"
    write_reports(data, [], output)
    with patch("wasm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("no Azure calls")):
        assert main(["package", "--output-dir", str(output)]) == 0
    assert len(list(output.glob("wasm-agent-results-*.zip"))) == 1


def test_package_cli_cannot_relabel_recorded_fixture_as_live(tmp_path: Path) -> None:
    from wasm_agent.cli import main
    from wasm_agent.reporting.reports import write_reports

    data, output, _ = prepared(tmp_path)
    data.facts["data_mode"] = "fixture"
    write_reports(data, [], output, "fixture")
    assert main(["package", "--output-dir", str(output), "--mode", "live"]) == 1
    assert not list(output.glob("wasm-agent-results-*.zip"))
