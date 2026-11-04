from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from wasm_agent.azure import ARM, GRAPH_URL, LOG_SCOPE, AccessError, ReaderHTTP, issue
from wasm_agent.models import (
    Budget,
    Collection,
    CostRecord,
    LogSetting,
    PolicyAssignment,
    SecureScore,
    SecurityRecommendation,
    Usage,
    timestamp,
    try_timestamp,
)

_when = try_timestamp


class SignalCollector:
    required_roles = ("Reader", "Cost Management Reader", "Log Analytics Reader", "Security Reader")

    def __init__(
        self, http: ReaderHTTP, base: Collection, now: datetime,
        criteria: dict[str, Any], monitor: dict[str, list[str]],
        allowed_subscriptions: Sequence[str] | None = None,
    ) -> None:
        self.http, self.base, self.now, self.criteria, self.monitor = http, base, now, criteria, monitor
        self.allowed_subscriptions = {sid.lower() for sid in (allowed_subscriptions or base.subscriptions)}

    def discover(self, subscriptions: Sequence[str]) -> Collection:
        result = Collection(collected_at=self.now)
        for sid in subscriptions:
            for name, operation in [
                ("cost", self.costs), ("logs", self.logs), ("metrics", self.metrics), ("security", self.security),
                ("secure_score", self.secure_score), ("policies", self.policies), ("budgets", self.budgets),
            ]:
                try:
                    operation(sid, result)
                except AccessError as exc:
                    roles = {
                        "cost": ("Reader", "Cost Management Reader"),
                        "logs": ("Reader", "Log Analytics Reader"),
                        "metrics": ("Reader", "Monitoring Reader"),
                        "security": ("Reader", "Security Reader"),
                        "secure_score": ("Reader", "Security Reader"),
                        "policies": ("Reader",),
                        "budgets": ("Reader", "Cost Management Reader"),
                    }[name]
                    result.issues.append(issue(self.http, name, sid, exc, roles))
                    if name == "cost":
                        for agent in self.base.agents:
                            if agent.subscription_id == sid and agent.cost_30d is None:
                                agent.unavailable("cost_30d", exc.reason, str(exc))
        return result

    def ai_ids(self, sid: str) -> set[str]:
        ids = {
            row["id"].lower() for row in self.base.resources
            if row["subscriptionId"] == sid
            and row["type"].lower() == "microsoft.cognitiveservices/accounts"
            and row.get("kind", "").lower() in ("aiservices", "openai")
        }
        ids.update(
            rid.lower() for agent in self.base.agents
            if agent.subscription_id == sid and agent.platform == "langchain"
            for rid in agent.cost_resource_ids
        )
        ids.update(
            row["id"].lower() for row in self.base.resources
            if row["subscriptionId"] == sid
            and (row.get("tags") or {}).get("agent-type") == "shared-observability"
        )
        return ids

    def costs(self, sid: str, result: Collection) -> None:
        ids = sorted(self.ai_ids(sid))
        if not ids:
            raise AccessError("not_found", "비용 분모에 포함할 Azure AI/자체 Agent 리소스가 없음")
        body = {
            "type": "Usage", "timeframe": "Custom",
            "timePeriod": {
                "from": (self.now - timedelta(days=self.criteria["cost_window_days"])).isoformat(),
                "to": self.now.isoformat(),
            },
            "dataset": {
                "granularity": "Daily",
                "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
                "grouping": [{"type": "Dimension", "name": "ResourceId"}],
                "filter": {"dimensions": {"name": "ResourceId", "operator": "In", "values": ids}},
            },
        }
        url = ARM + f"/subscriptions/{sid}/providers/Microsoft.CostManagement/query?api-version=2023-03-01"
        seen = set()
        while url:
            if url in seen:
                raise AccessError("error", "비용 페이지 링크 반복")
            seen.add(url)
            properties = self.http.request("POST", url, body=body).get("properties") or {}
            columns = {entry["name"].lower(): index for index, entry in enumerate(properties.get("columns", []))}
            rows = properties.get("rows")
            if not isinstance(rows, list):
                raise AccessError("error", "비용 rows 배열이 없음")
            if rows:
                cost_key = next((key for key in ("pretaxcost", "cost", "totalcost") if key in columns), None)
                if cost_key is None or any(key not in columns for key in ("resourceid", "currency")):
                    raise AccessError("error", "비용·리소스·통화 필수 열이 없음")
                for row in rows:
                    rid = str(row[columns["resourceid"]])
                    if rid.lower() not in ids:
                        raise AccessError("error", "요청 범위 밖 비용 리소스 응답")
                    result.costs.append(CostRecord(
                        subscription_id=sid, resource_id=rid,
                        amount=row[columns[cost_key]], currency=row[columns["currency"]],
                        usage_date=str(row[columns["usagedate"]]) if "usagedate" in columns else None,
                        evidence_refs=[self.http.last_ref] if self.http.last_ref else [],
                    ))
            url = properties.get("nextLink") or ""
        result.facts.setdefault("cost_complete_subscriptions", []).append(sid)
        if not result.costs:
            raise AccessError("not_found", "최근 30일 비용 행이 없음; 청구 반영 지연 또는 사용 없음")

    def logs(self, sid: str, result: Collection) -> None:
        targets = {f"/subscriptions/{sid}"}
        targets.update(
            row["id"] for row in self.base.resources
            if row["subscriptionId"] == sid and row["type"].lower() == "microsoft.cognitiveservices/accounts"
        )
        targets.update(agent.resource_id for agent in self.base.agents
                       if agent.subscription_id == sid and agent.platform == "langchain" and agent.resource_id)
        workspaces: dict[str, tuple[str, int | None]] = {}
        for rid in sorted(targets):
            try:
                settings = self.http.list_arm(
                    ARM + rid + "/providers/Microsoft.Insights/diagnosticSettings?api-version=2021-05-01-preview"
                )
                if not settings:
                    result.logs.append(LogSetting(
                        subscription_id=sid, resource_id=rid, enabled=False,
                        evidence_refs=[self.http.last_ref] if self.http.last_ref else [],
                    ))
                for setting in settings:
                    properties = setting.get("properties") or {}
                    enabled = any(entry.get("enabled") is True for entry in properties.get("logs", []))
                    workspace = properties.get("workspaceId")
                    ref = self.http.last_ref
                    retention = None
                    if workspace:
                        parts = workspace.split("/")
                        if len(parts) < 3 or parts[1].lower() != "subscriptions":
                            raise AccessError("error", "진단 설정의 workspace 리소스 ID 형식 불일치")
                        if parts[2].lower() not in self.allowed_subscriptions:
                            result.logs.append(LogSetting(
                                subscription_id=sid, resource_id=rid, enabled=enabled,
                                workspace_id=workspace, retention_days=None,
                                evidence_refs=[ref] if ref else [],
                            ))
                            result.issues.append(issue(
                                self.http, "logs", workspace,
                                AccessError("permission_denied", "중앙 로그 workspace가 선택 구독 범위 밖임; 다른 테넌트/구독 접근·권한 확대를 시도하지 않음"),
                                ("Reader at separately approved workspace scope",),
                            ))
                            continue
                        if workspace not in workspaces:
                            ws = self.http.request("GET", ARM + workspace + "?api-version=2022-10-01")
                            props = ws.get("properties") or {}
                            customer_id = props.get("customerId")
                            if customer_id:
                                workspaces[workspace] = (customer_id, props.get("retentionInDays"))
                        if workspace in workspaces:
                            retention = workspaces[workspace][1]
                    result.logs.append(LogSetting(
                        subscription_id=sid, resource_id=rid, enabled=enabled,
                        workspace_id=workspace, retention_days=retention,
                        evidence_refs=[value for value in (ref, self.http.last_ref) if value],
                    ))
            except AccessError as exc:
                result.issues.append(issue(self.http, "logs", rid, exc, ("Reader", "Log Analytics Reader")))
        for workspace, (customer_id, _) in workspaces.items():
            if not any(agent.platform == "langchain" and agent.subscription_id == sid for agent in self.base.agents):
                continue
            usage_days = self.criteria["usage_window_days"]
            inactivity = self.criteria["inactivity_days"]
            query = (
                f"AppServiceConsoleLogs | where TimeGenerated >= ago({inactivity}d) "
                r"| extend event=parse_json(extract(@'(\{.*\})',1,ResultDescription)) "
                "| where tostring(event.event) == 'wasmagent.sample.completed' "
                "| extend agent_id=tostring(event.agent_id), input_tokens=tolong(event.input_tokens),"
                "output_tokens=tolong(event.output_tokens) "
                f"| summarize calls_30d=countif(TimeGenerated >= ago({usage_days}d)),"
                f"tokens_30d=sumif(input_tokens+output_tokens,TimeGenerated >= ago({usage_days}d)),"
                f"known_tokens_30d=countif(isnotnull(input_tokens) and isnotnull(output_tokens) "
                f"and TimeGenerated >= ago({usage_days}d)),"
                "calls_90d=count(),last_used_at=max(TimeGenerated) by agent_id"
            )
            try:
                payload = self.http.request(
                    "POST", f"https://api.loganalytics.azure.com/v1/workspaces/{customer_id}/query",
                    LOG_SCOPE, {"query": query},
                )
                tables = payload.get("tables")
                if not isinstance(tables, list) or not tables:
                    raise AccessError("not_found", "Agent 사용량 로그 테이블/행 없음")
                table = tables[0]
                columns = [column["name"] for column in table.get("columns", [])]
                for row in table.get("rows", []):
                    values = dict(zip(columns, row, strict=True))
                    for agent in self.base.agents:
                        if agent.subscription_id == sid and agent.agent_id == values.get("agent_id"):
                            agent.usage_30d = Usage(
                                calls=values["calls_30d"],
                                tokens=values["tokens_30d"]
                                if values["known_tokens_30d"] == values["calls_30d"] else None,
                            )
                            agent.calls_90d = values["calls_90d"]
                            agent.last_used_at = timestamp(values["last_used_at"])
                            for key in ("usage_30d", "calls_90d", "last_used_at"):
                                agent.field_status.pop(key, None)
                            if self.http.last_ref:
                                agent.evidence_refs.append(self.http.last_ref)
                            if agent.usage_30d.tokens is None:
                                from wasm_agent.models import FieldStatus

                                agent.field_status["usage_30d.tokens"] = FieldStatus(
                                    reason="not_found", detail="사용량 이벤트에 토큰 수가 누락됨",
                                )
                            result.facts["audit_activity_observed"] = True
                if not table.get("rows"):
                    raise AccessError("not_found", "Agent 이벤트 없음; 계측/로그 유입 지연 확인 필요")
            except AccessError as exc:
                result.issues.append(issue(self.http, "agent_usage", workspace, exc, ("Log Analytics Reader",)))
                for agent in self.base.agents:
                    if agent.subscription_id == sid and agent.usage_30d is None:
                        for field in ("usage_30d", "calls_90d", "last_used_at"):
                            agent.unavailable(field, exc.reason, str(exc))

    def metrics(self, sid: str, result: Collection) -> None:
        signals = []
        for rid in sorted(self.ai_ids(sid)):
            try:
                definitions = self.http.list_arm(
                    ARM + rid + "/providers/Microsoft.Insights/metricDefinitions?api-version=2018-01-01"
                )
                names = {(entry.get("name") or {}).get("value") for entry in definitions}
                selected = sorted({
                    name for candidates in self.monitor.values() for name in candidates if name in names
                })
                if not selected:
                    continue
                params = urlencode({
                    "api-version": "2018-01-01",
                    "metricnames": ",".join(selected),
                    "timespan": (
                        (self.now - timedelta(days=self.criteria["usage_window_days"])).strftime("%Y-%m-%dT%H:%M:%SZ")
                        + "/" + self.now.strftime("%Y-%m-%dT%H:%M:%SZ")
                    ),
                    "interval": "P1D", "aggregation": "Total",
                })
                payload = self.http.request(
                    "GET", ARM + rid + "/providers/Microsoft.Insights/metrics?" + params,
                )
                signals.append({"resource_id": rid, "metrics": payload.get("value", []),
                                "evidence_ref": self.http.last_ref})
            except AccessError as exc:
                result.issues.append(issue(self.http, "metrics", rid, exc, ("Reader", "Monitoring Reader")))
        result.facts["resource_metrics"] = signals

    def security(self, sid: str, result: Collection) -> None:
        page = self.http.request("POST", GRAPH_URL, body={
            "subscriptions": [sid],
            "query": "securityresources | where type =~ 'microsoft.security/assessments' | project id,properties",
            "options": {"resultFormat": "objectArray", "$top": 1000},
        })
        if page.get("$skipToken") or str(page.get("resultTruncated", "")).lower() == "true":
            raise AccessError("error", "보안 권고가 잘려 전체 AI 권고 수를 확정할 수 없음")
        rows = page.get("data")
        if not isinstance(rows, list):
            raise AccessError("error", "보안 Resource Graph data 배열 없음")
        ids = self.ai_ids(sid)
        for row in rows:
            properties = row.get("properties") or {}
            target = (properties.get("resourceDetails") or {}).get("Id") or ""
            if not any(target.lower() == rid or target.lower().startswith(rid + "/") for rid in ids):
                continue
            metadata = properties.get("metadata") or {}
            status = properties.get("status") or {}
            result.security.append(SecurityRecommendation(
                subscription_id=sid, resource_id=target, assessment_id=row["id"],
                severity=metadata.get("severity"), status=status.get("code"),
                first_evaluation_date=_when(status.get("firstEvaluationDate")),
                status_change_date=_when(status.get("statusChangeDate")),
                evidence_refs=[self.http.last_ref] if self.http.last_ref else [],
            ))
        if not result.security:
            raise AccessError(
                "feature_unavailable",
                "AI 리소스 연결 권고 없음; Defender AI 기능/라이선스 활성화는 이 응답만으로 확인 불가",
            )

    def secure_score(self, sid: str, result: Collection) -> None:
        url = ARM + f"/subscriptions/{sid}/providers/Microsoft.Security/secureScores?api-version=2020-01-01"
        for row in self.http.list_arm(url):
            if row.get("name") != "ascScore":
                continue
            score = (row.get("properties") or {}).get("score") or {}
            result.secure_scores.append(SecureScore(
                subscription_id=sid, current=score.get("current"), max=score.get("max"),
                percentage=score.get("percentage"),
                evidence_refs=[self.http.last_ref] if self.http.last_ref else [],
            ))
        if not any(item.subscription_id == sid for item in result.secure_scores):
            raise AccessError("feature_unavailable", "구독 보안 점수(ascScore) 없음; Defender for Cloud 활성화 확인 필요")
        result.facts.setdefault("secure_score_complete_subscriptions", []).append(sid)

    def policies(self, sid: str, result: Collection) -> None:
        required = {str(value).lower() for value in self.criteria.get("model_policy_definition_ids") or []}
        if not required:
            return
        url = (
            ARM + f"/subscriptions/{sid}/providers/Microsoft.Authorization/policyAssignments"
            "?api-version=2023-04-01&$filter=atScope()"
        )
        for row in self.http.list_arm(url):
            properties = row.get("properties") or {}
            definition = str(properties.get("policyDefinitionId") or "")
            if definition.lower() not in required:
                continue
            result.policy_assignments.append(PolicyAssignment(
                subscription_id=sid, assignment_id=row["id"], display_name=properties.get("displayName"),
                policy_definition_id=definition, scope=properties.get("scope"),
                enforcement_mode=properties.get("enforcementMode"),
                evidence_refs=[self.http.last_ref] if self.http.last_ref else [],
            ))
        result.facts.setdefault("policy_complete_subscriptions", []).append(sid)

    def budgets(self, sid: str, result: Collection) -> None:
        url = ARM + f"/subscriptions/{sid}/providers/Microsoft.Consumption/budgets?api-version=2023-05-01"
        for row in self.http.list_arm(url):
            properties = row.get("properties") or {}
            alerts = [
                note for note in (properties.get("notifications") or {}).values()
                if isinstance(note, dict) and note.get("enabled") is True
            ]
            result.budgets.append(Budget(
                subscription_id=sid, budget_id=row["id"], amount=properties.get("amount"),
                category=properties.get("category"), time_grain=properties.get("timeGrain"),
                enabled_alerts=len(alerts),
                forecast_alerts=sum(1 for note in alerts if note.get("thresholdType") == "Forecasted"),
                thresholds=sorted(
                    float(note["threshold"]) for note in alerts
                    if isinstance(note.get("threshold"), (int, float))
                ),
                evidence_refs=[self.http.last_ref] if self.http.last_ref else [],
            ))
        result.facts.setdefault("budget_complete_subscriptions", []).append(sid)
