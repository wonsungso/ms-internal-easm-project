from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlparse

import pytest

from wasm_agent.collect import collect
from wasm_agent.collectors.foundry import FoundryCollector, list_data
from wasm_agent.collectors.manual import ManualCollector
from wasm_agent.collectors.signals import SignalCollector
from wasm_agent.models import Collection
from wasm_agent.utils.azure import AccessError
from wasm_agent.utils.evidence import EvidenceStore, redact
from wasm_agent.utils.settings import load_settings, load_yaml

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 11, 3, 1, tzinfo=UTC)
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PRINCIPAL = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def fake_credential() -> Mock:
    claims = base64.urlsafe_b64encode(json.dumps({"tid": TENANT, "oid": PRINCIPAL}).encode()).decode().rstrip("=")
    credential = Mock()
    credential.get_token.return_value.token = "header." + claims + ".signature"
    return credential


def test_redaction_preserves_numeric_usage_and_masks_sensitive_content(tmp_path: Path) -> None:
    payload = {
        "tokens": 42, "input_tokens": 12, "api_key": "do-not-store",
        "connectionString": "do-not-store", "owner": "person@example.invalid",
        "definition": {"instructions": "do-not-store"},
    }
    clean = redact(payload)
    assert clean["tokens"] == 42 and clean["input_tokens"] == 12
    assert clean["owner"].startswith("identity-")
    store = EvidenceStore(tmp_path, NOW)
    path = store.save("fixture", payload, "subscription")
    assert "do-not-store" not in Path(path).read_text(encoding="utf-8")
    assert "person@example.invalid" not in Path(path).read_text(encoding="utf-8")


def test_foundry_data_pages_reject_cycles() -> None:
    http = Mock()
    http.request.return_value = {"data": [{"id": "a"}], "has_more": True, "last_id": "a"}
    with pytest.raises(AccessError, match="반복"):
        list_data(http, "https://fixture.services.ai.azure.com/api/projects/test", "/agents")


@pytest.mark.parametrize("tools", [[], None])
@pytest.mark.parametrize("counts", [None, {"passed": 2, "failed": 1, "errored": 0, "total": 3}])
def test_foundry_versions_do_not_count_as_multiple_agents(
    tmp_path: Path, tools: list | None, counts: dict | None,
) -> None:
    fixtures = json.loads((ROOT / "tests" / "fixtures" / "api_responses.json").read_text(encoding="utf-8"))
    settings = load_settings(ROOT / "config" / "config.yaml")
    settings.tenant_id = TENANT
    fixtures["foundry_versions"]["data"][0]["definition"]["tools"] = tools
    sid = fixtures["subscriptions"][0]["subscription_id"]
    http = Mock(subscription=sid, last_ref="fixture://api")
    http.list_arm.side_effect = [
        fixtures["model_deployments"]["value"],
        [{"id": "/fixture/account/projects/test"}],
    ]
    http.request.return_value = {
        "properties": {"endpoints": {"AI Foundry API": "https://fixture.services.ai.azure.com/api/projects/test"}},
    }
    with patch("wasm_agent.collectors.foundry.list_data", side_effect=[
        fixtures["foundry_agents"]["data"], fixtures["foundry_versions"]["data"],
        [{"id": "eval-fixture"}],
        [{"id": "run-fixture", "status": "completed", "result_counts": counts,
          "metadata": {"agent_id": "fixture-foundry", "agent_version": "2"}}],
    ]):
        data = FoundryCollector(http, fixtures["subscriptions"][0]["resources"], settings, NOW).discover([sid])
    assert len(data.agents) == 1
    assert data.agents[0].agent_id == "fixture-foundry"
    assert data.agents[0].agent_version == "2"
    assert data.agents[0].created_at is not None
    assert data.agents[0].deployed_at is None
    assert data.agents[0].guardrail_applied is None
    assert data.agents[0].tools == tools
    assert data.agents[0].field_status["deployed_at"].reason == "not_found"
    assert data.evaluations[0].passed_items == (2 if counts else None)
    assert data.evaluations[0].failed_items == (1 if counts else None)
    assert data.evaluations[0].errored_items == (0 if counts else None)
    assert data.evaluations[0].total_items == (3 if counts else None)
    assert data.evaluations[0].completed_at is None


def test_three_subscription_pipeline_and_cross_subscription_model_link(tmp_path: Path) -> None:
    fixture = json.loads((ROOT / "tests" / "fixtures" / "api_responses.json").read_text(encoding="utf-8"))
    subs = fixture["subscriptions"]
    settings = load_settings(ROOT / "config" / "config.yaml")
    settings.tenant_id, settings.expected_principal_id = TENANT, PRINCIPAL
    settings.subscriptions = [entry["subscription_id"] for entry in subs]
    settings.evidence_dir = tmp_path / "evidence"

    def request(method: str, url: str, **kwargs: object) -> Mock:
        body = kwargs.get("json") or {}
        path = urlparse(url).path
        if path.endswith("/permissions"):
            payload = {"value": [{"actions": ["*/read"], "dataActions": []}]}
        elif "Microsoft.ResourceGraph/resources" in path:
            sid = body["subscriptions"][0]
            rows = next(entry["resources"] for entry in subs if entry["subscription_id"] == sid)
            payload = {"data": [] if "securityresources" in body["query"] else rows}
        elif path == "/fixture/account/deployments":
            payload = fixture["model_deployments"]
        elif path == "/fixture/account/projects":
            payload = {"value": [{"id": "/fixture/account/projects/test"}]}
        elif path == "/fixture/account/projects/test":
            payload = {"properties": {"endpoints": {"AI Foundry API": "https://fixture.services.ai.azure.com/api/projects/test"}}}
        elif path.endswith("/agents"):
            payload = fixture["foundry_agents"]
        elif path.endswith("/versions"):
            payload = fixture["foundry_versions"]
        elif path.endswith("/evals"):
            payload = {"data": [], "has_more": False}
        elif path.endswith("/query") and "CostManagement" in path:
            sid = path.split("/")[2]
            resource = "/fixture/account" if sid == settings.subscriptions[0] else (
                "/fixture/plan-2" if sid == settings.subscriptions[1] else "/fixture/plan-3"
            )
            payload = {"properties": {**fixture["cost_management"]["properties"],
                                     "rows": [[2.5, resource, 20261101, "USD"]]}}
        elif path.endswith("/diagnosticSettings"):
            payload = {"value": []}
        elif path.endswith("/metricDefinitions"):
            payload = fixture["monitor_definitions"]
        elif path.endswith("/metrics"):
            payload = fixture["monitor_metrics"]
        else:
            raise AssertionError(f"Unmocked API: {method} {path}")
        return Mock(status_code=200, headers={}, json=Mock(return_value=payload))

    with patch("requests.Session.request", side_effect=request):
        data = collect(settings, fake_credential(), NOW)
    assert len(data.agents) == 3
    assert len(data.completed_subscriptions) == 3
    assert {agent.platform for agent in data.agents} == {"foundry", "langchain"}
    assert all(agent.model == "gpt-4o-mini" for agent in data.agents)
    assert all(agent.model_version == "2024-07-18" for agent in data.agents)
    assert len(data.costs) == 3


def test_subscription_failure_preserves_other_subscription_records(tmp_path: Path) -> None:
    settings = load_settings(ROOT / "config" / "config.yaml")
    fixture = Collection.model_validate_json((ROOT / "tests" / "fixtures" / "three_subscriptions.json").read_text())
    settings.tenant_id, settings.expected_principal_id = TENANT, PRINCIPAL
    settings.subscriptions = fixture.subscriptions
    settings.evidence_dir = tmp_path

    def inventory(instance: object, subscriptions: list[str]) -> Collection:
        sid = subscriptions[0]
        if sid == fixture.subscriptions[1]:
            raise AccessError("permission_denied", "fixture denial")
        return Collection(
            collected_at=NOW, completed_subscriptions=[sid],
            agents=[agent.model_copy(deep=True) for agent in fixture.agents if agent.subscription_id == sid],
            facts={"inventory_complete": True},
        )

    with patch("wasm_agent.collectors.inventory.InventoryCollector.discover", autospec=True, side_effect=inventory), patch(
        "wasm_agent.collect.FoundryCollector.discover", return_value=Collection(collected_at=NOW),
    ), patch("wasm_agent.collect.LangChainCollector.discover", return_value=Collection(collected_at=NOW)), patch(
        "wasm_agent.collect.SignalCollector.discover", return_value=Collection(collected_at=NOW),
    ):
        data = collect(settings, fake_credential(), NOW)
    assert len(data.agents) == 2
    assert len(data.completed_subscriptions) == 2
    assert data.facts["inventory_complete"] is False
    assert any(item.reason == "permission_denied" for item in data.issues)


def test_manual_template_and_invalid_input(tmp_path: Path) -> None:
    data = ManualCollector(ROOT / "templates" / "manual_agents.csv", NOW).discover([])
    assert data.agents[0].platform == "other"
    assert data.agents[0].field_status["subscription_id"].reason == "not_found"
    invalid = tmp_path / "invalid.csv"
    invalid.write_text("platform,agent_id,agent_name\nfoundry,x,x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="manual/other"):
        ManualCollector(invalid, NOW).discover([])


def test_log_workspace_outside_selected_subscriptions_is_not_queried() -> None:
    sid = "11111111-1111-4111-8111-111111111111"
    foreign = "/subscriptions/99999999-9999-4999-8999-999999999999/resourceGroups/central/providers/Microsoft.OperationalInsights/workspaces/shared"
    base = Collection(collected_at=NOW, subscriptions=[sid])
    http = Mock(subscription=sid, last_ref="fixture://diagnostic-setting")
    http.list_arm.return_value = [{"properties": {
        "workspaceId": foreign, "logs": [{"enabled": True}],
    }}]
    collector = SignalCollector(http, base, NOW, load_yaml(ROOT / "config" / "criteria.yaml"), {}, [sid])
    result = Collection(collected_at=NOW)
    collector.logs(sid, result)
    http.request.assert_not_called()
    assert result.logs[0].retention_days is None
    assert result.issues[0].reason == "permission_denied"
    assert "선택 구독 범위 밖" in result.issues[0].detail


def test_metrics_use_canonical_utc_not_plus_timezone() -> None:
    from urllib.parse import parse_qs

    sid = "11111111-1111-4111-8111-111111111111"
    base = Collection(collected_at=NOW, subscriptions=[sid], resources=[{
        "id": "/fixture/account", "subscriptionId": sid, "type": "Microsoft.CognitiveServices/accounts",
        "kind": "AIServices",
    }])
    http = Mock(subscription=sid, last_ref="fixture://metric")
    http.list_arm.return_value = [{"name": {"value": "Requests"}}]
    http.request.return_value = {"value": []}
    collector = SignalCollector(http, base, NOW, load_yaml(ROOT / "config" / "criteria.yaml"),
                                {"calls": ["Requests"]}, [sid])
    collector.metrics(sid, Collection(collected_at=NOW))
    query = parse_qs(urlparse(http.request.call_args.args[1]).query)
    assert query["timespan"][0].endswith("Z")
    assert "+" not in query["timespan"][0]
