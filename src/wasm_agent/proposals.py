from __future__ import annotations

from collections import Counter
from typing import Any

from wasm_agent.models import Collection, Issue, ProposalFinding, ProposalObservation, Reason

TITLES = {
    "BI-SY-15": "Agent 자산 대장·책임 태그",
    "OE-SY-23": "관리 ID와 ARM 역할 범위",
    "DS-SY-07": "네트워크 경계와 공용 접근",
    "BI-SY-13": "Content Safety 정책 연결",
    "OE-SY-24": "관측·경보 구성",
    "DS-SY-08": "도구 구성과 승인 모드",
    "DS-SY-09": "외부 도구 엔드포인트",
    "OE-SY-25": "경보 전달 경로(작업 그룹)",
    "OT-SY-31": "예산·예측 경보",
    "OE-SY-26": "지역과 보존 설정",
    "BI-SY-16": "Azure 정책 준수 상태",
    "BI-SY-14": "릴리스 버전 고정·런타임",
}
# (주 영역, 보조 영역, 근거): 영역 정의와 질문은 평가 모델 Excel '2. 질문 및 확인사항' 기준
DOMAINS = {
    "BI-SY-15": ("3. Build", "4. Deploy", "개발·배포 시 Agent 자산 대장과 책임 태그(Owner·Sponsor) 표준을 적용(Build 개발 표준). 배포 후 현황 점검은 Deploy·Optimize 보조"),
    "OE-SY-23": ("5. Operate", "4. Deploy", "Agent 권한의 정기 검토·회수와 권한 현황 관리(Operate 질문)"),
    "DS-SY-07": ("2. Design", "3. Build", "실행 환경·플랫폼과 보안 요건을 정하는 기술 설계 리뷰(Design 질문). 환경 분리는 Build 보조"),
    "BI-SY-13": ("3. Build", "2. Design", "데이터 유출·유해 입출력 등 보안 위협을 배포 전에 점검하는 개발 및 검증(Build 질문)"),
    "OE-SY-24": ("5. Operate", "6. Optimize", "Agent의 비정상 행동을 자동 탐지하는 수단과 장애 감시(Operate 기술)"),
    "DS-SY-08": ("2. Design", "3. Build", "Agent 자율성 수준(조회 전용·사람 승인 후 실행·자율 실행)을 설계 단계에서 결정(Design 질문)"),
    "DS-SY-09": ("2. Design", "5. Operate", "외부 연계(커넥터·API·MCP)의 허용 기준과 사전 승인 목록(Design 기술)"),
    "OE-SY-25": ("5. Operate", "", "장애 접수와 보안 사고 시 즉시 중지·격리하는 긴급 절차(Operate 질문)"),
    "OT-SY-31": ("6. Optimize", "", "Agent별·조직별 비용 산정과 자동 측정 체계(Optimize 질문)"),
    "OE-SY-26": ("5. Operate", "2. Design", "로그·운영 기록의 보존·삭제 관리(OE-SY-22 보완). 데이터 지역 결정은 Design 보조"),
    "BI-SY-16": ("3. Build", "4. Deploy", "개발·테스트·운영 환경 구성을 Azure Policy로 통제(Build 기술: 환경 분리). 승인되지 않은 구성의 배포 제한은 Deploy 보조"),
    "BI-SY-14": ("3. Build", "5. Operate", "프롬프트·설정·모델·소스의 버전 관리(Build 기술). 변경 승인과 원복은 Deploy·Operate 보조"),
}
PRODUCTS = {
    "BI-SY-15": "Azure 리소스 태그", "OE-SY-23": "Azure Resource Graph, Azure RBAC",
    "DS-SY-07": "Azure AI Services, App Service", "BI-SY-13": "Microsoft Foundry - 콘텐츠 필터",
    "OE-SY-24": "Azure Monitor",
    "DS-SY-08": "Microsoft Foundry Agent 정의", "DS-SY-09": "Microsoft Foundry Agent 정의",
    "OE-SY-25": "Azure Monitor - 작업 그룹", "OT-SY-31": "Azure Cost Management",
    "OE-SY-26": "Azure 리소스 위치, Log Analytics", "BI-SY-16": "Azure Policy",
    "BI-SY-14": "Azure OpenAI 배포, App Service",
}
LIMITS = {
    "BI-SY-15": "태그 존재 여부만 확인. 승인된 자산 대장과의 대사와 업무 목적·변경 이력은 고객 제출 자료가 필요함",
    "OE-SY-23": "관리 ID 연결과 동일 구독의 직접 ARM 역할 할당만 확인. 타 구독·상속·Graph·데이터 평면 권한과 실제 인증 사용은 별도 검증 필요",
    "DS-SY-07": "ARM 네트워크 설정만 확인. 실제 연결 차단, 앱 내부 우회, 송신 허용 목록 검증은 확인 불가",
    "BI-SY-13": "정책 연결과 구성만 확인. 필터의 실제 방어 효과와 입력·출력 시험 결과는 확인 불가",
    "OE-SY-24": "경보 규칙과 Application Insights 존재만 확인. 계측·샘플링·SLO 승인과 대응 이력은 확인 불가",
    "DS-SY-08": "Foundry Agent 정의의 도구 유형과 MCP 승인 모드만 확인. 승인 우회 방지와 실행 주체 귀속은 확인 불가",
    "DS-SY-09": "Foundry Agent 정의의 도구 엔드포인트 호스트만 확인(경로·쿼리 제외). 승인 목록 대조와 인증 방식은 확인 불가",
    "OE-SY-25": "작업 그룹 수신자 유형 수와 경보 연결만 확인(주소 미수집). SOC 수신, 중단·복구 훈련은 확인 불가",
    "OT-SY-31": "구독 예산의 예측 경보 설정만 확인. Agent 단위 비용 귀속과 통보 후 조치 이력은 확인 불가",
    "OE-SY-26": "리소스 위치와 로그 보존 설정만 확인. 실제 처리 지역, 앱 메모리, 삭제 검증은 확인 불가",
    "BI-SY-16": "정책 준수 상태만 확인. 예외 만료 승인과 편차 검토 기록은 확인 불가. 정책 준수가 앱 동작 안전을 보장하지 않음",
    "BI-SY-14": "배포 메타데이터의 런타임·모델 버전 업그레이드 옵션만 확인. 소스·빌드 출처와 SDK 승인은 확인 불가",
}
ISSUE_COLLECTORS = {
    "OE-SY-23": ("proposal_OE-SY-23",), "DS-SY-07": ("proposal_DS-SY-07",), "BI-SY-13": ("proposal_BI-SY-13", "model_deployments"),
    "OE-SY-24": ("proposal_OE-SY-24",), "DS-SY-08": ("foundry_agents",),
    "DS-SY-09": ("foundry_agents",), "OE-SY-25": ("proposal_OE-SY-24",), "OT-SY-31": ("budgets",),
    "OE-SY-26": ("logs", "subscription"), "BI-SY-16": ("proposal_BI-SY-16",),
    "BI-SY-14": ("proposal_DS-SY-07", "model_deployments"),
}
PRIORITY = {"permission_denied": 0, "error": 1, "license_missing": 2, "feature_unavailable": 3, "not_found": 4}


def observations(data: Collection, code: str) -> list[ProposalObservation]:
    return [item for item in data.proposal_observations if item.code == code]


def count(values: list[Any]) -> int:
    return sum(1 for value in values if value)


def azure_agents(data: Collection) -> list[Any]:
    return [agent for agent in data.agents if agent.platform in ("foundry", "langchain")]


def build(code: str, data: Collection, tags: dict[str, Any]) -> tuple[dict[str, Any], str, bool]:
    """Return metrics, a one-line Korean summary and whether any evidence was collected."""
    if code == "BI-SY-15":
        agents = azure_agents(data)
        keys = {
            "owner": tags["owner_key"], "sponsor": tags["sponsor_key"], "env": tags["environment_key"],
            "cost_center": tags["cost_center_key"],
        }
        metrics: dict[str, Any] = {"agents": len(agents)}
        for name, key in keys.items():
            metrics[f"with_{name}"] = sum(
                1 for agent in agents
                if agent.tags.get(key) or (name == "owner" and agent.owner) or (name == "sponsor" and agent.sponsor)
            )
        return metrics, (
            f"Azure Agent {len(agents)}개 중 소유자 {metrics['with_owner']}, 후원자 {metrics['with_sponsor']}, "
            f"환경 {metrics['with_env']}, 비용센터 {metrics['with_cost_center']}개에 태그가 있음"
        ), bool(agents)
    if code == "OE-SY-23":
        rows = [item.values for item in observations(data, code)]
        accounts = [item.values for item in observations(data, code) if item.kind == "ai_account"]
        metrics = {
            "subjects": len(rows),
            "with_managed_identity": count([
                isinstance(row.get("identity_type"), str)
                and any(part.strip().lower() in ("systemassigned", "userassigned")
                        for part in row["identity_type"].split(","))
                for row in rows
            ]),
            "assignments": sum(row["assignments"] for row in rows),
            "privileged_assignments": sum(row["privileged_assignments"] for row in rows),
            "subscription_scope_assignments": sum(row["subscription_scope_assignments"] for row in rows),
            "accounts": len(accounts),
            "accounts_local_auth_disabled": count([row["local_auth_disabled"] for row in accounts]),
        }
        return metrics, (
            f"대상 {metrics['subjects']}개 중 관리 ID {metrics['with_managed_identity']}개, 동일 구독 직접 ARM 역할 할당 "
            f"{metrics['assignments']}건(Owner/Contributor 등 광범위 역할 {metrics['privileged_assignments']}건, "
            f"구독 범위 {metrics['subscription_scope_assignments']}건), AI 계정 {metrics['accounts']}개 중 "
            f"키 인증 비활성 {metrics['accounts_local_auth_disabled']}개"
        ), bool(rows)
    if code == "DS-SY-07":
        rows = observations(data, code)
        accounts = [item.values for item in rows if item.kind == "ai_account"]
        hosts = [item.values for item in rows if item.kind == "agent_host"]
        metrics = {
            "accounts": len(accounts),
            "accounts_public": count([row["public_network_access"] == "Enabled" for row in accounts]),
            "accounts_default_deny": count([row["default_action"] == "Deny" for row in accounts]),
            "accounts_private_endpoint": count([(row["private_endpoints"] or 0) > 0 for row in accounts]),
            "hosts": len(hosts),
            "hosts_https_only": count([row["https_only"] for row in hosts]),
            "hosts_vnet_integrated": count([row["vnet_integrated"] for row in hosts]),
            "hosts_ip_restricted": count([(row["ip_restrictions"] or 0) > 0 for row in hosts]),
        }
        return metrics, (
            f"AI 계정 {metrics['accounts']}개 중 공용 접근 허용 {metrics['accounts_public']}, 기본 거부 "
            f"{metrics['accounts_default_deny']}, 프라이빗 엔드포인트 {metrics['accounts_private_endpoint']}개. "
            f"Agent 호스트 {metrics['hosts']}개 중 HTTPS 전용 {metrics['hosts_https_only']}, VNet 통합 "
            f"{metrics['hosts_vnet_integrated']}, 비기본 IP 제한 규칙 보유 {metrics['hosts_ip_restricted']}개"
        ), bool(rows)
    if code == "BI-SY-13":
        rows = observations(data, code)
        custom = {
            item.subject.lower(): set(item.values.get("custom_policy_names") or []) for item in rows
        }
        deployments = data.deployments
        metrics = {
            "accounts": len(rows),
            "custom_policies": sum(item.values["custom_policies"] for item in rows),
            "deployments": len(deployments),
            "with_policy": count([item.rai_policy for item in deployments]),
            "with_custom_policy": sum(
                1 for item in deployments if item.rai_policy in custom.get(item.account_id.lower(), set())
            ),
        }
        return metrics, (
            f"모델 배포 {metrics['deployments']}개 중 정책 연결 {metrics['with_policy']}개, 사용자 지정 정책 "
            f"연결 {metrics['with_custom_policy']}개 (사용자 지정 정책 {metrics['custom_policies']}개)"
        ), bool(rows)
    if code in ("OE-SY-24", "OE-SY-25"):
        rows = observations(data, "OE-SY-24")
        alerts = [item.values for item in rows if item.values.get("kind") in (
            "metricalerts", "scheduledqueryrules", "activitylogalerts",
        )]
        groups = [item.values for item in rows if item.values.get("kind") == "actiongroups"]
        components = [item.values for item in rows if item.values.get("kind") == "components"]
        if code == "OE-SY-24":
            metrics = {
                "alert_rules": len(alerts), "enabled": count([row["enabled"] for row in alerts]),
                "targeting_ai": count([row["targets_ai"] for row in alerts]),
                "application_insights": len(components),
                "diagnostic_settings_enabled": count([entry.enabled for entry in data.logs]),
            }
            return metrics, (
                f"경보 규칙 {metrics['alert_rules']}개(활성 {metrics['enabled']}, AI 리소스 대상 "
                f"{metrics['targeting_ai']}개), Application Insights {metrics['application_insights']}개, "
                f"활성 진단 설정 {metrics['diagnostic_settings_enabled']}개"
            ), bool(rows) or bool(data.logs)
        types: Counter[str] = Counter()
        for row in groups:
            types.update({key: 1 for key in row.get("receivers", {})})
        metrics = {
            "action_groups": len(groups), "with_receivers": count([row.get("receivers") for row in groups]),
            "receiver_types": dict(types),
            "alerts_with_action_group": count([row["has_action_group"] for row in alerts]),
        }
        return metrics, (
            f"작업 그룹 {metrics['action_groups']}개(수신자 보유 {metrics['with_receivers']}개, 유형 "
            f"{', '.join(sorted(types)) or '없음'}), 작업 그룹에 연결된 경보 {metrics['alerts_with_action_group']}개"
        ), bool(rows)
    if code == "DS-SY-08":
        agents = azure_agents(data)
        rows = observations(data, code)
        types = Counter(tool for item in rows for tool in item.values["tool_types"])
        approvals = Counter(value for item in rows for value in item.values["mcp_approval"])
        metrics = {
            "agents": len(agents), "agents_with_tools": len(rows), "tool_types": dict(types),
            "mcp_approval": dict(approvals),
        }
        return metrics, (
            f"Azure Agent {len(agents)}개 중 도구 보유 {len(rows)}개 (유형 "
            f"{', '.join(f'{key} {value}' for key, value in sorted(types.items())) or '없음'}; "
            f"MCP 승인 모드 {', '.join(f'{key} {value}' for key, value in sorted(approvals.items())) or '해당 없음'})"
        ), bool(agents)
    if code == "DS-SY-09":
        rows = observations(data, code)
        hosts = sorted({host for item in rows for host in item.values["hosts"]})
        metrics = {"agents_with_endpoints": len(rows), "hosts": hosts}
        return metrics, (
            f"외부 도구 엔드포인트를 가진 Agent {len(rows)}개, 호스트 {len(hosts)}종"
            + (f" ({', '.join(hosts)})" if hosts else "")
        ), bool(azure_agents(data))
    if code == "OT-SY-31":
        budgets = data.budgets
        metrics = {
            "subscriptions": len(data.subscriptions), "budgets": len(budgets),
            "with_alerts": count([item.enabled_alerts for item in budgets]),
            "with_forecast_alert": count([item.forecast_alerts for item in budgets]),
        }
        return metrics, (
            f"구독 {metrics['subscriptions']}개에서 예산 {metrics['budgets']}개 (경보 설정 {metrics['with_alerts']}개, "
            f"예측 경보 {metrics['with_forecast_alert']}개)"
        ), bool(data.facts.get("budget_complete_subscriptions"))
    if code == "OE-SY-26":
        interesting = (
            "microsoft.cognitiveservices/accounts", "microsoft.web/sites", "microsoft.app/containerapps",
            "microsoft.operationalinsights/workspaces",
        )
        locations = sorted({
            str(row.get("location", "")).lower() for row in data.resources
            if str(row.get("type", "")).lower() in interesting and row.get("location")
        })
        retention = sorted({
            entry.retention_days for entry in data.logs if entry.retention_days is not None
        } | {
            item.values["retention_days"] for item in observations(data, "OE-SY-24")
            if item.values.get("retention_days") is not None
        })
        metrics = {"regions": locations, "retention_days": retention}
        return metrics, (
            f"사용 지역 {len(locations)}곳({', '.join(locations) or '없음'}), 로그·Application Insights 보존 "
            f"설정값 {', '.join(str(value) + '일' for value in retention) or '확인 자료 없음'}"
        ), bool(locations)
    if code == "BI-SY-16":
        rows = observations(data, code)
        states: Counter[str] = Counter()
        for item in rows:
            states[item.values["state"]] += item.values["resources"]
        metrics = {"resources_by_state": dict(states), "subscriptions_checked": len(
            data.facts.get("proposal_policy_subscriptions", [])
        )}
        return metrics, (
            "AI 관련 리소스 정책 준수 상태: "
            + (", ".join(f"{key} {value}개" for key, value in sorted(states.items())) or "평가 결과 0건(할당 없음 또는 평가 전)")
        ), bool(data.facts.get("proposal_policy_subscriptions"))
    rows = observations(data, "BI-SY-14")
    options = Counter(item.version_upgrade_option or "unknown" for item in data.deployments)
    runtimes = [item.values.get("runtime") for item in rows if item.values.get("runtime")]
    images = [item.values for item in rows if item.values.get("image")]
    metrics = {
        "model_deployments": len(data.deployments), "version_upgrade_option": dict(options),
        "hosts": len(rows), "hosts_with_runtime": len(runtimes),
        "container_images": len(images),
        "images_pinned_by_digest": count([item.get("pinned_by_digest") for item in images]),
    }
    return metrics, (
        f"모델 배포 {metrics['model_deployments']}개의 버전 업그레이드 옵션 "
        f"{', '.join(f'{key} {value}' for key, value in sorted(options.items())) or '없음'}; "
        f"호스트 {metrics['hosts']}개 중 런타임 확인 {metrics['hosts_with_runtime']}개, 이미지 다이제스트 고정 "
        f"{metrics['images_pinned_by_digest']}/{metrics['container_images']}개"
    ), bool(rows) or bool(data.deployments)


def evaluate_proposals(data: Collection, tags: dict[str, Any]) -> list[ProposalFinding]:
    findings = []
    for code, title in TITLES.items():
        metrics, summary, has_data = build(code, data, tags)
        wanted = ISSUE_COLLECTORS.get(code, ())
        issues: list[Issue] = [item for item in data.issues if item.collector in wanted]
        incomplete = code in (data.facts.get("proposal_incomplete") or [])
        reason: Reason | None = None
        if issues:
            reason = min(issues, key=lambda item: PRIORITY[item.reason]).reason
        if issues and not has_data:
            status = "수집 불가"
        elif issues or incomplete:
            status = "일부 수집"
        elif not has_data:
            status, reason = "수집 불가", "not_found"
        else:
            status = "수집됨"
        if status == "수집 불가":
            summary = (
                "수집하지 못함: " + "; ".join(sorted({item.detail for item in issues}))
                if issues else "조회 대상 또는 수집 증적 미확보 - 0점이나 통제 부재로 확정하지 않음"
            )
        elif issues:
            summary += "; 일부 실패: " + "; ".join(sorted({item.detail for item in issues}))
        refs = sorted({ref for item in observations(data, code) for ref in item.evidence_refs})
        findings.append(ProposalFinding(
            code=code, title=title, area=DOMAINS[code][0], status=status, metrics=metrics, observation=summary,
            limit=LIMITS[code] + ". Level은 6. 수집 결과에서 증적 포함 기준으로 판정", reason=reason,
            evidence_refs=refs,
        ))
    return findings
