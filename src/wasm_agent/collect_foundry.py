from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlencode, urlparse

from wasm_agent.azure import AI_SCOPE, ARM, AccessError, ReaderHTTP, issue, redact, trusted_url
from wasm_agent.models import (
    AgentEvidence,
    Collection,
    EvaluationRun,
    ModelDeployment,
    ProposalObservation,
    Settings,
    timestamp,
)


def list_data(
    http: ReaderHTTP, endpoint: str, path: str, api_version: str | None = "v1",
) -> list[dict[str, Any]]:
    trusted_url(endpoint, AI_SCOPE)
    rows = []
    after = None
    seen = set()
    while True:
        params = {"limit": 100}
        if api_version:
            params["api-version"] = api_version
            params["order"] = "desc"
        if after:
            params["after"] = after
        payload = http.request("GET", endpoint.rstrip("/") + path + "?" + urlencode(params), AI_SCOPE)
        page = payload.get("data")
        if not isinstance(page, list) or not all(isinstance(row, dict) for row in page):
            raise AccessError("error", "Foundry v1 data 배열 형식 불일치")
        rows.extend(page)
        if not page or payload.get("has_more") is False:
            break
        after = payload.get("last_id")
        if not after:
            if payload.get("has_more"):
                raise AccessError("error", "Foundry 페이지 커서 없음")
            break
        if after in seen:
            raise AccessError("error", "Foundry 페이지 커서 반복")
        seen.add(after)
    return rows


class FoundryCollector:
    required_roles = ("Reader", "WASMAgent Foundry Evidence Reader v2")

    def tool_observations(
        self, project: dict[str, Any], record: AgentEvidence, raw_tools: Any,
    ) -> list[ProposalObservation]:
        tools = [tool for tool in raw_tools if isinstance(tool, dict)] if isinstance(raw_tools, list) else []
        refs = [self.http.last_ref] if self.http.last_ref else []
        if not tools:
            return []
        approvals = sorted({
            value if isinstance(value, str) else "custom"
            for tool in tools if tool.get("type") == "mcp"
            for value in [tool.get("require_approval", "unspecified")]
        })
        hosts = sorted({
            host for tool in tools
            for host in [urlparse(str(tool.get("server_url") or tool.get("url") or "")).hostname] if host
        })
        base = {"subscription_id": project["subscriptionId"], "subject": record.agent_id, "evidence_refs": refs}
        found = [ProposalObservation(
            code="DS-SY-08", kind="agent_tools",
            values={
                "tool_types": sorted({str(tool.get("type")) for tool in tools}), "mcp_approval": approvals,
                "mcp_approval_modes": [
                    tool.get("require_approval") if isinstance(tool.get("require_approval"), str)
                    else "custom" if isinstance(tool.get("require_approval"), dict) else None
                    for tool in tools if tool.get("type") == "mcp"
                ],
            },
            **base,
        )]
        urls = [
            str(tool.get("server_url") or tool.get("url"))
            for tool in tools if tool.get("server_url") or tool.get("url")
        ]
        if urls:
            found.append(ProposalObservation(
                code="DS-SY-09", kind="tool_endpoints", values={
                    "hosts": hosts,
                    "endpoint_https": [
                        parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username
                        and not parsed.password for url in urls for parsed in [urlparse(url)]
                    ],
                }, **base,
            ))
        return found

    def __init__(
        self, http: ReaderHTTP, resources: list[dict[str, Any]], settings: Settings, now: datetime,
    ) -> None:
        self.http, self.resources, self.settings, self.now = http, resources, settings, now

    def discover(self, subscriptions: Sequence[str]) -> Collection:
        result = Collection(collected_at=self.now)
        accounts = [
            row for row in self.resources
            if row["type"].lower() == "microsoft.cognitiveservices/accounts"
            and row.get("kind", "").lower() in ("aiservices", "openai")
            and row["subscriptionId"] in subscriptions
        ]
        projects = {
            entry.resource_id.lower(): {
                "id": entry.resource_id, "subscriptionId": entry.subscription_id,
                "endpoint": entry.endpoint, "tags": {},
            }
            for entry in self.settings.projects if entry.subscription_id in subscriptions
        }
        deployment_complete = True
        for account in accounts:
            sid, rid = account["subscriptionId"], account["id"]
            try:
                deployments = self.http.list_arm(ARM + rid + "/deployments?api-version=2024-10-01")
                for row in deployments:
                    properties = row.get("properties") or {}
                    model, sku = properties.get("model") or {}, row.get("sku") or {}
                    result.deployments.append(ModelDeployment(
                        subscription_id=sid, resource_id=row["id"], account_id=rid, name=row["name"],
                        model=model.get("name"), version=model.get("version"), format=model.get("format"),
                        sku=sku.get("name"), capacity=sku.get("capacity"),
                        state=properties.get("provisioningState"),
                        rai_policy=properties.get("raiPolicyName"),
                        version_upgrade_option=properties.get("versionUpgradeOption"),
                        evidence_refs=[self.http.last_ref] if self.http.last_ref else [],
                    ))
            except AccessError as exc:
                deployment_complete = False
                result.issues.append(issue(self.http, "model_deployments", rid, exc, ("Reader",)))
            if account.get("kind", "").lower() != "aiservices":
                continue
            try:
                for project in self.http.list_arm(ARM + rid + "/projects?api-version=2025-06-01"):
                    detail = self.http.request("GET", ARM + project["id"] + "?api-version=2025-06-01")
                    endpoints = (detail.get("properties") or {}).get("endpoints") or {}
                    candidates = [
                        value for value in endpoints.values()
                        if isinstance(value, str) and "/api/projects/" in value
                    ]
                    existing = projects.get(project["id"].lower())
                    endpoint = existing["endpoint"] if existing else (candidates[0] if candidates else None)
                    if not endpoint:
                        raise AccessError("not_found", "프로젝트 ARM 응답에 데이터 endpoint가 없음")
                    projects[project["id"].lower()] = {
                        "id": project["id"], "subscriptionId": sid, "endpoint": endpoint,
                        "tags": {**(account.get("tags") or {}), **(detail.get("tags") or {})},
                    }
            except AccessError as exc:
                result.issues.append(issue(self.http, "foundry_projects", rid, exc, self.required_roles))
        result.facts["deployment_inventory_complete"] = deployment_complete
        complete_projects = []
        for project in projects.values():
            if project["subscriptionId"] not in subscriptions:
                continue
            endpoint = project["endpoint"]
            try:
                rows = list_data(
                    self.http, endpoint,
                    "/agents" if self.settings.foundry_profile == "agents_v1" else "/assistants",
                )
                for row in rows:
                    if self.settings.foundry_profile == "classic_v1":
                        versions = [row]
                    else:
                        versions = list_data(
                            self.http, endpoint, "/agents/" + quote(row["name"], safe="") + "/versions",
                        )
                    for version in versions[:1]:
                        definition = version.get("definition") or version
                        metadata = version.get("metadata") or {}
                        tags = {**project["tags"], **{
                            key: value for key, value in metadata.items() if isinstance(value, str)
                        }}
                        model_name = definition.get("model")
                        matching = [
                            item for item in result.deployments
                            if item.name == model_name and project["id"].lower().startswith(item.account_id.lower() + "/")
                        ]
                        raw_tools = definition.get("tools")
                        tool_types = [
                            tool.get("type") or tool.get("kind") for tool in raw_tools
                        ] if isinstance(raw_tools, list) else None
                        if tool_types is not None and any(value is None for value in tool_types):
                            tool_types = None
                        record = AgentEvidence(
                            collected_at=self.now, tenant_id=self.settings.tenant_id,
                            subscription_id=project["subscriptionId"], platform="foundry",
                            resource_group=project["id"].split("/")[4],
                            agent_id=row["id"], agent_name=version.get("name") or row["name"],
                            agent_version=version.get("version"),
                            resource_id=project["id"], hosting_type="Microsoft Foundry Agent Service",
                            owner=redact(tags.get("owner")), sponsor=redact(tags.get("sponsor")),
                            tags=redact(tags), model=matching[0].model if len(matching) == 1 else model_name,
                            model_version=matching[0].version if len(matching) == 1 else None,
                            model_resource_id=matching[0].account_id if len(matching) == 1 else None,
                            guardrail_applied=True if len(matching) == 1 and matching[0].rai_policy else None,
                            tools=tool_types,
                            created_at=timestamp(version.get("created_at")),
                            detection_confidence="tag",
                            evidence_refs=[self.http.last_ref] if self.http.last_ref else [],
                            se_codes=["DS-SY-06", "BI-SY-11", "BI-SY-12", "OE-SY-22", "OT-SY-28", "OT-SY-29"],
                        ).mark_unknowns()
                        record.unavailable(
                            "deployed_at", "not_found",
                            "Agent 버전 생성 시각은 실제 운영 배포 시각의 증거가 아님",
                        )
                        result.agents.append(record)
                        result.proposal_observations.extend(
                            self.tool_observations(project, record, raw_tools),
                        )
            except AccessError as exc:
                result.issues.append(issue(self.http, "foundry_agents", project["id"], exc, self.required_roles))
            try:
                evaluations = list_data(self.http, endpoint, "/openai/v1/evals", api_version=None)
                for evaluation in evaluations:
                    for run in list_data(
                        self.http, endpoint, "/openai/v1/evals/" + quote(evaluation["id"], safe="") + "/runs",
                        api_version=None,
                    ):
                        metadata = run.get("metadata") or {}
                        counts = run.get("result_counts") or {}
                        result.evaluations.append(EvaluationRun(
                            subscription_id=project["subscriptionId"], project_id=project["id"],
                            run_id=run["id"], status=run.get("status"),
                            agent_id=metadata.get("agent_id"), agent_version=metadata.get("agent_version"),
                            completed_at=timestamp(run.get("completed_at")),
                            passed_items=counts.get("passed"), failed_items=counts.get("failed"),
                            errored_items=counts.get("errored"), total_items=counts.get("total"),
                            evidence_refs=[self.http.last_ref] if self.http.last_ref else [],
                        ))
                complete_projects.append(project["id"])
            except AccessError as exc:
                result.issues.append(issue(self.http, "foundry_evaluations", project["id"], exc, self.required_roles))
        result.facts["evaluation_complete_projects"] = complete_projects
        result.facts["foundry_project_ids"] = [project["id"] for project in projects.values()]
        result.facts["foundry_project_endpoints"] = [
            {"project_id": project["id"], "endpoint": project["endpoint"]} for project in projects.values()
        ]
        return result
