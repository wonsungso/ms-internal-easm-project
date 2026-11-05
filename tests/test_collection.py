from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlparse

import pytest

from wasm_agent.azure import AccessError, EvidenceStore, redact
from wasm_agent.collect import collect
from wasm_agent.collect_foundry import FoundryCollector, list_data
from wasm_agent.collect_inventory import ManualCollector
from wasm_agent.collect_signals import SignalCollector
from wasm_agent.models import Collection, load_criteria, load_settings

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
    with patch("wasm_agent.collect_foundry.list_data", side_effect=[
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
            queries = ("securityresources", "policyresources", "microsoft.insights", "identityType")
            payload = {"data": [] if any(key in body["query"].lower() for key in queries) else rows}
        elif path.endswith("/redTeams/runs"):
            payload = {"value": []}
        elif path.endswith("/config/web"):
            payload = {"properties": {"ipSecurityRestrictions": [], "linuxFxVersion": "PYTHON|3.11"}}
        elif path.endswith("/raiPolicies"):
            payload = {"value": []}
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
        elif path.endswith("/secureScores"):
            payload = {"value": [{"name": "ascScore", "properties": {
                "score": {"current": 10, "max": 20, "percentage": 0.5},
            }}]}
        elif path.endswith("/budgets"):
            payload = {"value": []}
        elif urlparse(url).hostname == "graph.microsoft.com":
            payload = {"value": []}
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
    assert len(data.secure_scores) == 3 and not data.budgets
    assert set(data.facts["budget_complete_subscriptions"]) == set(settings.subscriptions)
    assert "policy_complete_subscriptions" not in data.facts


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

    with patch("wasm_agent.collect_inventory.InventoryCollector.discover", autospec=True, side_effect=inventory), patch(
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
    data = ManualCollector(ROOT / "config" / "manual_agents.csv", NOW).discover([])
    assert data.agents[0].platform == "other"
    assert data.agents[0].field_status["subscription_id"].reason == "not_found"
    invalid = tmp_path / "invalid.csv"
    invalid.write_text("platform,agent_id,agent_name\nfoundry,x,x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="manual/other"):
        ManualCollector(invalid, NOW).discover([])


def test_secure_score_policy_and_budget_collectors_keep_only_evidence_fields() -> None:
    sid = "11111111-1111-4111-8111-111111111111"
    required = "/providers/Microsoft.Authorization/policyDefinitions/model-allowlist"
    criteria = {**load_criteria(), "model_policy_definition_ids": [required.upper()]}
    http = Mock(subscription=sid, last_ref="fixture://ref")
    http.list_arm.side_effect = [
        [{"name": "other"}, {"name": "ascScore", "properties": {"score": {"current": 5, "max": 10, "percentage": 0.5}}}],
        [
            {"id": "a1", "properties": {"policyDefinitionId": required, "enforcementMode": "Default",
                                          "scope": f"/subscriptions/{sid}", "displayName": "Allowed models"}},
            {"id": "a2", "properties": {"policyDefinitionId": "/providers/Microsoft.Authorization/other"}},
        ],
        [{"id": "b1", "properties": {
            "amount": 100, "category": "Cost", "timeGrain": "Monthly",
            "notifications": {
                "on": {"enabled": True, "threshold": 80, "contactEmails": ["owner@example.com"]},
                "off": {"enabled": False, "threshold": 100},
            },
        }}],
    ]
    collector = SignalCollector(http, Collection(collected_at=NOW, subscriptions=[sid]), NOW, criteria, {}, [sid])
    result = Collection(collected_at=NOW)
    collector.secure_score(sid, result)
    collector.policies(sid, result)
    collector.budgets(sid, result)
    assert [(row.current, row.max, row.percentage) for row in result.secure_scores] == [(5, 10, 0.5)]
    assert [row.assignment_id for row in result.policy_assignments] == ["a1"]
    assert result.policy_assignments[0].enforcement_mode == "Default"
    assert (result.budgets[0].enabled_alerts, result.budgets[0].thresholds) == (1, [80.0])
    assert "owner@example.com" not in result.model_dump_json()
    for key in ("secure_score", "policy", "budget"):
        assert result.facts[key + "_complete_subscriptions"] == [sid]


def test_policy_collection_is_skipped_without_customer_policy_ids_and_missing_score_is_reported() -> None:
    sid = "11111111-1111-4111-8111-111111111111"
    http = Mock(subscription=sid, last_ref=None)
    http.list_arm.return_value = []
    collector = SignalCollector(
        http, Collection(collected_at=NOW, subscriptions=[sid]), NOW,
        load_criteria(), {}, [sid],
    )
    result = Collection(collected_at=NOW)
    collector.policies(sid, result)
    http.list_arm.assert_not_called()
    assert "policy_complete_subscriptions" not in result.facts
    with pytest.raises(AccessError) as exc:
        collector.secure_score(sid, result)
    assert exc.value.reason == "feature_unavailable"


def test_entra_collector_reads_graph_keeps_counts_not_people_and_isolates_failures() -> None:
    from wasm_agent.collect_entra import EntraCollector

    identity = "11111111-1111-4111-8111-111111111111"
    graph_sp = "22222222-2222-4222-8222-222222222222"
    write_role, read_role = "33333333-3333-4333-8333-333333333333", "44444444-4444-4444-8444-444444444444"

    def list_graph(url: str) -> list[dict]:
        if "agentIdentityBlueprint" in url:
            return [{"appId": "55555555-5555-4555-8555-555555555555", "displayName": "bp", "createdDateTime":
                     "2026-11-04T01:08:41Z", "tags": ["agentName:a1", "projectName:p1"]}]
        if url.endswith("/servicePrincipals/microsoft.graph.agentIdentity?$top=100"):
            return [{"id": identity, "displayName": "agent", "agentIdentityBlueprintId":
                     "55555555-5555-4555-8555-555555555555", "createdDateTime": "2026-11-04T01:08:44Z",
                     "accountEnabled": True}]
        if "/owners" in url:
            return [{"id": "o1", "accountEnabled": False, "displayName": "Departed Person"}]
        if "/sponsors" in url:
            return []
        if "/appRoleAssignments" in url:
            return [
                {"appRoleId": write_role, "resourceId": graph_sp},
                {"appRoleId": read_role, "resourceId": graph_sp},
                {"appRoleId": "00000000-0000-0000-0000-000000000000", "resourceId": graph_sp},
            ]
        raise AssertionError(url)

    http = Mock(subscription="", last_ref="fixture://graph")
    http.list_graph.side_effect = list_graph
    http.request.return_value = {"appRoles": [
        {"id": write_role, "value": "Mail.ReadWrite.All"}, {"id": read_role, "value": "User.Read.All"},
    ]}
    criteria = load_criteria()
    result = EntraCollector(http, NOW, criteria).discover()
    assert not result.issues
    assert [item.blueprint_id for item in result.entra_blueprints] == ["55555555-5555-4555-8555-555555555555"]
    agent = result.entra_agent_identities[0]
    assert (agent.owner_count, agent.sponsor_count, agent.owners_all_disabled) == (1, 0, True)
    assert agent.app_roles == ["Mail.ReadWrite.All", "User.Read.All"]
    assert agent.overprivileged_roles == ["Mail.ReadWrite.All"]
    assert not result.agent_ca_policies and not result.risky_agents
    assert "Departed Person" not in result.model_dump_json()
    assert all(result.facts[key] for key in (
        "entra_blueprints_complete", "entra_agents_complete",
    ))

    def denied(url: str) -> list[dict]:
        if "agentIdentityBlueprint" in url:
            raise AccessError("permission_denied", "HTTP 403")
        return list_graph(url)

    http.list_graph.side_effect = denied
    partial = EntraCollector(http, NOW, criteria).discover()
    assert [(item.collector, item.reason, item.target) for item in partial.issues] == [
        ("entra_blueprints", "permission_denied", "tenant"),
    ]
    assert partial.issues[0].required_roles == ["AgentIdentityBlueprint.Read.All"]
    assert "entra_blueprints_complete" not in partial.facts and partial.facts["entra_agents_complete"]


def test_entra_graph_requests_use_only_the_graph_host_and_reject_foreign_pagination() -> None:
    import requests

    from wasm_agent.azure import MSGRAPH_SCOPE, ReaderHTTP, trusted_url

    trusted_url("https://graph.microsoft.com/v1.0/servicePrincipals", MSGRAPH_SCOPE)
    with pytest.raises(ValueError):
        trusted_url("https://evil.example/v1.0/servicePrincipals", MSGRAPH_SCOPE)
    http = ReaderHTTP(fake_credential())
    pages = [
        {"value": [{"id": "1"}], "@odata.nextLink": "https://graph.microsoft.com/v1.0/other"},
    ]
    with patch.object(requests.Session, "request", return_value=Mock(
        status_code=200, headers={}, json=Mock(return_value=pages[0]),
    )), pytest.raises(AccessError, match="pagination"):
        http.list_graph("https://graph.microsoft.com/v1.0/servicePrincipals")
    with pytest.raises(ValueError):
        http.request("POST", "https://graph.microsoft.com/v1.0/security/auditLog/queries", MSGRAPH_SCOPE, {})


def test_log_workspace_outside_selected_subscriptions_is_not_queried() -> None:
    sid = "11111111-1111-4111-8111-111111111111"
    foreign = "/subscriptions/99999999-9999-4999-8999-999999999999/resourceGroups/central/providers/Microsoft.OperationalInsights/workspaces/shared"
    base = Collection(collected_at=NOW, subscriptions=[sid])
    http = Mock(subscription=sid, last_ref="fixture://diagnostic-setting")
    http.list_arm.return_value = [{"properties": {
        "workspaceId": foreign, "logs": [{"enabled": True}],
    }}]
    collector = SignalCollector(http, base, NOW, load_criteria(), {}, [sid])
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
    collector = SignalCollector(http, base, NOW, load_criteria(),
                                {"calls": ["Requests"]}, [sid])
    collector.metrics(sid, Collection(collected_at=NOW))
    query = parse_qs(urlparse(http.request.call_args.args[1]).query)
    assert query["timespan"][0].endswith("Z")
    assert "+" not in query["timespan"][0]


def test_all_subscriptions_overrides_config_and_dry_run_never_calls_azure(
    tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    import yaml

    from wasm_agent.cli import main

    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"subscriptions": ["11111111-1111-4111-8111-111111111111"]}))
    with patch("wasm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("no Azure calls")):
        assert main(["collect", "--config", str(config), "--all-subscriptions", "--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["subscriptions"] == "auto-enumerate"


def test_all_subscriptions_and_explicit_scope_cannot_be_combined() -> None:
    from wasm_agent.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["collect", "--all-subscriptions", "--subscriptions", "a"])
    assert exc.value.code == 2


@pytest.mark.parametrize(("extra", "expected"), [
    ([], ["11111111-1111-4111-8111-111111111111"]),
    (["--all-subscriptions"], "auto-enumerate"),
    (["--subscriptions", "22222222-2222-4222-8222-222222222222"], ["22222222-2222-4222-8222-222222222222"]),
])
def test_setup_file_subscriptions_are_the_default_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture, extra: list[str], expected: object,
) -> None:
    from wasm_agent.cli import main

    setup = tmp_path / "setup.json"
    setup.write_text(json.dumps({
        "tenant_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "principal_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "subscription_ids": ["11111111-1111-4111-8111-111111111111"],
    }))
    assert main(["collect", "--setup-file", str(setup), "--dry-run", *extra]) == 0
    assert json.loads(capsys.readouterr().out)["subscriptions"] == expected


def test_auto_enumeration_handles_hundreds_and_filters_tenant_and_state(tmp_path: Path) -> None:
    from uuid import UUID

    settings = load_settings(ROOT / "config" / "config.yaml")
    settings.tenant_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    settings.expected_principal_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    settings.evidence_dir = tmp_path / "evidence"
    ids = [str(UUID(int=index)) for index in range(1, 201)]
    rows = [{"subscriptionId": sid, "tenantId": settings.tenant_id, "state": "Enabled"} for sid in ids]
    rows += [
        {"subscriptionId": str(UUID(int=999)), "tenantId": "another-tenant", "state": "Enabled"},
        {"subscriptionId": str(UUID(int=998)), "tenantId": settings.tenant_id, "state": "Disabled"},
    ]
    http = Mock()
    http.list_arm.return_value = rows
    http.list_graph.return_value = []

    def per_subscription(sid, credential, resolved, store, instant, criteria, tags):
        assert set(resolved.subscriptions) == set(ids)
        return Collection(collected_at=instant, completed_subscriptions=[sid], facts={"inventory_complete": True})

    with patch("wasm_agent.collect.verify_identity"), patch(
        "wasm_agent.collect.ReaderHTTP", return_value=http,
    ), patch("wasm_agent.collect.collect_subscription", side_effect=per_subscription) as worker:
        result = collect(settings, Mock(), datetime.now(UTC))
    assert set(result.subscriptions) == set(ids)
    assert set(result.completed_subscriptions) == set(ids)
    assert worker.call_count == 200
    assert result.facts["inventory_complete"] is True
    assert http.close.call_count == 2
    assert result.facts["entra_blueprints_complete"] and result.facts["entra_agents_complete"]


def test_entra_cannot_be_disabled_by_cli_or_settings() -> None:
    from pydantic import ValidationError

    from wasm_agent.cli import main
    from wasm_agent.models import Settings

    with pytest.raises(SystemExit) as exc:
        main(["collect", "--no-entra", "--dry-run"])
    assert exc.value.code == 2
    with pytest.raises(ValidationError):
        Settings.model_validate({"entra": False})
