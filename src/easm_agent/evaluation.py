from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol

from easm_agent.api_grading import PROFILE, Measurement, measurements
from easm_agent.models import AssessmentMeasurement, Collection, Finding
from easm_agent.provenance import assessment_provenance


class Evaluator(Protocol):
    def evaluate(self, data: Collection, criteria: Mapping[str, Any]) -> list[Finding]: ...


def matches(facts: dict[str, Any], conditions: dict[str, dict[str, Any]]) -> bool:
    operations = {
        "eq": lambda a, b: a == b, "gt": lambda a, b: a > b, "gte": lambda a, b: a >= b,
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


def readiness(data: Collection, config: dict[str, Any]) -> str | None:
    for key in config.get("complete_flags", []):
        if data.facts.get(key) is not True:
            return f"API 목록 수집 완료 확인 없음: {key}"
    for key in config.get("complete_subscriptions", []):
        if set(data.subscriptions) - set(data.facts.get(key, [])):
            return f"일부 구독의 API 목록 수집 미완료: {key}"
    if config.get("requires") != "entra":
        if not data.facts.get("inventory_complete"):
            return "구독 인벤토리 수집 미완료"
        if config.get("agent_denominator") and not data.facts.get("agent_inventory_complete"):
            return "Agent 인벤토리 수집 미완료"
    return None


def evaluate(
    data: Collection, criteria: dict[str, Any], allowed: dict[str, Any],
    conventions: dict[str, Any], policy_facts: dict[str, Any] | None = None,
    interviews: dict[str, float] | None = None,
    *, provenance_origin: Literal["evaluation", "saved_snapshot_reassessment"] = "evaluation",
) -> list[Finding]:
    if criteria.get("grading_profile") != PROFILE:
        raise ValueError(f"지원되지 않는 등급 기준입니다. grading_profile={PROFILE} 기준을 사용하세요.")
    if policy_facts:
        raise ValueError("policy_facts는 API 구성 등급의 입력으로 사용할 수 없습니다. API 조회값을 사용하세요.")
    observed = measurements(data, criteria, conventions)
    if observed.keys() != criteria["items"].keys():
        raise ValueError("구현 API 지표와 criteria.yaml의 항목이 일치하지 않습니다.")
    findings = []
    data.facts["grading_profile"] = PROFILE
    data.assessment_provenance = assessment_provenance(criteria, conventions, provenance_origin)
    for code, config in criteria["items"].items():
        measurement: Measurement = observed[code]
        issues = [row for row in data.issues if row.collector in config.get("collectors", [])]
        incomplete = readiness(data, config)
        reason = None
        ratio = measurement.ratio
        if issues:
            priority = {"permission_denied": 0, "error": 1, "license_missing": 2,
                        "feature_unavailable": 3, "not_found": 4}
            reason = min(issues, key=lambda row: priority[row.reason]).reason
            incomplete = "; ".join(sorted({row.detail for row in issues}))
        elif incomplete:
            reason = "error"
        elif measurement.unavailable:
            reason = "not_found"
            incomplete = measurement.unavailable
        if incomplete:
            ratio = None
        rule = next((rule for rule in config["rules"] if matches({"coverage": ratio}, rule["when"])), None)
        level = rule["level"] if rule else "N/A"
        if level == "N/A" and reason is None:
            reason = "not_found"
        rationale = measurement.detail
        if ratio is not None:
            rationale += f". API 충족 {measurement.compliant:g} / 대상 {measurement.total:g}, 비율 {ratio:.2%}"
        else:
            rationale += ". " + (incomplete or "충족률을 확정할 수 없음")
        rationale += "; " + config["limit"]
        if level == "L5":
            next_step = "Level 5: 현재 API 구성 충족률 유지"
        elif level == "N/A":
            next_step = "조회 사유 확인 후 API 수집 재실행"
        else:
            next_level = f"L{int(level[1:]) + 1}"
            next_step = f"다음 단계 조건: {config['levels'][next_level]}"
        interview = (interviews or {}).get(code)
        findings.append(Finding(
            se_code=code, scope=config["scope"], metric_value=ratio, level=level,
            measurement=AssessmentMeasurement(
                numerator=measurement.compliant if ratio is not None else None,
                denominator=measurement.total if ratio is not None else None,
                unit=measurement.unit, currency=measurement.currency,
                complete=ratio is not None, reason=incomplete or measurement.unavailable,
                targets=measurement.decisions,
            ),
            level_criterion=config["levels"].get(level),
            rationale=rationale, reason=reason,
            evidence_refs=sorted(set(measurement.refs) | {
                ref for entry in measurement.decisions for ref in entry.evidence_refs
            } | {ref for issue in issues for ref in issue.evidence_refs}),
            next_step=next_step, interview_level=interview,
            gap_flag=interview is not None and level != "N/A" and interview - int(level[1]) >= criteria["interview_gap"],
        ))
    return findings
