from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import cache

import pytest

from wasm_agent.api_grading import Measurement, measurements, targets
from wasm_agent.evaluation import evaluate, matches
from wasm_agent.models import (
    DEFAULT_TAGS,
    AgentEvidence,
    Budget,
    Collection,
    EntraAgentIdentity,
    EntraBlueprint,
    EvaluationRun,
    Issue,
    LogSetting,
    ModelDeployment,
    ProposalObservation,
)
from wasm_agent.models import (
    load_criteria as read_criteria,
)


@cache
def load_criteria() -> dict:
    return read_criteria()


NOW = datetime(2026, 11, 9, tzinfo=UTC)
SID = "11111111-1111-4111-8111-111111111111"
ACCOUNT = f"/subscriptions/{SID}/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/ai"
PROJECT = ACCOUNT + "/projects/p"
BLUEPRINT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CODES = list(load_criteria()["items"])


def grade(data: Collection, criteria: dict | None = None, facts: dict | None = None) -> dict:
    return {row.se_code: row for row in evaluate(data, criteria or load_criteria(), {}, DEFAULT_TAGS, facts)}


def test_custom_host_uses_same_grading_scope_as_langchain_host(data: Collection) -> None:
    data.agents[0].platform = "langchain"
    baseline = {code: row.model_dump() for code, row in grade(data).items()}
    baseline_targets = targets(data)
    baseline_measurements = measurements(data, load_criteria(), DEFAULT_TAGS)
    data.agents[0].platform = "custom"
    assert targets(data) == baseline_targets
    assert data.agents[0].resource_id.lower() in targets(data)
    assert measurements(data, load_criteria(), DEFAULT_TAGS) == baseline_measurements
    assert {code: row.model_dump() for code, row in grade(data).items()} == baseline


@pytest.fixture
def data() -> Collection:
    criteria = load_criteria()
    value = Collection(
        collected_at=NOW, subscriptions=[SID],
        resources=[{"id": ACCOUNT, "subscriptionId": SID, "type": "microsoft.cognitiveservices/accounts",
                    "kind": "AIServices", "location": "westus2"}],
        agents=[AgentEvidence(
            collected_at=NOW, platform="foundry", agent_id="agent", agent_name="agent", agent_version="1",
            subscription_id=SID, resource_id=PROJECT, model_resource_id=ACCOUNT, detection_confidence="tag",
            tags={"owner": "team", "sponsor": "team", "env": "prod", "cost-center": "engineering"},
        )],
        deployments=[ModelDeployment(
            subscription_id=SID, resource_id=ACCOUNT + "/deployments/m", account_id=ACCOUNT, name="m",
            model="gpt", version="1", format="OpenAI", version_upgrade_option="NoAutoUpgrade", rai_policy="safe",
        )],
        evaluations=[EvaluationRun(subscription_id=SID, project_id=PROJECT, run_id="run", status="completed")],
        entra_blueprints=[EntraBlueprint(blueprint_id=BLUEPRINT, tags=[
            f"subscriptionId:{SID}", "accountName:ai", "projectName:p", "agentName:agent",
        ])],
        entra_agent_identities=[EntraAgentIdentity(
            identity_id="identity", blueprint_id=BLUEPRINT, account_enabled=True,
            owner_count=1, sponsor_count=1, owners_all_disabled=False,
        )],
        logs=[LogSetting(subscription_id=SID, resource_id=ACCOUNT, enabled=True,
                         workspace_id="/workspace", retention_days=90)],
        budgets=[Budget(
            subscription_id=SID, budget_id="/budget", amount=100, category="Cost", time_grain="Monthly",
            actual_alerts=1, forecast_alerts=1, enabled_alerts=2, thresholds=[80, 90],
            period_start=NOW - timedelta(days=1), period_end=NOW + timedelta(days=30),
            filters_empty=True, notifications_with_receivers=True,
        )],
        facts={
            "inventory_complete": True, "agent_inventory_complete": True,
            "deployment_inventory_complete": True, "entra_blueprints_complete": True,
            "entra_agents_complete": True, "evaluation_complete_projects": [PROJECT], "foundry_project_ids": [PROJECT],
            "resource_metrics": [{"resource_id": ACCOUNT, "metrics": [{"timeseries": [{"data": [{"total": 0}]}]}]}],
        },
    )
    from wasm_agent.models import CostRecord, SecurityRecommendation

    value.costs = [CostRecord(subscription_id=SID, resource_id=ACCOUNT, amount=10, currency="USD", usage_date="20261109")]
    value.security = [SecurityRecommendation(subscription_id=SID, resource_id=ACCOUNT,
                                            assessment_id="/assessment", severity="Low", status="Healthy")]
    entries = [
        ("DS-SY-07", "ai_account", {"public_network_access": "Disabled", "approved_private_endpoints": 1}),
        ("DS-SY-08", "agent_tools", {"mcp_approval_modes": ["always"]}),
        ("DS-SY-09", "tool_endpoints", {"endpoint_https": [True]}),
        ("BI-SY-13", "ai_account", {"enabled_policy_names": ["safe"], "policy_filter_enabled": {"safe": True}}),
        ("BI-SY-16", "policy_resource", {"state": "Compliant"}),
        ("OE-SY-23", "ai_account", {
            "identity_type": "SystemAssigned", "principal_count": 1,
            "privileged_assignments": 0, "local_auth_disabled": True,
        }),
        ("OE-SY-24", "metricalerts", {
            "kind": "metricalerts", "targets_ai": True, "target_ids": [ACCOUNT],
            "enabled": True, "action_group_resolved": True,
        }),
    ]
    value.proposal_observations = [
        ProposalObservation(code=code, subscription_id=SID, subject=ACCOUNT, kind=kind,
                            values=fields, evidence_refs=["fixture://api"])
        for code, kind, fields in entries
    ]
    for config in criteria["items"].values():
        for key in config.get("complete_subscriptions", []):
            value.facts[key] = [SID]
    return value


def test_complete_api_snapshot_grades_all_22_controls_without_qualitative_inputs(data: Collection) -> None:
    rows = grade(data)
    assert len(rows) == 22
    assert all(row.level == "L5" and row.metric_value == 1 for row in rows.values())
    assert all(row.reason is None and row.assessment_basis == "criteria" for row in rows.values())
    assert data.facts["grading_profile"] == "api_configuration_v1"


@pytest.mark.parametrize("reason", ["permission_denied", "license_missing", "error"])
def test_agent365_crosscheck_failures_do_not_change_primary_grades(data: Collection, reason: str) -> None:
    from wasm_agent.collect_agent365 import crosscheck_agent365
    from wasm_agent.models import Issue

    before = {code: row.model_dump() for code, row in grade(data).items()}
    data.issues.append(Issue(
        collector="agent365_registry", target="tenant", reason=reason, detail="crosscheck unavailable",
    ))
    data.facts["agent365_registry_complete"] = False
    data.agent365_crosschecks = crosscheck_agent365(data, load_criteria())
    assert {code: row.model_dump() for code, row in grade(data).items()} == before


def test_administrator_evidence_never_changes_primary_grades(data: Collection) -> None:
    from wasm_agent.collect_admin_evidence import admin_observations
    from wasm_agent.models import AdminReadResult

    before = {code: row.model_dump() for code, row in grade(data).items()}
    data.admin_evidence = [AdminReadResult(
        source="purview.activity_explorer", command="Export-ActivityExplorerData",
        module_version="3.9.0", scope="tenant activity aggregates, not Agent exposure",
        completed=True, observed_at=data.collected_at, object_count=0, detail="completed empty query",
    )]
    data.proposals.extend(admin_observations(data))
    assert {code: row.model_dump() for code, row in grade(data).items()} == before


@pytest.mark.parametrize("good,level", [(0, "L1"), (1, "L2"), (8, "L3"), (9, "L4"), (10, "L5")])
def test_real_api_field_combinations_reach_every_level_for_all22_controls(
    data: Collection, good: int, level: str,
) -> None:
    from copy import deepcopy

    snapshot = Collection(collected_at=NOW)
    for index in range(10):
        complete = index < good
        sid = f"{index + 1:08}-1111-4111-8111-111111111111"
        account = f"/subscriptions/{sid}/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/ai{index}"
        project = account + "/projects/p"
        blueprint = f"blueprint-{index}"
        snapshot.subscriptions.append(sid)
        snapshot.resources.append({
            "id": account, "subscriptionId": sid, "type": "microsoft.cognitiveservices/accounts",
            "kind": "AIServices", "location": "westus2",
        })
        agent = data.agents[0].model_copy(deep=True, update={
            "subscription_id": sid, "resource_id": project, "model_resource_id": account,
            "agent_id": f"agent-{index}", "agent_name": f"agent-{index}",
            "agent_version": "1" if complete else "",
        })
        if not complete:
            agent.tags.pop("cost-center")
        snapshot.agents.append(agent)
        snapshot.entra_blueprints.append(EntraBlueprint(blueprint_id=blueprint, tags=[
            f"subscriptionId:{sid}", f"accountName:ai{index}", "projectName:p", f"agentName:agent-{index}",
        ]))
        snapshot.entra_agent_identities.append(data.entra_agent_identities[0].model_copy(update={
            "identity_id": f"identity-{index}", "blueprint_id": blueprint if complete else "not-collected",
            "owner_count": 1 if complete else 0,
            "app_roles": [] if complete else ["Data.Write.All"],
            "overprivileged_roles": [] if complete else ["Data.Write.All"],
        }))
        snapshot.deployments.append(data.deployments[0].model_copy(update={
            "subscription_id": sid, "account_id": account, "resource_id": account + "/deployments/m",
            "version": "1" if complete else "", "rai_policy": "safe" if complete else "missing",
        }))
        snapshot.evaluations.append(data.evaluations[0].model_copy(update={
            "subscription_id": sid, "project_id": project, "run_id": f"run-{index}",
            "status": "completed" if complete else "failed",
        }))
        snapshot.security.append(data.security[0].model_copy(update={
            "subscription_id": sid, "resource_id": account, "assessment_id": f"/assessment/{index}",
            "status": "Healthy" if complete else "Unhealthy",
        }))
        snapshot.logs.append(data.logs[0].model_copy(update={
            "subscription_id": sid, "resource_id": account, "enabled": complete,
        }))
        snapshot.budgets.append(data.budgets[0].model_copy(update={
            "subscription_id": sid, "budget_id": f"/budget/{index}", "forecast_alerts": 1 if complete else 0,
        }))
        snapshot.costs.append(data.costs[0].model_copy(update={
            "subscription_id": sid, "resource_id": account if complete else f"/shared-workspace/{index}",
        }))
        for original in data.proposal_observations:
            row = original.model_copy(deep=True, update={"subscription_id": sid, "subject": account})
            field_values = deepcopy(row.values)
            if row.code == "DS-SY-07":
                field_values["public_network_access"] = "Disabled" if complete else "Enabled"
            elif row.code == "DS-SY-08":
                field_values["mcp_approval_modes"] = ["always" if complete else "never"]
            elif row.code == "DS-SY-09":
                field_values["endpoint_https"] = [complete]
            elif row.code == "BI-SY-16":
                field_values["state"] = "Compliant" if complete else "NonCompliant"
            elif row.code == "OE-SY-23":
                field_values["principal_count"] = 1 if complete else 0
            elif row.code == "OE-SY-24":
                field_values.update({"enabled": complete, "target_ids": [account], "action_group_resolved": complete})
            row.values = field_values
            snapshot.proposal_observations.append(row)
    snapshot.facts = {
        "inventory_complete": True, "agent_inventory_complete": True, "deployment_inventory_complete": True,
        "entra_blueprints_complete": True, "entra_agents_complete": True,
        "foundry_project_ids": [run.project_id for run in snapshot.evaluations],
        "evaluation_complete_projects": [run.project_id for run in snapshot.evaluations],
        "resource_metrics": [
            {"resource_id": row["id"], "metrics": [{"timeseries": [{"data": [{"total": 0}]}]}]
             if index < good else []}
            for index, row in enumerate(snapshot.resources)
        ],
    }
    for config in load_criteria()["items"].values():
        for key in config["complete_subscriptions"]:
            snapshot.facts[key] = snapshot.subscriptions
    rows = grade(snapshot)
    assert len(rows) == 22
    for code, row in rows.items():
        assert row.metric_value == pytest.approx(good / 10), (code, row.rationale)
        assert row.level == level, (code, row.rationale)


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("ratio,level", [
    (0, "L1"), (0.01, "L2"), (0.7999, "L2"), (0.8, "L3"),
    (0.8999, "L3"), (0.9, "L4"), (0.9999, "L4"), (1, "L5"),
])
def test_exact_thresholds_for_every_control(
    data: Collection, code: str, ratio: float, level: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wasm_agent import evaluation

    original = measurements(data, load_criteria(), DEFAULT_TAGS)
    original[code] = Measurement(total=10000, compliant=ratio * 10000, detail="Boundary API measurement")
    monkeypatch.setattr(evaluation, "measurements", lambda *args: original)
    row = grade(data)[code]
    assert row.level == level and row.metric_value == pytest.approx(ratio)
    assert row.level_criterion == load_criteria()["items"][code]["levels"][level]


@pytest.mark.parametrize("code", CODES)
def test_related_collection_error_prevents_any_level(data: Collection, code: str) -> None:
    collector = load_criteria()["items"][code]["collectors"][0]
    data.issues.append(Issue(collector=collector, target="fixture", reason="permission_denied", detail="Denied API"))
    row = grade(data)[code]
    assert row.level == "N/A" and row.metric_value is None and row.reason == "permission_denied"


@pytest.mark.parametrize("code", CODES)
def test_empty_denominator_is_not_success_or_l1(
    data: Collection, code: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wasm_agent import evaluation

    original = measurements(data, load_criteria(), DEFAULT_TAGS)
    original[code] = Measurement(unavailable="대상 없음")
    monkeypatch.setattr(evaluation, "measurements", lambda *args: original)
    row = grade(data)[code]
    assert row.level == "N/A" and row.metric_value is None and row.reason == "not_found"


@pytest.mark.parametrize("code", CODES)
def test_completeness_markers_cannot_be_omitted(data: Collection, code: str) -> None:
    config = load_criteria()["items"][code]
    data.facts["inventory_complete"] = False
    data.facts["entra_agents_complete"] = data.facts["entra_blueprints_complete"] = False
    assert grade(data)[code].level == "N/A"
    if config.get("complete_subscriptions"):
        data.facts["inventory_complete"] = True
        data.facts[config["complete_subscriptions"][0]] = []
        assert grade(data)[code].level == "N/A"


def test_ten_blueprints_and_ten_linked_identities_receive_level5(data: Collection) -> None:
    data.entra_blueprints = [EntraBlueprint(blueprint_id=f"blueprint-{i}") for i in range(10)]
    data.entra_agent_identities = [EntraAgentIdentity(identity_id=f"id-{i}", blueprint_id=f"blueprint-{i}")
                                    for i in range(10)]
    row = grade(data)["DS-SY-05"]
    assert row.level == "L5" and row.metric_value == 1
    data.entra_agent_identities[0].blueprint_id = "outside"
    assert grade(data)["DS-SY-05"].level == "L4"
    data.entra_agent_identities[1].blueprint_id = None
    assert grade(data)["DS-SY-05"].level == "L3"


@pytest.mark.parametrize("field,value", [
    ("period_end", NOW - timedelta(seconds=1)), ("period_start", NOW + timedelta(days=1)),
    ("filters_empty", False), ("amount", 0), ("actual_alerts", 0),
    ("forecast_alerts", 0), ("notifications_with_receivers", False),
])
def test_budget_must_be_effective_and_include_both_notification_types(
    data: Collection, field: str, value: object,
) -> None:
    setattr(data.budgets[0], field, value)
    row = grade(data)["OT-SY-31"]
    assert row.level == "L1" and row.metric_value == 0


def test_missing_budget_fields_are_unknown_not_zero(data: Collection) -> None:
    data.budgets[0].period_end = None
    assert grade(data)["OT-SY-31"].level == "N/A"
    data.budgets = []
    assert grade(data)["OT-SY-31"].level == "L1"


def test_model_unknown_update_option_does_not_count_as_configured(data: Collection) -> None:
    data.deployments[0].version_upgrade_option = None
    assert grade(data)["DS-SY-06"].level == "N/A"
    data.deployments[0].version_upgrade_option = "unrecognized"
    assert grade(data)["DS-SY-06"].level == "L1"


def test_mcp_never_custom_and_missing_modes_are_not_always(data: Collection) -> None:
    tool = next(row for row in data.proposal_observations if row.code == "DS-SY-08")
    tool.values["mcp_approval_modes"] = ["never"]
    assert grade(data)["DS-SY-08"].level == "L1"
    tool.values["mcp_approval_modes"] = ["custom"]
    assert grade(data)["DS-SY-08"].level == "L1"
    tool.values["mcp_approval_modes"] = [None]
    assert grade(data)["DS-SY-08"].level == "N/A"
    tool.values["mcp_approval_modes"] = []
    assert grade(data)["DS-SY-08"].level == "N/A"


def test_cost_shared_resources_are_not_attributed_twice(data: Collection) -> None:
    data.agents.append(data.agents[0].model_copy(update={"agent_id": "other"}))
    assert grade(data)["OT-SY-29"].metric_value == 0
    data.costs[0].amount = 0
    assert grade(data)["OT-SY-29"].level == "N/A"
    data.costs[0].amount = -1
    assert grade(data)["OT-SY-29"].level == "N/A"


def test_not_applicable_recommendations_and_unknown_fields_do_not_mean_healthy(data: Collection) -> None:
    data.security[0].status = "NotApplicable"
    assert grade(data)["BI-SY-12"].level == "N/A"
    data.security[0].status = None
    assert grade(data)["BI-SY-12"].level == "N/A"


def test_missing_filter_configuration_is_unknown_not_disabled(data: Collection) -> None:
    row = next(row for row in data.proposal_observations if row.code == "BI-SY-13")
    row.values["policy_filter_enabled"] = {"safe": None}
    assert grade(data)["BI-SY-13"].level == "N/A"
    row.values["policy_filter_enabled"] = {"safe": False}
    assert grade(data)["BI-SY-13"].level == "L1"


def test_noncompliance_and_exemption_are_not_perfect_policy_coverage(data: Collection) -> None:
    row = next(row for row in data.proposal_observations if row.code == "BI-SY-16")
    row.values["state"] = "NonCompliant"
    assert grade(data)["BI-SY-16"].level == "L1"
    row.values["state"] = "Unknown"
    assert grade(data)["BI-SY-16"].level == "N/A"


def test_missing_owner_counts_and_unresolved_role_names_are_unknown(data: Collection) -> None:
    data.entra_agent_identities[0].owner_count = None
    data.entra_agent_identities[0].app_roles = ["unresolved:abc"]
    assert grade(data)["OE-SY-20"].level == grade(data)["OE-SY-21"].level == "N/A"


def test_fully_linked_blueprint_must_have_actual_agent_identity_for_azure_link(data: Collection) -> None:
    data.entra_agent_identities[0].blueprint_id = "other"
    assert grade(data)["DP-SY-19"].level == "L1"


def test_metric_zero_is_observed_but_missing_timeseries_is_not(data: Collection) -> None:
    assert grade(data)["OT-SY-28"].level == "L5"
    data.facts["resource_metrics"][0]["metrics"] = []
    assert grade(data)["OT-SY-28"].level == "L1"
    data.facts["resource_metrics"] = []
    assert grade(data)["OT-SY-28"].level == "N/A"


def test_configuration_name_count_does_not_prove_a_network_boundary(data: Collection) -> None:
    row = next(row for row in data.proposal_observations if row.code == "DS-SY-07")
    row.values["public_network_access"] = "Enabled"
    assert grade(data)["DS-SY-07"].level == "L1"
    row.values["public_network_access"] = "Disabled"
    row.values["approved_private_endpoints"] = None
    assert grade(data)["DS-SY-07"].level == "N/A"


def test_qualitative_facts_cannot_elevate_api_grades(data: Collection) -> None:
    with pytest.raises(ValueError, match="policy_facts"):
        grade(data, facts={"major_type_blueprints_defined": {"value": True, "evidence_refs": ["file"]}})


def test_rules_reject_unknown_operator_and_missing_values() -> None:
    assert not matches({}, {"coverage": {"eq": 0}})
    assert matches({"coverage": 0}, {"coverage": {"eq": 0}})
    with pytest.raises(ValueError, match="Unknown criteria operator"):
        matches({"coverage": 1}, {"coverage": {"unknown": 1}})


def test_all_criteria_have_exactly_api_metrics_and_exhaustive_level_definitions() -> None:
    criteria = load_criteria()
    assert len(criteria["items"]) == 22
    assert "configuration_grading" not in criteria
    for config in criteria["items"].values():
        assert list(config["levels"]) == ["L1", "L2", "L3", "L4", "L5"]
        assert all(set(rule["when"]) == {"coverage"} for rule in config["rules"])
        for value in (0, 0.001, 0.79, 0.8, 0.89, 0.9, 0.99, 1):
            assert sum(matches({"coverage": value}, rule["when"]) for rule in config["rules"]) == 1
