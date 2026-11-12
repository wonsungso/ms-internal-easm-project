from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from wasm_agent.api_grading import targets
from wasm_agent.models import AZURE_AGENT_PLATFORMS, AgentEvidence, Collection


@dataclass(frozen=True)
class ResourceName:
    category: str
    name: str | None
    identifier: str
    subscription_id: str | None = None
    resource_group: str | None = None


def resource_names(data: Collection, code: str) -> list[ResourceName]:
    found: dict[tuple[str, str, str], ResourceName] = {}
    inventory = {str(row.get("id", "")).lower(): row for row in data.resources}

    def add(category: str, identifier: str, name: str | None = None, sid: str | None = None) -> None:
        if not identifier:
            return
        parts = identifier.strip("/").split("/")
        lower = [part.lower() for part in parts]
        group = None
        if len(parts) >= 2 and lower[0] == "subscriptions":
            sid = parts[1]
            if "resourcegroups" in lower and lower.index("resourcegroups") + 1 < len(parts):
                group = parts[lower.index("resourcegroups") + 1]
            if len(parts) > 2:
                name = name or inventory.get(identifier.lower(), {}).get("name") or parts[-1]
        found[(category, sid or "", identifier.lower())] = ResourceName(category, name, identifier, sid, group)

    def agent(row: AgentEvidence) -> None:
        category = {"foundry": "Foundry Agent", "langchain": "LangChain Agent", "custom": "자체 Agent"}[row.platform]
        # A Foundry project resource ID can be shared by multiple agents.
        identifier = (row.resource_id or "") + "#" + row.agent_id
        add(category, identifier, row.agent_name, row.subscription_id)

    agents = [row for row in data.agents if row.platform in AZURE_AGENT_PLATFORMS]
    if code in ("DM-SY-02", "BI-SY-10"):
        for read in data.admin_evidence:
            if read.source == "powerplatform.environments" and read.completed:
                for environment in read.environments:
                    add("Power Platform 환경", environment.environment_id, environment.display_name)
    elif code in ("DS-SY-05", "OE-SY-20", "OE-SY-21"):
        for row in data.entra_agent_identities:
            add("Entra Agent ID", row.identity_id, row.display_name)
        if code == "DS-SY-05":
            for blueprint in data.entra_blueprints:
                add("Blueprint", blueprint.blueprint_id, blueprint.display_name)
    elif code in ("DP-SY-17", "DP-SY-18"):
        for package in data.agent365_packages:
            add("Agent 365 패키지", package.package_id, package.display_name)
    elif code in ("DS-SY-06", "BI-SY-13"):
        for deployment in data.deployments:
            add("모델 배포", deployment.resource_id, deployment.name, deployment.subscription_id)
    elif code in ("DS-SY-08", "DS-SY-09"):
        for observation in data.proposal_observations:
            if observation.code != code:
                continue
            if code == "DS-SY-08" and not observation.values.get("mcp_approval_modes"):
                continue
            matches = [
                row for row in agents if row.subscription_id == observation.subscription_id
                and row.agent_id == observation.subject
            ]
            if len(matches) == 1:
                agent(matches[0])
            else:
                add("도구 선언 Agent ID", observation.subject, sid=observation.subscription_id)
            if code == "DS-SY-09":
                for host in observation.values.get("hosts", []):
                    if isinstance(host, str) and host:
                        add("외부 도구 호스트", host, host)
    elif code == "BI-SY-11":
        for project in data.facts.get("foundry_project_ids", []):
            add("Foundry 프로젝트", project)
        for run in data.evaluations:
            add("Foundry 프로젝트", run.project_id, sid=run.subscription_id)
            add("평가 실행 ID", run.run_id, sid=run.subscription_id)
    elif code == "BI-SY-12":
        for recommendation in data.security:
            if recommendation.status != "NotApplicable":
                add("보안 권고 대상", recommendation.resource_id, sid=recommendation.subscription_id)
    elif code in ("BI-SY-14", "BI-SY-15", "DP-SY-19"):
        for row in agents:
            agent(row)
    elif code in ("DS-SY-07", "BI-SY-16", "OE-SY-23"):
        categories = {
            "ai_account": "AI 계정", "agent_host": "Agent 호스트", "policy_resource": "정책 평가 대상",
        }
        for observation in data.proposal_observations:
            if observation.code == code and observation.kind in categories:
                add(categories[observation.kind], observation.subject, sid=observation.subscription_id)
    elif code in ("OE-SY-22", "OE-SY-24", "OE-SY-26", "OT-SY-28"):
        resource_ids = targets(data)
        for identifier in resource_ids:
            add("AI 리소스", identifier)
        if code in ("OE-SY-22", "OE-SY-26"):
            for log in data.logs:
                if log.resource_id.lower() not in resource_ids:
                    add("로그 연결 대상", log.resource_id, sid=log.subscription_id)
                if log.workspace_id:
                    add("Log Analytics", log.workspace_id)
    elif code == "OE-SY-25":
        for observation in data.proposal_observations:
            if observation.code == "OE-SY-24" and observation.values.get("targets_ai") and (
                observation.values.get("kind") in ("metricalerts", "scheduledqueryrules", "activitylogalerts")
            ):
                add("AI 경보", observation.subject, sid=observation.subscription_id)
    elif code == "OT-SY-29":
        for cost in data.costs:
            add("비용 리소스", cost.resource_id, sid=cost.subscription_id)
    elif code == "OT-SY-31":
        for budget in data.budgets:
            add("예산", budget.budget_id, sid=budget.subscription_id)
    return sorted(found.values(), key=lambda row: (
        row.category, (row.name or "").casefold(), row.identifier.casefold(),
    ))


def resource_summary(resources: list[ResourceName], limit: int = 3) -> str:
    if not resources:
        return "이름 목록 미확보"
    counts = Counter((row.category, (row.name or "").casefold()) for row in resources)
    labels = []
    for row in resources[:limit]:
        name = row.name or "이름 미확인"
        if counts[(row.category, (row.name or "").casefold())] > 1:
            name += f" [{row.subscription_id or row.identifier}; {row.resource_group or '테넌트/기타 범위'}]"
        labels.append(f"{row.category}: {name}")
    remainder = len(resources) - min(limit, len(resources))
    return "; ".join(labels) + (
        f"; 외 {remainder}개 (전체 {len(resources)}개)"
        if remainder else ""
    )
