from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from openpyxl import load_workbook
from openpyxl.utils import range_boundaries

from wasm_agent.azure import AccessError, EvidenceStore, ReaderHTTP
from wasm_agent.collect_agent365 import (
    REGISTRY_URL,
    Agent365Collector,
    agent365_observations,
    crosscheck_agent365,
)
from wasm_agent.models import (
    Agent365Package,
    AgentEvidence,
    Collection,
    EntraAgentIdentity,
    EntraBlueprint,
    Finding,
    load_criteria,
)
from wasm_agent.report_excel import write_workbook

NOW = datetime(2026, 11, 9, tzinfo=UTC)
IDENTITY = "11111111-1111-4111-8111-111111111111"
BLUEPRINT = "22222222-2222-4222-8222-222222222222"
SID = "33333333-3333-4333-8333-333333333333"
OTHER = "44444444-4444-4444-8444-444444444444"


def http(rows: list[dict] | None = None) -> Mock:
    value = Mock(spec=ReaderHTTP, store=None, last_ref=None, subscription="")
    value.list_graph.return_value = rows or []
    return value


def snapshot() -> Collection:
    return Collection(
        collected_at=NOW,
        facts={
            "agent365_registry_complete": True, "entra_agents_complete": True,
            "entra_blueprints_complete": True, "agent_inventory_complete": True,
        },
        agent365_packages=[Agent365Package(package_id="package", agent_identity_id=IDENTITY, version="99")],
        entra_agent_identities=[EntraAgentIdentity(identity_id=IDENTITY, blueprint_id=BLUEPRINT)],
        entra_blueprints=[EntraBlueprint(blueprint_id=BLUEPRINT, tags=[
            f"subscriptionId:{SID}", "accountName:account", "projectName:project", "agentName:agent",
        ])],
        agents=[AgentEvidence(
            collected_at=NOW, platform="foundry", agent_id="agent-id", agent_name="agent", agent_version="1",
            subscription_id=SID, detection_confidence="tag",
            resource_id=f"/subscriptions/{SID}/resourceGroups/rg/providers/Microsoft.CognitiveServices/"
            "accounts/account/projects/project/agents/agent",
        )],
    )


def checks(data: Collection) -> dict:
    return {row.se_code: row for row in crosscheck_agent365(data, load_criteria())}


def test_registry_uses_documented_get_and_saves_only_minimal_fields(tmp_path: Path) -> None:
    source = http([{
        "id": "package", "agentIdentityId": IDENTITY, "version": "99",
        "displayName": "resource-agent", "publisher": "Personal Publisher",
        "zipFile": "secret package content", "shortDescription": "private text",
    }])
    store = EvidenceStore(tmp_path, NOW)
    result = Agent365Collector(source, NOW, store).discover()
    source.list_graph.assert_called_once_with(REGISTRY_URL)
    assert result.facts["agent365_registry_complete"] is True
    package = result.agent365_packages[0]
    assert package.agent_identity_id == IDENTITY
    text = Path(package.evidence_refs[0]).read_text(encoding="utf-8")
    assert not any(word in text for word in ("Personal Publisher", "secret package", "private text"))
    assert json.loads(text)["response"]["value"] == [{
        "id": "package", "agentIdentityId": IDENTITY, "version": "99",
        "displayName": "resource-agent", "platform": None, "availableTo": None,
        "deployedTo": None, "isBlocked": None,
    }]
    assert package.field_status["available_to"].reason == "not_found"


@pytest.mark.parametrize("reason", [
    "permission_denied", "license_missing", "feature_unavailable", "error",
])
def test_registry_failure_is_explicit_and_never_complete(reason: str, tmp_path: Path) -> None:
    source = http()
    source.list_graph.side_effect = AccessError(reason, "safe failure")
    result = Agent365Collector(source, NOW, EvidenceStore(tmp_path, NOW)).discover()
    assert result.agent365_packages == []
    assert result.facts["agent365_registry_complete"] is False
    assert result.issues[0].reason == reason
    assert result.issues[0].evidence_refs
    rows = checks(result)
    assert rows["DS-SY-05"].status == "unavailable" and rows["DS-SY-05"].reason == reason
    assert rows["DS-SY-05"].compared is None


@pytest.mark.parametrize("rows", [
    [{"version": "1"}], [{"id": ""}], [{"id": 123}],
    [{"id": "p"}, {"id": "p"}], [{"id": "p", "agentIdentityId": 123}],
    [{"id": "p", "agentIdentityId": "invalid"}], [{"id": "p", "version": 1}],
    [{"id": "p", "isBlocked": 1}], [{"id": "p", "availableTo": []}],
])
def test_malformed_registry_never_becomes_a_match(rows: list[dict]) -> None:
    result = Agent365Collector(http(rows), NOW).discover()
    assert not result.facts["agent365_registry_complete"]
    assert result.issues[0].reason == "error"
    assert result.agent365_packages == []


def test_rejects_raw_registry_capture_before_data_minimization() -> None:
    source = http()
    source.store = Mock()
    with pytest.raises(ValueError, match="최소 필드"):
        Agent365Collector(source, NOW)


def test_opaque_next_links_and_429_retry_use_existing_read_only_client() -> None:
    continuation = REGISTRY_URL + "?$skiptoken=opaque"
    responses = []
    for code, body in (
        (429, {}), (200, {"value": [{"id": "first"}], "@odata.nextLink": continuation}),
        (200, {"value": [{"id": "last", "agentIdentityId": IDENTITY}]}),
    ):
        response = Mock(status_code=code, headers={})
        response.json.return_value = body
        responses.append(response)
    session = Mock()
    session.request.side_effect = responses
    credential = Mock()
    credential.get_token.return_value.token = "fixture-token"
    with patch("wasm_agent.azure.time.sleep"):
        result = Agent365Collector(ReaderHTTP(credential, session=session), NOW).discover()
    assert [row.package_id for row in result.agent365_packages] == ["first", "last"]
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)
    assert session.request.call_args_list[-1].args[1] == continuation


@pytest.mark.parametrize("next_link", [
    REGISTRY_URL, REGISTRY_URL.replace("graph.microsoft.com", "outside.invalid"),
    REGISTRY_URL.replace("/catalog/packages", "/other"), [], 7,
])
def test_invalid_registry_pagination_is_an_explicit_failure(next_link: object) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {"value": [{"id": "p"}], "@odata.nextLink": next_link}
    session = Mock()
    session.request.return_value = response
    result = Agent365Collector(ReaderHTTP(Mock(), session=session), NOW).discover()
    assert result.issues[0].reason == "error"
    assert result.agent365_packages == [] and not result.facts["agent365_registry_complete"]
    assert session.request.call_count == 1


def test_partial_id_crosschecks_do_not_compare_unrelated_fields_or_same_graph_source() -> None:
    result = checks(snapshot())
    assert len(result) == 22
    for code in ("DS-SY-05", "DP-SY-19"):
        assert result[code].status == "partial_match"
        assert result[code].matched == result[code].compared == 1
    for code in set(result) - {"DS-SY-05", "DP-SY-19"}:
        assert result[code].status == "not_comparable"
        assert result[code].matched is None
    assert "다른 필드" in result["BI-SY-14"].detail
    assert "동일 원천" in result["OE-SY-20"].detail and "동일 원천" in result["OE-SY-21"].detail


def test_registry_reference_missing_from_complete_graph_is_mismatch() -> None:
    data = snapshot()
    data.agent365_packages[0].agent_identity_id = OTHER
    result = checks(data)
    assert result["DS-SY-05"].status == "mismatch"
    assert result["DS-SY-05"].mismatched == 1
    assert result["DP-SY-19"].status == "unavailable"


def test_missing_graph_blueprint_field_is_unknown_not_mismatch() -> None:
    data = snapshot()
    data.entra_agent_identities[0].blueprint_id = None
    result = checks(data)["DS-SY-05"]
    assert result.status == "unavailable" and result.unverified == 1 and result.mismatched == 0


@pytest.mark.parametrize("marker", [
    "agent365_registry_complete", "entra_agents_complete", "entra_blueprints_complete", "agent_inventory_complete",
])
def test_incomplete_inventories_cannot_match(marker: str) -> None:
    data = snapshot()
    data.facts.pop(marker)
    assert checks(data)["DP-SY-19"].status == "unavailable"


def test_missing_identity_field_empty_registry_and_unpublished_agents_are_not_failure_proof() -> None:
    data = snapshot()
    data.agent365_packages = [Agent365Package(package_id="without-agent-id")]
    for row in checks(data).values():
        assert row.status != "mismatch"
    data.agent365_packages = []
    assert checks(data)["DS-SY-05"].status == "unavailable"


def test_display_names_are_never_join_keys_and_ambiguous_connections_do_not_match() -> None:
    data = snapshot()
    data.entra_agent_identities[0].display_name = "unrelated name"
    assert checks(data)["DP-SY-19"].status == "partial_match"
    data.entra_agent_identities.append(EntraAgentIdentity(identity_id=OTHER, blueprint_id=BLUEPRINT))
    result = checks(data)["DP-SY-19"]
    assert result.status == "unavailable" and result.unverified == 1


def test_duplicate_graph_id_does_not_create_false_match() -> None:
    data = snapshot()
    data.entra_agent_identities.append(data.entra_agent_identities[0].model_copy())
    assert checks(data)["DS-SY-05"].reason == "error"
    assert checks(data)["DP-SY-19"].status == "unavailable"


def test_report_keeps_grades_and_separates_crosscheck_details(tmp_path: Path) -> None:
    data = snapshot()
    data.agent365_crosschecks = list(checks(data).values())
    finding = Finding(se_code="DS-SY-05", scope="in_scope", level="L5", metric_value=1, rationale="primary grade")
    path = tmp_path / "report.xlsx"
    write_workbook(data, [
        finding,
        Finding(se_code="OE-SY-21", scope="in_scope", level="L5", metric_value=1, rationale="primary role grade"),
    ], path)
    book = load_workbook(path)
    details = book["7. 수집결과 근거"]
    table = next(table for table in details.tables.values() if table.ref.startswith("A3:"))
    rows = {details.cell(row, 1).value: row for row in range(4, range_boundaries(table.ref)[3] + 1)}
    assert details.cell(rows["DS-SY-05"], 10).value == "일부 일치"
    assert "기존 등급 유지" in details.cell(rows["DS-SY-05"], 11).value
    assert details.cell(rows["OE-SY-21"], 10).value == "동일 정보 미제공"
    assert "기존 Azure/Graph API로 평가" in details.cell(rows["OE-SY-21"], 11).value
    assert "평가 제외 아님" in details.cell(rows["OE-SY-21"], 11).value
    assert len(book["8. 수집 Raw 데이터"].tables) == 15
    assert finding.level == "L5"


def test_package_metadata_is_partial_evidence_not_automatic_scoring(tmp_path: Path) -> None:
    data = snapshot()
    data.agent365_packages[0].display_name = "registered-agent"
    data.agent365_packages[0].available_to = "allowedForAll"
    data.agent365_packages[0].deployed_to = "acquiredForSome"
    data.agent365_packages[0].is_blocked = False
    records = agent365_observations(data)
    assert {row.code for row in records} == {"DP-SY-17", "DP-SY-18"}
    assert all(row.status == "일부 수집" for row in records)
    assert records[1].metrics["available_to"] == {"allowedForAll": 1}
    path = tmp_path / "partial.xlsx"
    write_workbook(data, [], path)
    sheet = load_workbook(path)["6. 수집 결과"]
    rows = {sheet.cell(row, 2).value: row for row in range(5, 90)}
    for code in ("DP-SY-17", "DP-SY-18"):
        assert sheet.cell(rows[code], 7).value == "일부 수집"
        assert sheet.cell(rows[code], 9).value == "판정 보류"
        assert sheet.cell(rows[code], 13).value is None
    assert data.proposals == []
    assert not {"DP-SY-17", "DP-SY-18"} & load_criteria()["items"].keys()


def test_package_metadata_failure_cannot_be_reported_as_partial_success(tmp_path: Path) -> None:
    source = http()
    source.list_graph.side_effect = AccessError("permission_denied", "HTTP 403")
    data = Agent365Collector(source, NOW).discover()
    records = agent365_observations(data)
    assert all(row.status == "수집 불가" and row.reason == "permission_denied" for row in records)
    assert all(row.metrics["packages"] is None for row in records)
    path = tmp_path / "denied.xlsx"
    write_workbook(data, [], path)
    sheet = load_workbook(path)["6. 수집 결과"]
    rows = {sheet.cell(row, 2).value: row for row in range(5, 90)}
    for code in ("DP-SY-17", "DP-SY-18"):
        assert sheet.cell(rows[code], 8).value == "확인 자료 없음"
