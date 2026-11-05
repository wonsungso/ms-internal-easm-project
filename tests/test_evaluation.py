from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from wasm_agent.evaluation import derive_facts, evaluate, matches
from wasm_agent.models import (
    DEFAULT_TAGS,
    Budget,
    Collection,
    ModelDeployment,
    PolicyAssignment,
    SecureScore,
    SecurityRecommendation,
    load_criteria,
)
from wasm_agent.proposals import TITLES

ROOT = Path(__file__).parents[1]
ALLOWED = {"models": [
    {"name": "gpt-4.1-nano", "version": "2025-04-14", "format": "OpenAI"},
    {"name": "gpt-4o-mini", "version": "2024-07-18", "format": "OpenAI"},
]}
TAGS = DEFAULT_TAGS


@pytest.fixture
def data() -> Collection:
    value = Collection.model_validate_json((ROOT / "tests" / "fixtures" / "three_subscriptions.json").read_text())
    for agent in value.agents:
        agent.mark_unknowns()
    return value


def criteria_with(**updates: object) -> dict:
    return {**load_criteria(), **updates}


def facts_for(data: Collection, **criteria_updates: object) -> dict:
    return derive_facts(data, criteria_with(**criteria_updates), ALLOWED, TAGS)


def findings(data: Collection, facts: dict | None = None, interviews: dict | None = None) -> dict:
    rows = evaluate(data, load_criteria(), ALLOWED, TAGS, facts, interviews)
    return {row.se_code: row for row in rows}


@pytest.mark.parametrize("allowed_count,level", [(79, "L2"), (80, "L2"), (85, "L2"), (89, "L2"), (90, "L3"), (100, "L3")])
def test_model_allowlist_boundaries_have_no_unclassified_band(data: Collection, allowed_count: int, level: str) -> None:
    template = data.deployments[0]
    data.deployments = [
        ModelDeployment(**{
            **template.model_dump(),
            "resource_id": f"/fixture/model/{index}", "name": f"model-{index}",
            "model": "gpt-4o-mini" if index < allowed_count else "not-allowed",
        }) for index in range(100)
    ]
    row = findings(data)["DS-SY-06"]
    assert row.metric_value == allowed_count / 100
    assert row.level == level


def test_perfect_ratio_alone_does_not_grant_l4(data: Collection) -> None:
    assert findings(data)["DS-SY-06"].level == "L3"
    assert findings(data, {"model_policy_enforced": {
        "value": True, "evidence_refs": ["fixture://enforced-policy"],
    }})["DS-SY-06"].level == "L4"
    with pytest.raises(ValueError, match="requires value and evidence_refs"):
        findings(data, {"model_policy_enforced": True})


def test_policy_facts_cannot_override_measured_values(data: Collection) -> None:
    with pytest.raises(ValueError, match="cannot override"):
        findings(data, {"allowed_ratio": {"value": 1, "evidence_refs": ["fixture://not-metric"]}})
    data.deployments = []
    with pytest.raises(ValueError, match="cannot override"):
        findings(data, {"allowed_ratio": {"value": 1, "evidence_refs": ["fixture://not-metric"]}})


def test_before_deploy_requires_same_agent_version_and_completion(data: Collection) -> None:
    row = findings(data)["BI-SY-08"]
    assert row.metric_value == 1
    assert row.level == "L3"
    data.evaluations[0].agent_version = "different"
    data.agents[0].evaluated_before_deploy = None
    assert findings(data)["BI-SY-08"].level == "N/A"


def test_creation_timestamp_is_not_deployment_timestamp(data: Collection) -> None:
    data.agents[0].deployed_at = None
    data.agents[0].evaluated_before_deploy = None
    row = findings(data)["BI-SY-08"]
    assert row.metric_value is None
    assert row.level == "N/A"


def test_late_evaluation_with_incomplete_history_is_unknown(data: Collection) -> None:
    data.evaluations[0].completed_at = data.agents[0].deployed_at + timedelta(days=1)
    data.facts["evaluation_complete_projects"] = []
    data.agents[0].evaluated_before_deploy = None
    findings(data)
    assert data.agents[0].evaluated_before_deploy is None


@pytest.mark.parametrize("inactive_count,level", [(0, "L3"), (19, "L3"), (20, "L2"), (39, "L2"), (40, "L2")])
def test_inactivity_boundaries(data: Collection, inactive_count: int, level: str) -> None:
    template = data.agents[0]
    data.agents = [
        template.model_copy(update={
            "agent_id": f"agent-{index}",
            "last_used_at": data.collected_at - timedelta(days=91 if index < inactive_count else 1),
            "usage_coverage_start": data.collected_at - timedelta(days=100),
        }, deep=True) for index in range(100)
    ]
    row = findings(data)["OT-SY-18"]
    assert row.metric_value == inactive_count / 100
    assert row.level == level


def test_missing_usage_is_not_inactive_or_zero(data: Collection) -> None:
    data.agents[0].last_used_at = None
    data.agents[0].usage_coverage_start = None
    row = findings(data)["OT-SY-18"]
    assert row.metric_value is None and row.level == "N/A"


def test_cost_shared_model_not_allocated_twice_and_host_plan_is_included(data: Collection) -> None:
    row = findings(data)["OT-SY-19"]
    assert row.metric_value == 0.8
    assert row.level == "L3"
    assert data.agents[0].cost_30d is None
    assert data.agents[1].cost_30d == 40
    assert data.agents[2].cost_30d == 40


def test_cost_currency_mixing_and_absence_are_na(data: Collection) -> None:
    data.costs[1].currency = "KRW"
    assert findings(data)["OT-SY-19"].level == "N/A"
    data.costs = []
    row = findings(data)["OT-SY-19"]
    assert row.metric_value is None and row.level == "N/A"


def test_retention_uses_customer_threshold_not_hardcoded_one_year(data: Collection) -> None:
    assert findings(data)["OE-SY-15"].level == "N/A"
    criteria = load_criteria()
    criteria["required_retention_days"] = 60
    assert next(row for row in evaluate(data, criteria, ALLOWED, TAGS) if row.se_code == "OE-SY-15").level == "N/A"
    result = evaluate(data, criteria, ALLOWED, TAGS, {
        "retention_scope_verified": {"value": True, "evidence_refs": ["fixture://effective-table-retention"]},
    })
    assert next(row for row in result if row.se_code == "OE-SY-15").level == "L3"


def test_interview_gap_exact_boundary(data: Collection) -> None:
    assert findings(data, interviews={"DS-SY-06": 4.5})["DS-SY-06"].gap_flag is True
    assert findings(data, interviews={"DS-SY-06": 4.49})["DS-SY-06"].gap_flag is False


def test_partial_subscription_denominator_never_produces_confident_score(data: Collection) -> None:
    data.facts["inventory_complete"] = False
    assert all(row.level == "N/A" and row.metric_value is None for row in findings(data).values())


def entra_data(data: Collection, mapped: bool = True) -> Collection:
    from wasm_agent.models import EntraAgentIdentity, EntraBlueprint

    sid = data.subscriptions[0]
    project = f"/subscriptions/{sid}/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/acct/projects/proj"
    first = data.agents[0].model_copy(update={
        "platform": "foundry", "resource_id": project, "subscription_id": sid, "agent_name": "a1",
        "agent_id": "a1", "tags": {"env": "prod"},
    })
    second = first.model_copy(update={"agent_name": "a2", "agent_id": "a2"})
    data.agents = [first, second]
    tags = ["agentName:A1", "projectName:Proj", "accountName:ACCT", f"subscriptionId:{sid.upper()}"]
    data.entra_blueprints = [
        EntraBlueprint(blueprint_id="bp-1", tags=tags if mapped else []),
        EntraBlueprint(blueprint_id="bp-2"), EntraBlueprint(blueprint_id="bp-3"),
    ]
    data.entra_agent_identities = [
        EntraAgentIdentity(identity_id=f"id-{index}", blueprint_id="bp-1", owner_count=1, sponsor_count=1,
                           owners_all_disabled=False)
        for index in range(4)
    ]
    data.facts.update({
        "entra_requested": True, "entra_blueprints_complete": True, "entra_agents_complete": True,
    })
    return data


def test_entra_facts_map_azure_agents_by_blueprint_tags_and_never_use_names_of_people(data: Collection) -> None:
    facts = facts_for(entra_data(data))
    assert facts["agent_identity_count"] == 4 and facts["blueprint_count"] == 3
    assert facts["blueprint_based_ratio"] == 1
    assert facts["agent_id_ratio"] == 0.5
    assert facts["unassigned_ratio"] == 0 and facts["overprivileged_ratio"] == 0
    assert "agent_ca_coverage" not in facts and "unremediated_risk_detections" not in facts
    assert facts_for(entra_data(data, mapped=False))["agent_id_ratio"] == 0


def test_entra_unassigned_and_overprivileged_are_derived_from_graph_evidence(data: Collection) -> None:
    data = entra_data(data)
    identities = data.entra_agent_identities
    identities[0].sponsor_count = 0
    identities[1].owners_all_disabled = True
    identities[2].overprivileged_roles = ["Mail.ReadWrite.All"]
    facts = facts_for(data)
    assert facts["unassigned_ratio"] == 0.5 and facts["overprivileged_ratio"] == 0.25
    data.facts["entra_agents_complete"] = False
    assert "unassigned_ratio" not in facts_for(data) and "agent_identity_count" not in facts_for(data)


def levels(data: Collection, facts: dict | None = None) -> dict:
    rows = evaluate(data, load_criteria(), ALLOWED, TAGS, facts)
    return {row.se_code: row for row in rows}


def test_entra_items_are_always_reported_and_stay_conservative(data: Collection) -> None:
    assert set(levels(data)) == set(load_criteria()["items"])
    rows = levels(entra_data(data))
    entra = {"DS-SY-05", "DP-SY-12", "OE-SY-13", "OE-SY-14"}
    assert entra <= set(rows)
    assert rows["DS-SY-05"].level == "N/A" and rows["DS-SY-05"].metric_value == 3
    assert rows["OE-SY-13"].level == "L3" and rows["OE-SY-13"].metric_value == 0
    assert "Agent Registry" in rows["DP-SY-12"].rationale
    assert rows["OE-SY-14"].level == "L3" and "샘플 과다 권한" in rows["OE-SY-14"].rationale


def test_entra_levels_follow_reviewed_thresholds_and_customer_evidence(data: Collection) -> None:
    data = entra_data(data)
    data.entra_agent_identities[0].sponsor_count = 0
    data.entra_agent_identities[1].sponsor_count = 0
    rows = levels(data)
    assert (rows["OE-SY-13"].level, rows["OE-SY-13"].metric_value) == ("L2", 0.5)
    data.entra_agent_identities[1].sponsor_count = 1
    assert levels(data)["OE-SY-13"].level == "L2"
    data.entra_agent_identities[0].sponsor_count = 1
    assert levels(data)["OE-SY-13"].metric_value == 0
    evidence = {"value": True, "evidence_refs": ["fixture://customer"]}
    assert levels(data, {"major_type_blueprints_defined": evidence})["DS-SY-05"].level == "L4"
    data.entra_blueprints = data.entra_blueprints[:2]
    assert levels(data)["DS-SY-05"].level == "N/A"
    data.entra_blueprints, data.entra_agent_identities = [], []
    assert levels(data)["DS-SY-05"].level == "L1" and levels(data)["OE-SY-13"].level == "N/A"


def test_entra_item_is_not_blocked_by_an_incomplete_azure_inventory(data: Collection) -> None:
    data = entra_data(data)
    data.facts["inventory_complete"] = False
    rows = levels(data)
    assert rows["OE-SY-13"].metric_value == 0 and rows["OE-SY-13"].level == "L3"
    assert rows["DP-SY-12"].level == "N/A" and rows["DP-SY-12"].metric_value is None


def test_boolean_policy_does_not_accept_integer_one() -> None:
    assert matches({"policy": 1}, {"policy": {"eq": True}}) is False


def test_security_score_and_recommendation_age_are_derived_from_collected_evidence(data: Collection) -> None:
    sids = data.subscriptions
    assert "security_score" not in facts_for(data)
    data.facts["secure_score_complete_subscriptions"] = list(sids)
    data.secure_scores = [
        SecureScore(subscription_id=sid, percentage=value) for sid, value in zip(sids, (0.9, 0.75, 0.8), strict=True)
    ]
    data.security = [SecurityRecommendation(
        subscription_id=sids[0], resource_id="r", assessment_id="a", severity="High", status="Unhealthy",
        first_evaluation_date=data.collected_at - timedelta(days=40),
        status_change_date=data.collected_at - timedelta(days=10),
    )]
    facts = facts_for(data)
    assert facts["security_score"] == pytest.approx(75)
    assert facts["recommendation_max_age_days"] == 10
    data.security[0].status_change_date = data.security[0].first_evaluation_date = None
    assert "recommendation_max_age_days" not in facts_for(data)
    data.secure_scores.pop()
    assert "security_score" not in facts_for(data)


def test_internal_security_score_threshold_is_customer_supplied_and_enables_l3(data: Collection) -> None:
    sids = data.subscriptions
    data.facts["secure_score_complete_subscriptions"] = list(sids)
    data.secure_scores = [SecureScore(subscription_id=sid, percentage=0.8) for sid in sids]
    data.security = [SecurityRecommendation(
        subscription_id=sids[0], resource_id="r", assessment_id="a", severity="Low", status="Healthy",
    )]

    def level(minimum: float | None) -> str:
        rows = evaluate(data, criteria_with(internal_security_score_min=minimum), ALLOWED, TAGS)
        return next(row.level for row in rows if row.se_code == "BI-SY-09")

    assert level(None) == "N/A"
    assert level(85) == "N/A"
    assert level(80) == "L3"


def test_model_policy_enforcement_requires_every_subscription_and_customer_definition(data: Collection) -> None:
    sids = data.subscriptions
    definition = "/providers/Microsoft.Authorization/policyDefinitions/model-allowlist"
    data.facts["policy_complete_subscriptions"] = list(sids)
    assert "model_policy_assigned" not in facts_for(data)
    data.policy_assignments = [
        PolicyAssignment(
            subscription_id=sid, assignment_id=f"/a/{sid}", policy_definition_id=definition.upper(),
            enforcement_mode="Default",
        ) for sid in sids
    ]
    assert facts_for(data, model_policy_definition_ids=[definition])["model_policy_assigned"] is True
    assert "model_policy_enforced" not in facts_for(data, model_policy_definition_ids=[definition])
    data.policy_assignments[1].enforcement_mode = "DoNotEnforce"
    assert facts_for(data, model_policy_definition_ids=[definition])["model_policy_assigned"] is False
    data.facts["policy_complete_subscriptions"] = list(sids[:2])
    assert "model_policy_assigned" not in facts_for(data, model_policy_definition_ids=[definition])


def test_budget_alerts_and_cost_center_tags_enable_the_l4_cost_condition(data: Collection) -> None:
    sids = {agent.subscription_id for agent in data.agents}
    data.facts["budget_complete_subscriptions"] = sorted(sids)
    data.budgets = [Budget(subscription_id=sid, budget_id=f"/b/{sid}", enabled_alerts=1) for sid in sorted(sids)]
    assert facts_for(data)["budget_alerts_configured"] is True
    assert facts_for(data)["cost_allocation_tagged"] is False
    for agent in data.agents:
        agent.tags["cost-center"] = "cc-1"
    assert facts_for(data)["cost_allocation_tagged"] is True
    data.budgets[0].enabled_alerts = 0
    assert facts_for(data)["budget_alerts_configured"] is False
    data.facts["budget_complete_subscriptions"] = sorted(sids)[:1]
    assert "budget_alerts_configured" not in facts_for(data)


@pytest.mark.parametrize("code", TITLES)
@pytest.mark.parametrize("level", [1, 2, 3, 4, 5])
def test_all_azure_controls_are_scored_with_cumulative_evidence(code: str, level: int) -> None:
    criteria = load_criteria()
    config = criteria["items"][code]
    target = next(rule["when"][config["metric"]]["gte"] for rule in config["rules"] if rule["level"] == "L3")
    compliant = 0 if level == 1 else int(target * 100) - 1 if level == 2 else 100
    policy = {
        config["assessment_key"]: {
            "value": {"total": 100, "compliant": compliant}, "evidence_refs": ["fixture://complete-review"],
        },
    }
    if level >= 3:
        rule = next(rule for rule in config["rules"] if rule["level"] == f"L{level}")
        policy.update({
            name: {"value": True, "evidence_refs": [f"fixture://{name}"]}
            for name in rule["when"] if name != config["metric"]
        })
    data = Collection(collected_at="2026-11-05T00:00:00Z", facts={
        "inventory_complete": True, "agent_inventory_complete": True,
    })
    row = next(item for item in evaluate(data, criteria, {}, TAGS, policy) if item.se_code == code)
    assert row.level == f"L{level}" and row.metric_value == compliant / 100
    if level == 5:
        enforced = next(name for name in policy if name.endswith("_enforced"))
        del policy[enforced]
        row = next(item for item in evaluate(data, criteria, {}, TAGS, policy) if item.se_code == code)
        assert row.level == "L3"


@pytest.mark.parametrize("code", TITLES)
def test_perfect_control_ratio_does_not_invent_standardization_or_automation(code: str) -> None:
    config = load_criteria()["items"][code]
    data = Collection(collected_at="2026-11-05T00:00:00Z", facts={"inventory_complete": True})
    policy = {config["assessment_key"]: {
        "value": {"total": 10, "compliant": 10}, "evidence_refs": ["fixture://review"],
    }}
    row = next(item for item in evaluate(data, load_criteria(), {}, TAGS, policy) if item.se_code == code)
    assert row.level == "N/A" and row.metric_value == 1
    policy[config["assessment_key"]]["value"] = {"total": 0, "compliant": 0}
    row = next(item for item in evaluate(data, load_criteria(), {}, TAGS, policy) if item.se_code == code)
    assert row.level == "N/A" and row.metric_value is None


@pytest.mark.parametrize("value", [
    {"total": 2, "compliant": 3}, {"total": -1, "compliant": 0},
    {"total": 10, "compliant": True}, {"total": 10.0, "compliant": 9},
    {"total": 10}, 1, None,
])
def test_reviewed_assessment_rejects_invalid_counts(data: Collection, value: object) -> None:
    with pytest.raises(ValueError, match="requires integer counts"):
        findings(data, {"network_assessment": {"value": value, "evidence_refs": ["fixture://review"]}})


def test_public_access_flag_filter_name_and_runtime_option_are_not_effectiveness_scores(data: Collection) -> None:
    from wasm_agent.models import ProposalObservation

    data.proposal_observations = [
        ProposalObservation(code="DS-SY-07", subject="acct", kind="ai_account", values={
            "public_network_access": "Enabled", "default_action": "Deny", "private_endpoints": 1,
        }),
    ]
    for row in data.deployments:
        row.rai_policy = None
        row.version_upgrade_option = "NoAutoUpgrade"
    rows = findings(data)
    assert all(rows[code].level == "N/A" for code in ("DS-SY-07", "BI-SY-10", "BI-SY-12"))
    assert all(rows[code].metric_value is None for code in ("DS-SY-07", "BI-SY-10", "BI-SY-12"))


def test_tag_metric_requires_all_keys_on_the_same_agent_and_cannot_be_overridden(data: Collection) -> None:
    for agent in data.agents:
        agent.owner = agent.sponsor = None
        agent.tags = {"owner": "team", "env": "prod", "cost-center": "x"}
    assert findings(data)["BI-SY-13"].metric_value == 0
    with pytest.raises(ValueError, match="cannot override"):
        findings(data, {"asset_assessment": {
            "value": {"total": 3, "compliant": 3}, "evidence_refs": ["fixture://conflicting-review"],
        }})
    data.agents[0].sponsor = "team"
    assert findings(data)["BI-SY-13"].metric_value == pytest.approx(1 / 3)


@pytest.mark.parametrize("config", load_criteria()["items"].values(), ids=load_criteria()["items"].keys())
def test_every_l5_also_satisfies_an_l4_rule(config: dict) -> None:
    for rule in config["rules"]:
        if rule["level"] != "L5":
            continue
        facts = {}
        for name, conditions in rule["when"].items():
            operator, value = next(iter(conditions.items()))
            facts[name] = value / 2 if operator == "lt" else value
        assert matches(facts, rule["when"])
        assert any(matches(facts, lower["when"]) for lower in config["rules"] if lower["level"] == "L4")
