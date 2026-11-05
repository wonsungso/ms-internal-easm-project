from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

from wasm_agent.azure import AccessError
from wasm_agent.collect_proposals import ProposalCollector
from wasm_agent.models import (
    AgentEvidence,
    Budget,
    Collection,
    Issue,
    ModelDeployment,
    ProposalObservation,
    Settings,
    load_conventions,
)
from wasm_agent.proposals import DOMAINS, TITLES, evaluate_proposals

NOW = datetime(2026, 11, 4, tzinfo=UTC)
SID = "11111111-1111-4111-8111-111111111111"
ACCOUNT = f"/subscriptions/{SID}/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/acct"
SITE = f"/subscriptions/{SID}/resourceGroups/rg/providers/Microsoft.Web/sites/host"
TAGS = load_conventions(Settings())


def agent(name: str, platform: str = "foundry", **extra: object) -> AgentEvidence:
    return AgentEvidence(
        collected_at=NOW, subscription_id=SID, platform=platform, agent_id=name, agent_name=name,
        detection_confidence="tag", resource_id=SITE if platform == "langchain" else ACCOUNT, **extra,
    )


def by_code(data: Collection) -> dict:
    return {item.code: item for item in evaluate_proposals(data, TAGS)}


def test_every_proposal_has_collection_details() -> None:
    findings = evaluate_proposals(Collection(collected_at=NOW), TAGS)
    assert [item.code for item in findings] == list(TITLES)


def test_every_proposal_maps_to_one_lifecycle_domain() -> None:
    names = {"1. Demand", "2. Design", "3. Build", "4. Deploy", "5. Operate", "6. Optimize"}
    assert DOMAINS.keys() == TITLES.keys()
    assert all(primary in names and (not secondary or secondary in names) and primary != secondary
               for primary, secondary, _ in DOMAINS.values())
    findings = evaluate_proposals(Collection(collected_at=NOW), TAGS)
    assert {item.code: item.area for item in findings} == {code: v[0] for code, v in DOMAINS.items()}
    assert all("Level은 진단 체크리스트" in item.limit for item in findings)
    assert {item.status for item in findings} <= {"수집됨", "일부 수집", "수집 불가"}


def test_tag_coverage_counts_agents_without_inventing_missing_owners() -> None:
    data = Collection(collected_at=NOW, agents=[
        agent("a", owner="team", tags={"env": "prod", "cost-center": "x"}), agent("b"),
    ])
    metrics = by_code(data)["BI-SY-13"].metrics
    assert metrics == {"agents": 2, "with_owner": 1, "with_sponsor": 0, "with_env": 1, "with_cost_center": 1}


def test_failed_step_is_unavailable_not_zero() -> None:
    data = Collection(collected_at=NOW, issues=[Issue(
        collector="foundry_red_teams", target="p", reason="feature_unavailable", detail="HTTP 404",
    )], facts={"foundry_project_ids": ["p"]})
    finding = by_code(data)["BI-SY-11"]
    assert finding.status == "수집 불가" and finding.reason == "feature_unavailable"
    assert "HTTP 404" in finding.observation


def test_partial_status_keeps_collected_values() -> None:
    data = Collection(collected_at=NOW, proposal_observations=[ProposalObservation(
        code="DS-SY-07", subscription_id=SID, subject=ACCOUNT, kind="ai_account",
        values={"public_network_access": "Enabled", "default_action": "Allow", "private_endpoints": 0},
    )], issues=[Issue(
        collector="proposal_DS-SY-07", target=SID, reason="permission_denied", detail="HTTP 403",
    )])
    finding = by_code(data)["DS-SY-07"]
    assert finding.status == "일부 수집" and finding.metrics["accounts_public"] == 1


def test_safety_budget_and_tools_metrics() -> None:
    deployments = [
        ModelDeployment(
            subscription_id=SID, resource_id=ACCOUNT + "/deployments/a", account_id=ACCOUNT, name="a",
            model="m", version="1", format="OpenAI", rai_policy="strict", version_upgrade_option="NoAutoUpgrade",
        ),
        ModelDeployment(
            subscription_id=SID, resource_id=ACCOUNT + "/deployments/b", account_id=ACCOUNT, name="b",
            model="m", version="1", format="OpenAI", rai_policy="Microsoft.DefaultV2",
        ),
    ]
    data = Collection(
        collected_at=NOW, deployments=deployments, subscriptions=[SID], agents=[agent("a"), agent("b")],
        budgets=[Budget(subscription_id=SID, budget_id="b", enabled_alerts=2, forecast_alerts=1)],
        facts={"budget_complete_subscriptions": [SID]},
        proposal_observations=[
            ProposalObservation(
                code="BI-SY-10", subscription_id=SID, subject=ACCOUNT, kind="ai_account",
                values={"policies": 2, "custom_policies": 1, "custom_enabled_filters": 1,
                        "custom_policy_names": ["strict"]},
            ),
            ProposalObservation(
                code="DS-SY-08", subscription_id=SID, subject="a", kind="agent_tools",
                values={"tool_types": ["mcp"], "mcp_approval": ["always"]},
            ),
            ProposalObservation(
                code="DS-SY-09", subscription_id=SID, subject="a", kind="tool_endpoints",
                values={"hosts": ["learn.microsoft.com"]},
            ),
        ],
    )
    result = by_code(data)
    assert result["BI-SY-10"].metrics["with_policy"] == 2 and result["BI-SY-10"].metrics["with_custom_policy"] == 1
    assert result["OT-SY-21"].metrics["with_forecast_alert"] == 1
    assert result["DS-SY-08"].metrics["mcp_approval"] == {"always": 1}
    assert result["DS-SY-09"].metrics["hosts"] == ["learn.microsoft.com"]
    assert result["BI-SY-12"].metrics["version_upgrade_option"] == {"NoAutoUpgrade": 1, "unknown": 1}


def collector(rows: dict[str, list[dict]], assignments: list[dict] | None = None) -> ProposalCollector:
    http = Mock(last_ref="fixture://ref", subscription=SID)

    def request(method: str, url: str, audience: str = "", body: dict | None = None) -> dict:
        if method == "POST":
            query = body["query"]
            key = next(name for name in rows if name.lower() in query.lower())
            return {"data": rows[key]}
        if url.endswith("/config/web?api-version=2024-04-01"):
            return {"properties": {"ipSecurityRestrictions": [{"name": "x"}], "linuxFxVersion": "PYTHON|3.11"}}
        raise AssertionError(url)

    def list_arm(url: str) -> list[dict]:
        if "roleAssignments" in url:
            return assignments or []
        if "raiPolicies" in url:
            return [
                {"name": "Microsoft.DefaultV2", "properties": {"type": "SystemManaged"}},
                {"name": "strict", "properties": {"type": "UserManaged", "contentFilters": [{"enabled": True}]}},
            ]
        raise AssertionError(url)

    http.request.side_effect = request
    http.list_arm.side_effect = list_arm
    data = Collection(collected_at=NOW, agents=[agent("host", "langchain")])
    return ProposalCollector(http, data, NOW)


def properties_rows() -> list[dict]:
    return [
        {"id": ACCOUNT, "name": "acct", "type": "microsoft.cognitiveservices/accounts", "kind": "AIServices",
         "identityType": "SystemAssigned", "principalId": "p1", "userPrincipals": [], "publicNetworkAccess": "Enabled",
         "defaultAction": "", "privateEndpoints": 0, "disableLocalAuth": 1},
        {"id": SITE, "name": "host", "type": "microsoft.web/sites", "kind": "app,linux",
         "identityType": "SystemAssigned, UserAssigned", "principalId": "p2", "userPrincipals": ["p3"],
         "publicNetworkAccess": "Enabled", "httpsOnly": 1, "vnetSubnet": ""},
        {"id": SITE + "-other", "name": "other", "type": "microsoft.web/sites", "kind": "app",
         "identityType": "None", "principalId": ""},
    ]


def test_collector_records_identity_network_safety_and_policy_facts() -> None:
    owner = "/providers/Microsoft.Authorization/roleDefinitions/8e3af657-a8ff-443c-a75c-2fe8c4bcb635"
    reader = "/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7"
    result = collector(
        {
            "identity": properties_rows(), "microsoft.insights": [
                {"id": "/a/ag", "type": "microsoft.insights/actiongroups", "receivers": {"webhook": 1, "email": 0}},
                {"id": "/a/al", "type": "microsoft.insights/metricalerts", "enabled": 1,
                 "scopes": f'["{ACCOUNT}"]', "actions": '[{"actionGroupId": "/x/actionGroups/ag"}]'},
            ],
            "policyresources": [
                {"resourceId": ACCOUNT, "state": "NonCompliant", "definition": "d1"},
                {"resourceId": SITE, "state": "Compliant", "definition": "d1"},
            ],
        },
        assignments=[
            {"properties": {"principalId": "p3", "roleDefinitionId": owner, "scope": f"/subscriptions/{SID}"}},
            {"properties": {"principalId": "p1", "roleDefinitionId": reader, "scope": ACCOUNT}},
            {"properties": {"principalId": "unrelated", "roleDefinitionId": owner, "scope": f"/subscriptions/{SID}"}},
        ],
    ).discover([SID])
    observed = {(item.code, item.kind): item.values for item in result.proposal_observations}
    host = next(
        item.values for item in result.proposal_observations
        if item.code == "OE-SY-17" and item.subject == SITE
    )
    assert host["privileged_assignments"] == 1 and host["subscription_scope_assignments"] == 1
    assert host["principal_count"] == 2
    assert not any(item.subject.endswith("-other") for item in result.proposal_observations)
    assert observed[("BI-SY-10", "ai_account")]["custom_policy_names"] == ["strict"]
    network = [item.values for item in result.proposal_observations if item.code == "DS-SY-07"]
    assert {"public_network_access": "Enabled", "default_action": None, "private_endpoints": 0} in network
    assert any(item["ip_restrictions"] == 1 and item["https_only"] is True for item in network if "https_only" in item)
    monitoring = [item.values for item in result.proposal_observations if item.code == "OE-SY-18"]
    assert {"kind": "actiongroups", "receivers": {"webhook": 1}} in monitoring
    assert any(item.get("targets_ai") and item.get("has_action_group") for item in monitoring)
    states = {item.values["state"]: item.values["resources"] for item in result.proposal_observations
              if item.code == "BI-SY-14"}
    assert states == {"Compliant": 1, "NonCompliant": 1}


def test_collector_isolates_a_failed_step() -> None:
    gathered = collector({"identity": properties_rows(), "microsoft.insights": [], "policyresources": []})

    def broken(*args: object, **kwargs: object) -> list[dict]:
        raise AccessError("permission_denied", "HTTP 403")

    gathered.http.list_arm.side_effect = broken
    result = gathered.discover([SID])
    assert {item.collector for item in result.issues} == {"proposal_OE-SY-17", "proposal_BI-SY-10"}
    assert "DS-SY-07" in {item.code for item in result.proposal_observations}
    assert sorted(result.facts["proposal_incomplete"]) == ["BI-SY-10", "OE-SY-17"]
