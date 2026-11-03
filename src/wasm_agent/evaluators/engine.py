from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Protocol

from wasm_agent.models import Collection, Finding


class Evaluator(Protocol):
    def evaluate(self, data: Collection, criteria: Mapping[str, Any]) -> list[Finding]: ...


def matches(facts: dict[str, Any], conditions: dict[str, dict[str, Any]]) -> bool:
    operations = {
        "eq": lambda a, b: a == b,
        "gt": lambda a, b: a > b, "gte": lambda a, b: a >= b,
        "lt": lambda a, b: a < b, "lte": lambda a, b: a <= b,
    }
    for key, tests in conditions.items():
        value = facts.get(key)
        if value is None:
            return False
        for operator, threshold in tests.items():
            if operator not in operations:
                raise ValueError(f"Unknown criteria operator: {operator}")
            if isinstance(threshold, bool):
                if operator != "eq" or value is not threshold:
                    return False
            elif not operations[operator](value, threshold):
                return False
    return True


def evidence_refs(data: Collection) -> list[str]:
    result = set()
    for field in ("agents", "deployments", "evaluations", "costs", "security", "logs", "issues"):
        for entry in getattr(data, field):
            result.update(entry.evidence_refs)
    return sorted(result)


def derive_facts(
    data: Collection, criteria: dict[str, Any], allowed: dict[str, Any],
    conventions: dict[str, Any],
) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    azure_agents = [agent for agent in data.agents if agent.platform in ("foundry", "langchain")]
    models = allowed.get("models") or []
    if data.deployments and models and data.facts.get("deployment_inventory_complete", False):
        hits = sum(any(
            item.get("name") == deployment.model
            and item.get("version") == deployment.version
            and item.get("format") == deployment.format
            for item in models
        ) for deployment in data.deployments)
        facts["allowed_ratio"] = hits / len(data.deployments)
        facts["outside_ratio"] = (len(data.deployments) - hits) / len(data.deployments)
    production = [
        agent for agent in azure_agents
        if agent.tags.get(conventions["environment_key"]) in conventions["production_values"]
    ]
    complete_projects = set(data.facts.get("evaluation_complete_projects", []))
    project_ids = set(data.facts.get("foundry_project_ids", []))
    if production and project_ids and project_ids <= complete_projects:
        facts["evaluation_history_complete"] = True
        facts["evaluation_history_count"] = len(data.evaluations)
        if not data.evaluations and all(agent.platform == "foundry" for agent in production):
            for agent in production:
                agent.evaluated_before_deploy = False
                agent.field_status.pop("evaluated_before_deploy", None)
    for agent in production:
        if agent.deployed_at is None:
            continue
        runs = [
            run for run in data.evaluations
            if run.agent_id == agent.agent_id
            and run.agent_version == agent.agent_version
            and run.project_id == agent.resource_id
            and run.completed_at is not None
            and run.status in ("completed", "succeeded", "Succeeded")
        ]
        if runs:
            before = any(run.completed_at <= agent.deployed_at for run in runs)
            if before or agent.resource_id in complete_projects:
                agent.evaluated_before_deploy = before
                agent.field_status.pop("evaluated_before_deploy", None)
    if production and all(agent.evaluated_before_deploy is not None for agent in production):
        facts["evaluated_ratio"] = sum(agent.evaluated_before_deploy is True for agent in production) / len(production)
    inactivity = []
    cutoff = data.collected_at - timedelta(days=criteria["inactivity_days"])
    for agent in azure_agents:
        if agent.last_used_at is not None and agent.last_used_at > cutoff:
            inactivity.append(False)
        elif agent.usage_coverage_start is not None and agent.usage_coverage_start <= cutoff:
            inactivity.append(agent.last_used_at is None or agent.last_used_at <= cutoff)
        else:
            inactivity.append(None)
    if inactivity and None not in inactivity:
        facts["inactive_ratio"] = sum(value is True for value in inactivity) / len(inactivity)
    if data.logs and all(setting.enabled for setting in data.logs) and not any(
        item.collector == "logs" for item in data.issues
    ):
        retention = [setting.retention_days for setting in data.logs if setting.retention_days is not None]
        if len(retention) == len(data.logs):
            facts["retention_days"] = min(retention)
            required = criteria.get("required_retention_days")
            if required is not None:
                facts["retention_meets_internal"] = facts["retention_days"] >= required
        if data.facts.get("audit_activity_observed"):
            facts["logs_collected"] = True
    currencies = {row.currency for row in data.costs}
    complete_cost = set(data.facts.get("cost_complete_subscriptions", []))
    if data.costs and len(currencies) == 1 and set(data.subscriptions) <= complete_cost:
        amount = sum(row.amount for row in data.costs)
        if amount > 0 and all(row.amount >= 0 for row in data.costs):
            allocated = 0.0
            agent_costs: dict[tuple[str | None, str, str | None, str], float] = {}
            for row in data.costs:
                matching = [
                    agent for agent in azure_agents
                    if row.resource_id.lower() in {
                        (agent.resource_id or "").lower(), (agent.model_resource_id or "").lower(),
                        *[rid.lower() for rid in agent.cost_resource_ids],
                    }
                ]
                if len(matching) == 1:
                    allocated += row.amount
                    agent = matching[0]
                    key = (agent.subscription_id, agent.platform, agent.resource_id, agent.agent_id)
                    agent_costs[key] = agent_costs.get(key, 0) + row.amount
            for agent in azure_agents:
                key = (agent.subscription_id, agent.platform, agent.resource_id, agent.agent_id)
                if key in agent_costs:
                    agent.cost_30d = agent_costs[key]
                    agent.currency = next(iter(currencies))
                    agent.field_status.pop("cost_30d", None)
                    agent.field_status.pop("currency", None)
            facts["attributable_cost_ratio"] = allocated / amount
            facts["monthly_cost_aggregation"] = all(row.usage_date is not None for row in data.costs)
    if data.security and not any(item.collector == "security" for item in data.issues) and all(
        row.severity in ("High", "Medium", "Low") and row.status in ("Healthy", "Unhealthy", "NotApplicable")
        for row in data.security
    ):
        facts["high_risk_recommendations"] = sum(
            row.severity == "High" and row.status == "Unhealthy" for row in data.security
        )
    return facts


def evaluate(
    data: Collection, criteria: dict[str, Any], allowed: dict[str, Any],
    conventions: dict[str, Any], policy_facts: dict[str, Any] | None = None,
    interviews: dict[str, float] | None = None,
) -> list[Finding]:
    facts = derive_facts(data, criteria, allowed, conventions)
    refs = evidence_refs(data)
    reserved = {entry["metric"] for entry in criteria["items"].values()}
    reserved.update(("outside_ratio", "security_score_meets_internal"))
    for name, entry in (policy_facts or {}).items():
        if not isinstance(entry, dict) or "value" not in entry or not entry.get("evidence_refs"):
            raise ValueError(f"Policy fact {name} requires value and evidence_refs")
        if name in facts or name in reserved:
            raise ValueError(f"Policy fact cannot override measured metric: {name}")
        facts[name] = entry["value"]
        refs.extend(entry["evidence_refs"])
    if facts.get("security_score") is not None and criteria.get("internal_security_score_min") is not None:
        facts["security_score_meets_internal"] = facts["security_score"] >= criteria["internal_security_score_min"]
    findings = []
    for code, config in criteria["items"].items():
        value = facts.get(config["metric"])
        matched = next((rule for rule in config["rules"] if matches(facts, rule["when"])), None)
        if value is None and matched and matched["level"] != "L1":
            matched = None
        level = matched["level"] if matched else "N/A"
        reason = None
        rationale = "원문 기준에 해당하는 수치·정성 조건을 확인한 판정 초안"
        if not data.facts.get("inventory_complete"):
            value = None
            level, reason = "N/A", "permission_denied" if any(
                issue.reason == "permission_denied" and issue.collector == "subscription" for issue in data.issues
            ) else "error"
            rationale = "구독 인벤토리 부분 실패로 전체 분모를 확정할 수 없음"
        elif not matched:
            reason = "not_found"
            rationale = (
                "필요 증적·귀속·관측 기간이 부족하거나 원문에 정의되지 않은 수치 구간/정성 조건임"
            )
            related = {
                "DS-SY-06": ("model_deployments",),
                "BI-SY-08": ("foundry_agents", "foundry_evaluations"),
                "BI-SY-09": ("security",), "OE-SY-16": ("logs", "agent_usage"),
                "OT-SY-18": ("agent_usage",), "OT-SY-19": ("cost",),
            }
            issues = [item for item in data.issues if item.collector in related[code]]
            if issues:
                priority = {"permission_denied": 0, "error": 1, "license_missing": 2,
                            "feature_unavailable": 3, "not_found": 4}
                reason = min(issues, key=lambda item: priority[item.reason]).reason
                rationale += "; " + "; ".join(sorted({item.detail for item in issues}))
        if code in ("BI-SY-08", "OT-SY-18", "OT-SY-19") and not data.facts.get(
            "agent_inventory_complete", data.facts.get("inventory_complete"),
        ):
            value, level = None, "N/A"
            reason = "permission_denied" if any(
                item.reason == "permission_denied" and item.collector in (
                    "foundry_agents", "foundry_projects", "subscription",
                ) for item in data.issues
            ) else "error"
            rationale = "Agent 목록의 일부를 수집하지 못해 전체 Agent 분모/귀속을 확정할 수 없음"
        if config["scope"] == "partial":
            rationale += "; Azure 부분 범위이며 원 제품/조직 전체 점수가 아님"
        if code == "DS-SY-06" and allowed.get("sample_policy"):
            rationale += "; 샘플 허용 모델 목록 사용, 고객 정책 승인 필요"
        if level == "N/A":
            next_step = "부족 증적을 확보한 뒤 목표 기준 확인: " + config["levels"]["L3"]
        elif level == "L5":
            next_step = "L5 운영 증적을 지속 확인"
        else:
            next_step = "다음 단계 조건: " + config["levels"]["L" + str(int(level[1]) + 1)]
        interview = (interviews or {}).get(code)
        gap = (
            interview is not None and level != "N/A"
            and interview - int(level[1]) >= criteria["interview_gap"]
        )
        findings.append(Finding(
            se_code=code, scope=config["scope"], metric_value=value,
            level=level, rationale=rationale, reason=reason, evidence_refs=sorted(set(refs)),
            next_step=next_step, interview_level=interview, gap_flag=gap,
        ))
    return findings
