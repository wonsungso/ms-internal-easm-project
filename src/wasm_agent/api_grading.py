from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from wasm_agent.models import AZURE_AGENT_PLATFORMS, HOSTED_AGENT_PLATFORMS, Collection

PROFILE = "api_configuration_v1"


@dataclass
class Measurement:
    total: float = 0
    compliant: float = 0
    detail: str = ""
    unavailable: str | None = None
    refs: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float | None:
        return self.compliant / self.total if self.total and not self.unavailable else None


def measured(values: list[bool | None], detail: str, refs: list[str] | None = None) -> Measurement:
    return Measurement(
        total=len(values), compliant=sum(value is True for value in values), detail=detail,
        unavailable="필수 API 필드 누락" if None in values else "대상 없음" if not values else None,
        refs=refs or [],
    )


def and_known(*values: bool | None) -> bool | None:
    if False in values:
        return False
    return None if None in values else True


def numeric(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def targets(data: Collection) -> set[str]:
    found = {
        row["id"].lower() for row in data.resources
        if str(row.get("type", "")).lower() == "microsoft.cognitiveservices/accounts"
        and str(row.get("kind", "")).lower() in ("aiservices", "openai")
    }
    found.update(
        agent.resource_id.lower() for agent in data.agents
        if agent.platform in HOSTED_AGENT_PLATFORMS and agent.resource_id
    )
    return found


def observations(data: Collection, code: str) -> list[Any]:
    return [row for row in data.proposal_observations if row.code == code]


def from_observations(rows: list[Any], values: list[bool | None], detail: str) -> Measurement:
    return measured(values, detail, [ref for row in rows for ref in row.evidence_refs])


def measurements(
    data: Collection, criteria: dict[str, Any], tags: dict[str, Any],
) -> dict[str, Measurement]:
    result: dict[str, Measurement] = {}
    agents = [agent for agent in data.agents if agent.platform in AZURE_AGENT_PLATFORMS]
    identities, blueprints = data.entra_agent_identities, data.entra_blueprints
    blueprint_ids = {row.blueprint_id.lower() for row in blueprints}
    result["DS-SY-05"] = measured([
        bool(row.blueprint_id) and row.blueprint_id.lower() in blueprint_ids for row in identities
    ], "수집 Agent ID 중 실제 Blueprint ID가 수집 Blueprint 목록과 연결된 비율")
    result["DS-SY-06"] = measured([
        and_known(
            bool(row.model) if row.model is not None else None,
            bool(row.version) if row.version is not None else None,
            bool(row.format) if row.format is not None else None,
            row.version_upgrade_option in criteria["version_upgrade_options"]
            if row.version_upgrade_option is not None else None,
        ) for row in data.deployments
    ], "전체 모델 배포 중 모델·버전·형식과 인식 가능한 업데이트 옵션이 있는 비율")
    network = observations(data, "DS-SY-07")
    boundary = []
    for row in network:
        value = row.values
        public = value.get("public_network_access")
        if row.kind == "ai_account":
            state = and_known(
                public == "Disabled" if public is not None else None,
                value.get("approved_private_endpoints", 0) > 0
                if value.get("approved_private_endpoints") is not None else None,
            )
        else:
            private = public == "Disabled" if public is not None else None
            restricted = value.get("ip_default_deny")
            if value.get("host_type") == "microsoft.app/containerapps":
                private = value.get("ingress_external") is False if value.get("ingress_external") is not None else None
                restricted = False
            state = private if private is True else restricted if restricted is True else (
                None if private is None or restricted is None else False
            )
        boundary.append(state)
    result["DS-SY-07"] = from_observations(network, boundary, "대상 AI 계정·호스트 중 확인된 인바운드 경계 설정 비율")
    tool_rows = observations(data, "DS-SY-08")
    modes = [mode for row in tool_rows for mode in row.values.get("mcp_approval_modes", [])]
    result["DS-SY-08"] = from_observations(
        tool_rows, [mode == "always" if mode in ("always", "never", "custom") else None for mode in modes],
        "MCP 도구 선언 중 require_approval=always인 비율; 함수·내장 도구는 분모 제외",
    )
    endpoints = observations(data, "DS-SY-09")
    result["DS-SY-09"] = from_observations(
        endpoints, [value for row in endpoints for value in row.values.get("endpoint_https", [])],
        "명시된 외부 도구 URL 중 HTTPS이며 호스트가 유효하고 URL 내 인증정보가 없는 비율",
    )
    complete_projects = set(data.facts.get("evaluation_complete_projects", []))
    project_ids = set(data.facts.get("foundry_project_ids", []))
    evaluated = {run.project_id.lower() for run in data.evaluations if (run.status or "").lower() in ("completed", "succeeded")}
    result["BI-SY-11"] = measured(
        [project.lower() in evaluated for project in sorted(project_ids)],
        "발견한 Foundry 프로젝트 중 완료 상태 평가 실행이 있는 프로젝트 비율",
    )
    if project_ids - complete_projects:
        result["BI-SY-11"].unavailable = "평가 목록 수집이 완료되지 않은 프로젝트가 있음"
    recommendations = [row for row in data.security if row.status != "NotApplicable"]
    result["BI-SY-12"] = measured([
        row.status == "Healthy" if row.status in ("Healthy", "Unhealthy") else None for row in recommendations
    ], "수집 AI 리소스 보안 권고 중 Healthy 비율; NotApplicable 제외")
    safety_rows = observations(data, "BI-SY-13")
    policies = {row.subject.lower(): row.values["policy_filter_enabled"] for row in safety_rows
                if isinstance(row.values.get("policy_filter_enabled"), dict)}
    result["BI-SY-13"] = measured([
        policies[row.account_id.lower()].get(row.rai_policy, False)
        if row.account_id.lower() in policies else None for row in data.deployments
    ], "전체 모델 배포 중 연결 정책이 실제 목록에 존재하고 enabled 필터가 확인된 비율")
    versions = observations(data, "BI-SY-14")
    pinned = [bool(agent.agent_version) if agent.agent_version is not None else None
              for agent in agents if agent.platform == "foundry"]
    for row in versions:
        value = row.values
        if value.get("image"):
            pinned.append(value.get("pinned_by_digest"))
        elif value.get("runtime"):
            runtime = str(value["runtime"])
            pinned.append(any(char.isdigit() for char in runtime) and "latest" not in runtime.lower())
        else:
            pinned.append(None)
    result["BI-SY-14"] = measured(pinned, "Foundry 버전과 자체 호스트 런타임 버전·컨테이너 다이제스트 고정 비율")
    result["BI-SY-15"] = measured([
        all((
            bool(agent.tags.get(tags["owner_key"]) or agent.owner),
            bool(agent.tags.get(tags["sponsor_key"]) or agent.sponsor),
            bool(agent.tags.get(tags["environment_key"])),
            bool(agent.tags.get(tags["cost_center_key"])),
        )) for agent in agents
    ], "전체 Azure Agent 중 owner·sponsor·환경·비용센터 4개 메타데이터가 모두 있는 비율")
    policy_rows = observations(data, "BI-SY-16")
    states: list[bool | None] = []
    for row in policy_rows:
        if row.kind != "policy_resource":
            continue
        state = row.values.get("state")
        states.append(state == "Compliant" if state in ("Compliant", "NonCompliant") else None)
    result["BI-SY-16"] = from_observations(policy_rows, states, "AI 관련 정책 평가 리소스 중 모든 평가가 Compliant인 비율")
    used_blueprints = {row.blueprint_id.lower() for row in identities if row.blueprint_id}
    linked_blueprints = [row for row in blueprints if row.blueprint_id.lower() in used_blueprints]
    result["DP-SY-19"] = measured([
        agent_has_entra_identity(agent, linked_blueprints) for agent in agents
    ], "전체 Azure Agent 중 구독·계정·프로젝트·Agent 이름으로 Blueprint 연결이 확인된 비율")
    result["OE-SY-20"] = measured([
        and_known(
            row.owner_count > 0 if row.owner_count is not None else None,
            row.sponsor_count > 0 if row.sponsor_count is not None else None,
        ) for row in identities
    ], "Agent ID 중 소유자와 스폰서가 모두 연결된 비율")
    result["OE-SY-21"] = measured([
        not row.overprivileged_roles if not any(role.startswith("unresolved:") for role in row.app_roles) else None
        for row in identities
    ], "Agent ID 중 내장 쓰기·전체제어 권한 패턴에 해당하는 앱 역할이 없는 비율")
    by_resource: dict[str, list[Any]] = {}
    for setting in data.logs:
        by_resource.setdefault(setting.resource_id.lower(), []).append(setting)
    result["OE-SY-22"] = measured([
        any(setting.enabled and bool(setting.workspace_id) for setting in by_resource[rid])
        if rid in by_resource else None for rid in sorted(targets(data))
    ], "대상 AI 계정·호스트 중 활성 로그와 Log Analytics workspace 연결이 있는 비율")
    identity_rows = observations(data, "OE-SY-23")
    result["OE-SY-23"] = from_observations(identity_rows, [
        and_known(
            bool(value.get("principal_count")) and any(
                part.strip().lower() in ("systemassigned", "userassigned")
                for part in str(value.get("identity_type")).split(",")
            ) if value.get("identity_type") is not None else None,
            value.get("privileged_assignments") == 0 if value.get("privileged_assignments") is not None else None,
            value.get("local_auth_disabled") if row.kind == "ai_account" else True,
        ) for row in identity_rows for value in [row.values]
    ], "관리 ID 연결·동일 구독 직접 광범위 역할 0건·AI 계정 키 인증 비활성을 충족한 비율")
    monitor = observations(data, "OE-SY-24")
    alerts = [row for row in monitor if row.values.get("kind") in (
        "metricalerts", "scheduledqueryrules", "activitylogalerts",
    ) and row.values.get("targets_ai")]
    covered = {
        rid.lower() for row in alerts if row.values.get("enabled") is True
        for rid in row.values.get("target_ids", [])
    }
    result["OE-SY-24"] = measured([rid in covered for rid in sorted(targets(data))],
                                                "대상 AI 계정·호스트 중 활성 경보의 실제 범위에 포함된 비율")
    result["OE-SY-25"] = from_observations(alerts, [
        row.values.get("action_group_resolved") if row.values.get("enabled") is True else False
        for row in alerts
    ], "AI 대상 경보 중 활성 상태이며 존재하는 작업 그룹과 활성 수신자가 연결된 비율")
    locations = {str(row.get("id", "")).lower(): row.get("location") for row in data.resources}
    retention = []
    for rid in sorted(targets(data)):
        settings = by_resource.get(rid)
        if not settings:
            retention.append(None)
            continue
        enabled = [row for row in settings if row.enabled]
        if not enabled:
            retention.append(False)
            continue
        values = [row.retention_days for row in enabled]
        retention.append(
            and_known(
                bool(locations[rid]) if rid in locations else None,
                min(values) >= criteria["workspace_retention_target_days"] if all(
                    numeric(value) for value in values
                ) else None,
            ),
        )
    result["OE-SY-26"] = measured(retention, "대상 중 리소스 지역이 식별되고 연결 workspace 보존 설정이 기준일 이상인 비율")
    metrics = {row["resource_id"].lower(): row for row in data.facts.get("resource_metrics", [])}
    samples = []
    for rid in sorted(targets(data)):
        row = metrics.get(rid)
        samples.append(
            any(numeric(value) for metric in row.get("metrics") or []
                for series in metric.get("timeseries") or [] for point in series.get("data") or []
                for key, value in point.items() if key != "timeStamp") if row is not None else None,
        )
    result["OT-SY-28"] = measured(samples, "대상 AI 계정·호스트 중 조회 기간에 수치 메트릭 표본이 있는 비율; 0 표본도 관측으로 포함")
    result["OT-SY-29"] = cost_measurement(data, agents)
    budget_values = []
    for sid in data.subscriptions:
        budgets = [row for row in data.budgets if row.subscription_id == sid]
        checks = [budget_configured(row, data.collected_at) for row in budgets]
        budget_values.append(True if True in checks else None if None in checks else False)
    result["OT-SY-31"] = measured(budget_values, "승인 구독 중 현재 유효한 무필터 Cost 예산·실제/예측 경보·수신자 구성이 있는 비율")
    for code in ("DS-SY-07", "OE-SY-23"):
        subjects = {row.subject.lower() for row in observations(data, code)}
        if subjects != targets(data):
            result[code].unavailable = "대상 AI 리소스의 구성 응답이 일부 누락됨"
    expected_hosts = {agent.resource_id.lower() for agent in agents
                      if agent.platform in HOSTED_AGENT_PLATFORMS and agent.resource_id}
    if {row.subject.lower() for row in versions} != expected_hosts:
        result["BI-SY-14"].unavailable = "자체 호스트 런타임 응답이 일부 누락됨"
    if not data.facts.get("deployment_inventory_complete"):
        result["BI-SY-13"].unavailable = result["DS-SY-06"].unavailable = "모델 배포 목록 수집 미완료"
    fields = (
        "agents", "deployments", "evaluations", "security", "logs", "budgets",
        "entra_blueprints", "entra_agent_identities", "proposal_observations", "costs",
    )
    refs = {ref for name in fields for row in getattr(data, name) for ref in row.evidence_refs}
    refs.update(row["evidence_ref"] for row in data.facts.get("resource_metrics", []) if row.get("evidence_ref"))
    for value in result.values():
        value.refs = sorted(set(value.refs) | refs)
    return result


def budget_configured(row: Any, now: datetime) -> bool | None:
    if row.period_start is None or row.period_end is None or row.filters_empty is None:
        return None
    return and_known(
        row.amount > 0 if row.amount is not None else None,
        row.category == "Cost" if row.category is not None else None,
        row.period_start <= now < row.period_end,
        row.filters_empty,
        row.actual_alerts > 0 if row.actual_alerts is not None else None,
        row.forecast_alerts > 0,
        row.notifications_with_receivers if row.notifications_with_receivers is not None else None,
    )


def cost_measurement(data: Collection, agents: list[Any]) -> Measurement:
    rows = data.costs
    currencies = {row.currency for row in rows}
    if not rows or len(currencies) != 1 or any(row.amount < 0 for row in rows):
        return Measurement(unavailable="비용 행 없음·통화 혼재·음수 조정", detail="직접 Agent 비용 귀속 금액 비율")
    total = sum(row.amount for row in rows)
    if total <= 0:
        return Measurement(unavailable="양수 비용 분모 없음", detail="직접 Agent 비용 귀속 금액 비율")
    allocated = 0.0
    for row in rows:
        matches = [agent for agent in agents if row.resource_id.lower() in {
            (agent.resource_id or "").lower(), (agent.model_resource_id or "").lower(),
            *[rid.lower() for rid in agent.cost_resource_ids],
        }]
        if len(matches) == 1 and row.usage_date is not None:
            allocated += row.amount
    return Measurement(total=total, compliant=allocated,
                       detail="동일 통화 양수 AI 비용 중 날짜가 있고 정확히 한 Agent에 귀속되는 금액 비율")


def blueprint_tags(tags: list[str]) -> dict[str, str]:
    return {key.lower(): value.lower() for key, _, value in (tag.partition(":") for tag in tags) if value}


def agent_has_entra_identity(agent: Any, blueprints: list[Any]) -> bool:
    if agent.platform != "foundry" or not agent.resource_id or not agent.subscription_id:
        return False
    parts = agent.resource_id.lower().split("/")
    if "accounts" not in parts or "projects" not in parts:
        return False
    if parts.index("accounts") + 1 >= len(parts) or parts.index("projects") + 1 >= len(parts):
        return False
    account, project = parts[parts.index("accounts") + 1], parts[parts.index("projects") + 1]
    return any(
        values.get("agentname") == agent.agent_name.lower() and values.get("projectname") == project
        and values.get("accountname") == account and values.get("subscriptionid") == agent.subscription_id.lower()
        for blueprint in blueprints for values in [blueprint_tags(blueprint.tags)]
    )
