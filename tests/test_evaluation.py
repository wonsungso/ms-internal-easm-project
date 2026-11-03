from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from wasm_agent.evaluation import evaluate, matches
from wasm_agent.models import Collection, ModelDeployment
from wasm_agent.settings import load_yaml

ROOT = Path(__file__).parents[1]


@pytest.fixture
def data() -> Collection:
    value = Collection.model_validate_json((ROOT / "tests" / "fixtures" / "three_subscriptions.json").read_text())
    for agent in value.agents:
        agent.mark_unknowns()
    return value


def findings(data: Collection, facts: dict | None = None, interviews: dict | None = None) -> dict:
    rows = evaluate(
        data, load_yaml(ROOT / "config" / "criteria.yaml"),
        load_yaml(ROOT / "config" / "allowed_models.yaml"),
        load_yaml(ROOT / "config" / "tag_conventions.yaml"), facts, interviews,
    )
    return {row.se_code: row for row in rows}


@pytest.mark.parametrize("allowed_count,level", [(79, "L2"), (80, "L2"), (85, "N/A"), (90, "L3"), (100, "L3")])
def test_model_allowlist_boundaries_do_not_interpolate(data: Collection, allowed_count: int, level: str) -> None:
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


@pytest.mark.parametrize("inactive_count,level", [(0, "L3"), (19, "L3"), (20, "N/A"), (39, "N/A"), (40, "L2")])
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
    assert findings(data)["OE-SY-16"].level == "L2"
    criteria = load_yaml(ROOT / "config" / "criteria.yaml")
    criteria["required_retention_days"] = 60
    result = evaluate(data, criteria, load_yaml(ROOT / "config" / "allowed_models.yaml"),
                      load_yaml(ROOT / "config" / "tag_conventions.yaml"))
    assert next(row for row in result if row.se_code == "OE-SY-16").level == "L3"


def test_interview_gap_exact_boundary(data: Collection) -> None:
    assert findings(data, interviews={"DS-SY-06": 4.5})["DS-SY-06"].gap_flag is True
    assert findings(data, interviews={"DS-SY-06": 4.49})["DS-SY-06"].gap_flag is False


def test_partial_subscription_denominator_never_produces_confident_score(data: Collection) -> None:
    data.facts["inventory_complete"] = False
    assert all(row.level == "N/A" and row.metric_value is None for row in findings(data).values())


def test_boolean_policy_does_not_accept_integer_one() -> None:
    assert matches({"policy": 1}, {"policy": {"eq": True}}) is False
