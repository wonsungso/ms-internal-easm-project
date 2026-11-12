from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from urllib.parse import unquote, urlparse

from wasm_agent.models import (
    AZURE_AGENT_PLATFORMS,
    HOSTED_AGENT_PLATFORMS,
    Collection,
    TargetAssessment,
)

PROFILE = "api_configuration_v1"


@dataclass
class Measurement:
    total: float = 0
    compliant: float = 0
    detail: str = ""
    unavailable: str | None = None
    refs: list[str] = field(default_factory=list)
    decisions: list[TargetAssessment] = field(default_factory=list)
    unit: Literal["count", "amount"] = "count"
    currency: str | None = None

    @property
    def ratio(self) -> float | None:
        return self.compliant / self.total if self.total and not self.unavailable else None


def row_refs(rows: list[Any]) -> list[str]:
    return sorted({ref for row in rows for ref in row.evidence_refs})


def endpoint_refs(data: Collection, paths: list[str], fallback: list[str] | None = None) -> list[str]:
    if not data.evidence_sources:
        return fallback or []
    expected = {path.lower().rstrip("/") for path in paths}
    return sorted({
        ref for source in data.evidence_sources
        if urlparse(source.target).path.lower().rstrip("/") in expected for ref in source.evidence_refs
    })


def decision(subject: str, refs: list[str], **observed: Any) -> TargetAssessment:
    return TargetAssessment(subject=subject, evidence_refs=sorted(set(refs)), observed=observed)


def agent_refs(data: Collection, agent: Any) -> list[str]:
    if not data.evidence_sources:
        return agent.evidence_refs
    expected = f"/agents/{agent.agent_name}/versions".lower()
    endpoint = next((
        row["endpoint"] for row in data.facts.get("foundry_project_endpoints", [])
        if row["project_id"].lower() == (agent.resource_id or "").lower()
    ), None)
    return sorted({
        ref for source in data.evidence_sources
        if (
            agent.platform == "foundry" and unquote(urlparse(source.target).path).lower().endswith(expected)
            and (urlparse(source.target).netloc == urlparse(endpoint).netloc if endpoint else
                 any(ref in agent.evidence_refs for ref in source.evidence_refs))
            or agent.platform in HOSTED_AGENT_PLATFORMS
            and urlparse(source.target).path.lower() == "/providers/microsoft.resourcegraph/resources"
        ) for ref in source.evidence_refs
        if agent.platform == "foundry" or ref in agent.evidence_refs
    })


def inventory_refs(data: Collection, resource_id: str) -> list[str]:
    return sorted({
        ref for row in data.facts.get("inventory_evidence", [])
        if row["resource_id"].lower() == resource_id.lower() for ref in row["evidence_refs"]
    })


def project_evaluation_refs(data: Collection, project: str) -> list[str]:
    endpoint = next((
        row["endpoint"] for row in data.facts.get("foundry_project_endpoints", [])
        if row["project_id"].lower() == project.lower()
    ), None)
    if not endpoint:
        return row_refs([run for run in data.evaluations if run.project_id.lower() == project.lower()])
    prefix = endpoint.rstrip("/") + "/openai/v1/evals"
    return sorted({
        ref for source in data.evidence_sources
        if source.target.split("?")[0] == prefix or source.target.split("?")[0].startswith(prefix + "/")
        for ref in source.evidence_refs
    })


def tool_refs(data: Collection, observation: Any) -> list[str]:
    agents = [agent for agent in data.agents if agent.platform == "foundry"
              and agent.agent_id == observation.subject and agent.subscription_id == observation.subscription_id]
    return sorted({ref for agent in agents for ref in agent_refs(data, agent)}) if agents else observation.evidence_refs


def observation_refs(data: Collection, observation: Any) -> list[str]:
    properties = [
        ref for row in data.facts.get("target_property_evidence", [])
        if row["resource_id"].lower() == observation.subject.lower() for ref in row["evidence_refs"]
    ]
    if not properties:
        return observation.evidence_refs
    if observation.code == "OE-SY-23":
        return sorted(set(properties + endpoint_refs(
            data, [f"/subscriptions/{observation.subscription_id}/providers/Microsoft.Authorization/roleAssignments"],
            observation.evidence_refs,
        )))
    if observation.code == "DS-SY-07":
        host_refs = endpoint_refs(data, [observation.subject + "/config/web"]) if observation.kind == "agent_host" else []
        return sorted(set(properties + host_refs))
    return observation.evidence_refs


def measured(
    values: list[bool | None], detail: str, refs: list[str] | None = None,
    *, decisions: list[TargetAssessment] | None = None,
) -> Measurement:
    entries = decisions or []
    if decisions is not None and len(entries) != len(values):
        raise ValueError("대상별 판정과 계산 대상의 개수가 다릅니다.")
    for entry, value in zip(entries, values, strict=bool(entries)):
        entry.status = "compliant" if value is True else "non_compliant" if value is False else "unknown"
        entry.contribution = 1 if value is True else 0 if value is False else None
        entry.reason = (
            "필수 값 미확인" if value is None else
            "직접 증적 참조 미기록" if not entry.evidence_refs else
            "조건 미충족 - 확인한 설정·값 참조" if value is False else None
        )
    return Measurement(
        total=len(values), compliant=sum(value is True for value in values), detail=detail,
        unavailable="필수 API 필드 누락" if None in values else "대상 없음" if not values else None,
        refs=sorted(set(refs or []) | {ref for entry in entries for ref in entry.evidence_refs}),
        decisions=entries,
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


def from_observations(
    rows: list[Any], values: list[bool | None], detail: str, data: Collection,
) -> Measurement:
    return measured(values, detail, decisions=[
        decision(row.subject, observation_refs(data, row), **row.values) for row in rows
    ])


def measurements(
    data: Collection, criteria: dict[str, Any], tags: dict[str, Any],
) -> dict[str, Measurement]:
    result: dict[str, Measurement] = {}
    agents = [agent for agent in data.agents if agent.platform in AZURE_AGENT_PLATFORMS]
    identities, blueprints = data.entra_agent_identities, data.entra_blueprints
    blueprint_ids = {row.blueprint_id.lower() for row in blueprints}
    identity_list_path = "/v1.0/servicePrincipals/microsoft.graph.agentIdentity"
    blueprint_list_path = "/v1.0/applications/microsoft.graph.agentIdentityBlueprint"
    identity_refs = endpoint_refs(data, [identity_list_path], row_refs(identities))
    blueprint_refs = endpoint_refs(data, [blueprint_list_path], row_refs(blueprints))
    result["DS-SY-05"] = measured([
        bool(row.blueprint_id) and row.blueprint_id.lower() in blueprint_ids for row in identities
    ], "수집 Agent ID 중 실제 Blueprint ID가 수집 Blueprint 목록과 연결된 비율",
        identity_refs + blueprint_refs, decisions=[
            decision(row.identity_id, identity_refs + blueprint_refs,
                     agent_identity_blueprint_id=row.blueprint_id,
                     blueprint_exists=bool(row.blueprint_id) and row.blueprint_id.lower() in blueprint_ids)
            for row in identities
        ])
    result["DS-SY-06"] = measured([
        and_known(
            bool(row.model) if row.model is not None else None,
            bool(row.version) if row.version is not None else None,
            bool(row.format) if row.format is not None else None,
            row.version_upgrade_option in criteria["version_upgrade_options"]
            if row.version_upgrade_option is not None else None,
        ) for row in data.deployments
    ], "전체 모델 배포 중 모델·버전·형식과 인식 가능한 업데이트 옵션이 있는 비율",
        endpoint_refs(data, [row["id"] + "/deployments" for row in data.resources
                             if str(row.get("type", "")).lower() == "microsoft.cognitiveservices/accounts"]),
        decisions=[
        decision(row.resource_id, endpoint_refs(data, [row.account_id + "/deployments"], row.evidence_refs),
                 model=row.model, version=row.version, format=row.format,
                 version_upgrade_option=row.version_upgrade_option)
        for row in data.deployments
    ])
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
    result["DS-SY-07"] = from_observations(network, boundary, "대상 AI 계정·호스트 중 확인된 인바운드 경계 설정 비율", data)
    tool_rows = observations(data, "DS-SY-08")
    modes = [mode for row in tool_rows for mode in row.values.get("mcp_approval_modes", [])]
    result["DS-SY-08"] = measured(
        [mode == "always" if mode in ("always", "never", "custom") else None for mode in modes],
        "MCP 도구 선언 중 require_approval=always인 비율; 함수·내장 도구는 분모 제외",
        [ref for row in tool_rows for ref in tool_refs(data, row)], decisions=[
            decision(f"{row.subject}#MCP[{index}]", tool_refs(data, row), require_approval=mode)
            for row in tool_rows for index, mode in enumerate(row.values.get("mcp_approval_modes", []), 1)
        ],
    )
    result["DS-SY-08"].decisions.extend(TargetAssessment(
        subject=f"{row.subject}#non-MCP-tools", status="excluded",
        observed={"tool_types": [kind for kind in row.values.get("tool_types", []) if kind != "mcp"]},
        reason="함수·내장 도구는 MCP 비율 계산에서 제외", evidence_refs=tool_refs(data, row),
    ) for row in tool_rows if any(kind != "mcp" for kind in row.values.get("tool_types", [])))
    endpoints = observations(data, "DS-SY-09")
    result["DS-SY-09"] = measured(
        [value for row in endpoints for value in row.values.get("endpoint_https", [])],
        "명시된 외부 도구 URL 중 HTTPS이며 호스트가 유효하고 URL 내 인증정보가 없는 비율",
        [ref for row in endpoints for ref in tool_refs(data, row)], decisions=[
            decision(f"{row.subject}#URL[{index}]", tool_refs(data, row),
                     valid_https=value, hosts=row.values.get("hosts", []))
            for row in endpoints for index, value in enumerate(row.values.get("endpoint_https", []), 1)
        ],
    )
    complete_projects = set(data.facts.get("evaluation_complete_projects", []))
    project_ids = set(data.facts.get("foundry_project_ids", []))
    evaluated = {run.project_id.lower() for run in data.evaluations if (run.status or "").lower() in ("completed", "succeeded")}
    result["BI-SY-11"] = measured(
        [project.lower() in evaluated for project in sorted(project_ids)],
        "발견한 Foundry 프로젝트 중 완료 상태 평가 실행이 있는 프로젝트 비율",
        decisions=[
            decision(project, project_evaluation_refs(data, project),
                runs=[{"run_id": run.run_id, "status": run.status}
                      for run in data.evaluations if run.project_id.lower() == project.lower()])
            for project in sorted(project_ids)
        ],
    )
    if project_ids - complete_projects:
        result["BI-SY-11"].unavailable = "평가 목록 수집이 완료되지 않은 프로젝트가 있음"
    recommendations = [row for row in data.security if row.status != "NotApplicable"]
    result["BI-SY-12"] = measured([
        row.status == "Healthy" if row.status in ("Healthy", "Unhealthy") else None for row in recommendations
    ], "수집 AI 리소스 보안 권고 중 Healthy 비율; NotApplicable 제외",
        data.facts.get("security_evidence_refs", []), decisions=[
        decision(row.assessment_id, row.evidence_refs, resource_id=row.resource_id, status=row.status)
        for row in recommendations
    ])
    result["BI-SY-12"].decisions.extend(TargetAssessment(
        subject=row.assessment_id, status="excluded", observed={"resource_id": row.resource_id, "status": row.status},
        reason="적용 대상이 아닌 보안 권고", evidence_refs=row.evidence_refs,
    ) for row in data.security if row.status == "NotApplicable")
    safety_rows = observations(data, "BI-SY-13")
    policies = {row.subject.lower(): row.values["policy_filter_enabled"] for row in safety_rows
                if isinstance(row.values.get("policy_filter_enabled"), dict)}
    result["BI-SY-13"] = measured([
        policies[row.account_id.lower()].get(row.rai_policy, False)
        if row.account_id.lower() in policies else None for row in data.deployments
    ], "전체 모델 배포 중 연결 정책이 실제 목록에 존재하고 enabled 필터가 확인된 비율", decisions=[
        decision(row.resource_id,
                 endpoint_refs(data, [row.account_id + "/deployments"], row.evidence_refs)
                 + row_refs([policy for policy in safety_rows if policy.subject.lower() == row.account_id.lower()]),
                 rai_policy=row.rai_policy, filter_enabled=policies.get(row.account_id.lower(), {}).get(row.rai_policy))
        for row in data.deployments
    ])
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
    result["BI-SY-14"] = measured(
        pinned, "Foundry 버전과 자체 호스트 런타임 버전·컨테이너 다이제스트 고정 비율",
        decisions=[
            decision(agent.agent_id, agent_refs(data, agent), version=agent.agent_version)
            for agent in agents if agent.platform == "foundry"
        ] + [decision(row.subject, row.evidence_refs, **row.values) for row in versions],
    )
    result["BI-SY-15"] = measured([
        all((
            bool(agent.tags.get(tags["owner_key"]) or agent.owner),
            bool(agent.tags.get(tags["sponsor_key"]) or agent.sponsor),
            bool(agent.tags.get(tags["environment_key"])),
            bool(agent.tags.get(tags["cost_center_key"])),
        )) for agent in agents
    ], "전체 Azure Agent 중 owner·sponsor·환경·비용센터 4개 메타데이터가 모두 있는 비율", decisions=[
        decision(agent.agent_id, agent_refs(data, agent)
                 + endpoint_refs(data, [agent.resource_id or ""])
                 + inventory_refs(data, agent.resource_id or "")
                 + inventory_refs(data, (agent.resource_id or "").split("/projects/")[0]),
                 owner_present=bool(agent.tags.get(tags["owner_key"]) or agent.owner),
                 sponsor_present=bool(agent.tags.get(tags["sponsor_key"]) or agent.sponsor),
                 environment_present=bool(agent.tags.get(tags["environment_key"])),
                 cost_center_present=bool(agent.tags.get(tags["cost_center_key"])))
        for agent in agents
    ])
    policy_rows = [row for row in observations(data, "BI-SY-16") if row.kind == "policy_resource"]
    states: list[bool | None] = []
    for row in policy_rows:
        if row.kind != "policy_resource":
            continue
        state = row.values.get("state")
        states.append(state == "Compliant" if state in ("Compliant", "NonCompliant") else None)
    result["BI-SY-16"] = from_observations(policy_rows, states, "AI 관련 정책 평가 리소스 중 모든 평가가 Compliant인 비율", data)
    used_blueprints = {row.blueprint_id.lower() for row in identities if row.blueprint_id}
    linked_blueprints = [row for row in blueprints if row.blueprint_id.lower() in used_blueprints]
    result["DP-SY-19"] = measured([
        agent_has_entra_identity(agent, linked_blueprints) for agent in agents
    ], "전체 Azure Agent 중 구독·계정·프로젝트·Agent 이름으로 Blueprint 연결이 확인된 비율",
        identity_refs + blueprint_refs, decisions=[
            decision(agent.agent_id, agent_refs(data, agent) + identity_refs + blueprint_refs,
                     platform=agent.platform, subscription_id=agent.subscription_id,
                     resource_id=agent.resource_id, agent_name=agent.agent_name,
                     blueprint_linked=agent_has_entra_identity(agent, linked_blueprints))
            for agent in agents
        ])
    result["OE-SY-20"] = measured([
        and_known(
            row.owner_count > 0 if row.owner_count is not None else None,
            row.sponsor_count > 0 if row.sponsor_count is not None else None,
        ) for row in identities
    ], "Agent ID 중 소유자와 스폰서가 모두 연결된 비율", decisions=[
        decision(row.identity_id, endpoint_refs(data, [
            identity_list_path, f"/v1.0/servicePrincipals/{row.identity_id}/microsoft.graph.agentIdentity/owners",
            f"/v1.0/servicePrincipals/{row.identity_id}/microsoft.graph.agentIdentity/sponsors",
        ], row.evidence_refs), owner_count=row.owner_count, sponsor_count=row.sponsor_count)
        for row in identities
    ])
    result["OE-SY-21"] = measured([
        not row.overprivileged_roles if not any(role.startswith("unresolved:") for role in row.app_roles) else None
        for row in identities
    ], "Agent ID 중 내장 쓰기·전체제어 권한 패턴에 해당하는 앱 역할이 없는 비율", decisions=[
        decision(row.identity_id, endpoint_refs(data, [
            identity_list_path, f"/v1.0/servicePrincipals/{row.identity_id}/appRoleAssignments",
            *[urlparse(source.target).path for source in data.evidence_sources if "appRoles" in urlparse(source.target).query],
        ], row.evidence_refs), app_roles=row.app_roles, overprivileged_roles=row.overprivileged_roles)
        for row in identities
    ])
    by_resource: dict[str, list[Any]] = {}
    for setting in data.logs:
        by_resource.setdefault(setting.resource_id.lower(), []).append(setting)
    result["OE-SY-22"] = measured([
        any(setting.enabled and bool(setting.workspace_id) for setting in by_resource[rid])
        if rid in by_resource else None for rid in sorted(targets(data))
    ], "대상 AI 계정·호스트 중 활성 로그와 Log Analytics workspace 연결이 있는 비율", decisions=[
        decision(rid, endpoint_refs(data, [rid + "/providers/Microsoft.Insights/diagnosticSettings"],
                                    row_refs(by_resource.get(rid, []))),
                 log_settings=[{"enabled": setting.enabled, "workspace_id": setting.workspace_id}
                               for setting in by_resource.get(rid, [])])
        for rid in sorted(targets(data))
    ])
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
    ], "관리 ID 연결·동일 구독 직접 광범위 역할 0건·AI 계정 키 인증 비활성을 충족한 비율", data)
    monitor = observations(data, "OE-SY-24")
    alerts = [row for row in monitor if row.values.get("kind") in (
        "metricalerts", "scheduledqueryrules", "activitylogalerts",
    ) and row.values.get("targets_ai")]
    covered = {
        rid.lower() for row in alerts if row.values.get("enabled") is True
        for rid in row.values.get("target_ids", [])
    }
    monitor_refs = sorted(set(row_refs(monitor) + data.facts.get("monitoring_evidence_refs", [])))
    result["OE-SY-24"] = measured(
        [rid in covered for rid in sorted(targets(data))],
        "대상 AI 계정·호스트 중 활성 경보의 실제 범위에 포함된 비율", monitor_refs, decisions=[
            decision(rid, monitor_refs,
                     active_alert_ids=[row.subject for row in alerts if row.values.get("enabled") is True
                                       and rid in {value.lower() for value in row.values.get("target_ids", [])}])
            for rid in sorted(targets(data))
        ],
    )
    result["OE-SY-25"] = from_observations(alerts, [
        row.values.get("action_group_resolved") if row.values.get("enabled") is True else False
        for row in alerts
    ], "AI 대상 경보 중 활성 상태이며 존재하는 작업 그룹과 활성 수신자가 연결된 비율", data)
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
    result["OE-SY-26"] = measured(
        retention, "대상 중 리소스 지역이 식별되고 연결 workspace 보존 설정이 기준일 이상인 비율", decisions=[
            decision(rid, endpoint_refs(data, [
                rid + "/providers/Microsoft.Insights/diagnosticSettings",
                *[row.workspace_id for row in by_resource.get(rid, []) if row.workspace_id],
            ], row_refs(by_resource.get(rid, []))) + inventory_refs(data, rid), location=locations.get(rid),
                     target_retention_days=criteria["workspace_retention_target_days"],
                     log_settings=[{"enabled": row.enabled, "retention_days": row.retention_days,
                                    "workspace_id": row.workspace_id} for row in by_resource.get(rid, [])])
            for rid in sorted(targets(data))
        ],
    )
    metrics = {row["resource_id"].lower(): row for row in data.facts.get("resource_metrics", [])}
    samples = []
    for rid in sorted(targets(data)):
        row = metrics.get(rid)
        samples.append(
            any(numeric(value) for metric in row.get("metrics") or []
                for series in metric.get("timeseries") or [] for point in series.get("data") or []
                for key, value in point.items() if key != "timeStamp") if row is not None else None,
        )
    result["OT-SY-28"] = measured(
        samples, "대상 AI 계정·호스트 중 조회 기간에 수치 메트릭 표본이 있는 비율; 0 표본도 관측으로 포함",
        decisions=[
            decision(rid, [metrics[rid]["evidence_ref"]] if metrics.get(rid, {}).get("evidence_ref") else [],
                     numeric_sample_present=sample)
            for rid, sample in zip(sorted(targets(data)), samples, strict=True)
        ],
    )
    result["OT-SY-29"] = cost_measurement(data, agents)
    budget_values = []
    for sid in data.subscriptions:
        budgets = [row for row in data.budgets if row.subscription_id == sid]
        checks = [budget_configured(row, data.collected_at) for row in budgets]
        budget_values.append(True if True in checks else None if None in checks else False)
    result["OT-SY-31"] = measured(
        budget_values, "승인 구독 중 현재 유효한 무필터 Cost 예산·실제/예측 경보·수신자 구성이 있는 비율",
        decisions=[
            decision(sid, endpoint_refs(data, [f"/subscriptions/{sid}/providers/Microsoft.Consumption/budgets"],
                                       row_refs([row for row in data.budgets if row.subscription_id == sid])),
                     budgets=[{"budget_id": row.budget_id, "configured": budget_configured(row, data.collected_at),
                               "amount": row.amount, "category": row.category,
                               "filters_empty": row.filters_empty, "actual_alerts": row.actual_alerts,
                               "forecast_alerts": row.forecast_alerts,
                               "notifications_with_receivers": row.notifications_with_receivers,
                               "period_start": row.period_start.isoformat() if row.period_start else None,
                               "period_end": row.period_end.isoformat() if row.period_end else None}
                              for row in data.budgets if row.subscription_id == sid])
            for sid in data.subscriptions
        ],
    )
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
    for code in ("DS-SY-07", "OE-SY-23", "BI-SY-14"):
        expected = expected_hosts if code == "BI-SY-14" else targets(data)
        actual = {entry.subject.lower() for entry in result[code].decisions}
        result[code].decisions.extend(TargetAssessment(
            subject=subject, reason="대상 구성 응답 미확보",
        ) for subject in sorted(expected - actual))
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
        return Measurement(
            unavailable="비용 행 없음·통화 혼재·음수 조정", detail="직접 Agent 비용 귀속 금액 비율",
            unit="amount", refs=row_refs(rows), decisions=[
                TargetAssessment(subject=f"{row.resource_id}#{index}", reason="비용 계산 조건 미충족",
                                 observed={"amount": row.amount, "currency": row.currency, "usage_date": row.usage_date},
                                 evidence_refs=row.evidence_refs)
                for index, row in enumerate(rows, 1)
            ],
        )
    total = sum(row.amount for row in rows)
    if total <= 0:
        return Measurement(
            unavailable="양수 비용 분모 없음", detail="직접 Agent 비용 귀속 금액 비율",
            unit="amount", currency=next(iter(currencies)), refs=row_refs(rows),
            decisions=[TargetAssessment(
                subject=f"{row.resource_id}#{index}", status="excluded",
                observed={"amount": row.amount, "currency": row.currency, "usage_date": row.usage_date},
                reason="양수 비용 분모 없음", evidence_refs=row.evidence_refs,
            ) for index, row in enumerate(rows, 1)],
        )
    allocated = 0.0
    decisions = []
    for row in rows:
        matches = [agent for agent in agents if row.resource_id.lower() in {
            (agent.resource_id or "").lower(), (agent.model_resource_id or "").lower(),
            *[rid.lower() for rid in agent.cost_resource_ids],
        }]
        if len(matches) == 1 and row.usage_date is not None:
            allocated += row.amount
        compliant = len(matches) == 1 and row.usage_date is not None
        decisions.append(TargetAssessment(
            subject=f"{row.resource_id}#{len(decisions) + 1}",
            status="excluded" if row.amount == 0 else "compliant" if compliant else "non_compliant",
            observed={"resource_id": row.resource_id, "amount": row.amount, "currency": row.currency,
                      "usage_date": row.usage_date, "matching_agent_ids": [agent.agent_id for agent in matches]},
            contribution=row.amount if compliant else 0,
            reason="사용일자 없음 또는 단일 Agent 귀속 불가" if not compliant else None,
            evidence_refs=sorted(set(row.evidence_refs) | {
                ref for agent in matches for ref in agent_refs(data, agent)
            }),
        ))
    return Measurement(total=total, compliant=allocated,
                       detail="동일 통화 양수 AI 비용 중 날짜가 있고 정확히 한 Agent에 귀속되는 금액 비율",
                       unit="amount", currency=next(iter(currencies)), decisions=decisions,
                       refs=sorted({ref for entry in decisions for ref in entry.evidence_refs}))


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
