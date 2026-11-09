from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest

from wasm_agent.azure import AccessError
from wasm_agent.collect_foundry import FoundryCollector
from wasm_agent.collect_proposals import ProposalCollector
from wasm_agent.collect_signals import SignalCollector
from wasm_agent.models import AgentEvidence, Collection, Settings, load_criteria

NOW = datetime(2026, 11, 9, tzinfo=UTC)
SID = "11111111-1111-4111-8111-111111111111"
ACCOUNT = f"/subscriptions/{SID}/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/ai"
HOST = f"/subscriptions/{SID}/resourceGroups/rg/providers/Microsoft.Web/sites/host"


def source() -> ProposalCollector:
    return ProposalCollector(Mock(last_ref="fixture://api"), Collection(collected_at=NOW), NOW)


@pytest.mark.parametrize("rules,default,expected", [
    ([], None, False),
    ([{"ipAddress": "Any", "action": "Allow"}], None, False),
    ([{"ipAddress": "0.0.0.0/0", "action": "Allow"}], "Deny", False),
    ([{"ipAddress": "10.0.0.0/8", "action": "Allow"}], None, True),
    ([{"ipAddress": "10.0.0.0/8", "action": "Allow"}], "Allow", False),
    ([], "Deny", True),
])
def test_ip_boundaries_use_unmatched_action_and_exclude_allow_all(rules: list, default: str | None, expected: bool) -> None:
    collector = source()
    collector.http.request.return_value = {"properties": {
        "ipSecurityRestrictions": rules, "ipSecurityRestrictionsDefaultAction": default,
    }}
    result = Collection(collected_at=NOW)
    with patch.object(collector, "targets", return_value=([], [{"id": HOST, "type": "microsoft.web/sites"}])):
        collector.network(SID, result)
    row = next(row for row in result.proposal_observations if row.code == "DS-SY-07")
    assert row.values["ip_default_deny"] is expected


def test_private_endpoint_is_approved_not_merely_present() -> None:
    collector = source()
    account = {"id": ACCOUNT, "privateEndpoints": 2, "privateConnections": [
        {"properties": {"privateLinkServiceConnectionState": {"status": "Pending"}}},
        {"properties": {"privateLinkServiceConnectionState": {"status": "Approved"}}},
    ]}
    result = Collection(collected_at=NOW)
    with patch.object(collector, "targets", return_value=([account], [])):
        collector.network(SID, result)
    assert result.proposal_observations[0].values["approved_private_endpoints"] == 1


@pytest.mark.parametrize("group_enabled,group_exists,expected", [
    (True, True, True), (False, True, False), (None, True, None), (True, False, False),
])
def test_alert_groups_are_resolved_against_actual_group_and_receivers(
    group_enabled: bool | None, group_exists: bool, expected: bool | None,
) -> None:
    collector = source()
    group_id = f"/subscriptions/{SID}/resourceGroups/rg/providers/Microsoft.Insights/actionGroups/g"
    rows = [{
        "id": "/alert", "type": "microsoft.insights/metricalerts", "enabled": True,
        "scopes": f'["{ACCOUNT}"]', "actions": f'[{{"actionGroupId":"{group_id}"}}]',
    }]
    if group_exists:
        rows.append({"id": group_id, "type": "microsoft.insights/actiongroups",
                     "enabled": group_enabled, "receivers": {"email": 1, "webhook": 0}})
    result = Collection(collected_at=NOW)
    with patch.object(collector, "graph", return_value=rows), patch.object(
        collector, "targets", return_value=([{"id": ACCOUNT}], []),
    ):
        collector.monitoring(SID, result)
    row = next(row for row in result.proposal_observations if row.values["kind"] == "metricalerts")
    assert row.values["target_ids"] == [ACCOUNT.lower()]
    assert row.values["action_group_resolved"] is expected


def test_policy_resource_uses_worst_state_and_excludes_unrelated_hosts() -> None:
    collector = source()
    rows = [
        {"resourceId": ACCOUNT, "state": state, "definition": f"d{index}"}
        for index, state in enumerate(("Compliant", "NonCompliant", "Compliant"))
    ] + [{"resourceId": HOST, "state": "Compliant", "definition": "d"}]
    result = Collection(collected_at=NOW)
    with patch.object(collector, "graph", return_value=rows), patch.object(
        collector, "targets", return_value=([{"id": ACCOUNT}], []),
    ):
        collector.policy(SID, result)
    resources = [row for row in result.proposal_observations if row.kind == "policy_resource"]
    assert len(resources) == 1 and resources[0].subject == ACCOUNT.lower()
    assert resources[0].values["state"] == "NonCompliant"


def test_resource_graph_paginates_and_rejects_repeated_cursor() -> None:
    collector = source()
    collector.http.request.side_effect = [
        {"data": [{"id": "a"}], "$skipToken": "next"},
        {"data": [{"id": "b"}]},
    ]
    assert collector.graph(SID, "Resources") == [{"id": "a"}, {"id": "b"}]
    assert collector.http.request.call_args.kwargs["body"]["options"]["$skipToken"] == "next"
    collector.http.request.side_effect = [
        {"data": [], "$skipToken": "loop"}, {"data": [], "$skipToken": "loop"},
    ]
    with pytest.raises(AccessError, match="반복"):
        collector.graph(SID, "Resources")


def test_tool_observations_keep_per_mcp_mode_and_safe_https_flags_without_url_secrets() -> None:
    collector = FoundryCollector(Mock(last_ref="fixture://agent"), [], Settings(), NOW)
    record = AgentEvidence(collected_at=NOW, platform="foundry", agent_id="a", agent_name="a",
                           detection_confidence="tag")
    rows = collector.tool_observations({"subscriptionId": SID}, record, [
        {"type": "mcp", "require_approval": "always", "server_url": "https://example.invalid/path?secret=hidden"},
        {"type": "mcp", "require_approval": "never", "server_url": "http://example.invalid"},
        {"type": "mcp", "require_approval": {"always": {"tool_names": ["x"]}},
         "server_url": "https://person:secret@example.invalid"},
    ])
    assert rows[0].values["mcp_approval_modes"] == ["always", "never", "custom"]
    assert rows[1].values["endpoint_https"] == [True, False, False]
    assert "secret" not in str([row.model_dump() for row in rows])


def test_budget_extracts_effective_scope_and_notification_contract_without_contacts() -> None:
    http = Mock(last_ref="fixture://budget")
    http.list_arm.return_value = [{"id": "/budget", "properties": {
        "amount": 100, "category": "Cost", "timeGrain": "Monthly", "filter": {},
        "timePeriod": {"startDate": "2026-11-01T00:00:00Z", "endDate": "2026-12-01T00:00:00Z"},
        "notifications": {
            "actual": {"enabled": True, "thresholdType": "Actual", "threshold": 80,
                       "contactEmails": ["private@example.invalid"]},
            "forecast": {"enabled": True, "thresholdType": "Forecasted", "threshold": 90,
                         "contactRoles": ["Reader"]},
        },
    }}]
    result = Collection(collected_at=NOW)
    SignalCollector(http, Collection(collected_at=NOW), NOW, load_criteria(), {}).budgets(SID, result)
    row = result.budgets[0]
    assert row.actual_alerts == row.forecast_alerts == 1
    assert row.period_start < NOW < row.period_end
    assert row.filters_empty is True and row.notifications_with_receivers is True
    assert "private@example.invalid" not in row.model_dump_json()
