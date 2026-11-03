from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from wasm_agent.azure import ARM, GRAPH_URL, AccessError, ReaderHTTP
from wasm_agent.identity import rejects_broad_permissions
from wasm_agent.models import Collection, Issue

RESOURCE_TYPES = (
    "microsoft.cognitiveservices/accounts", "microsoft.cognitiveservices/accounts/projects",
    "microsoft.cognitiveservices/accounts/deployments", "microsoft.web/sites",
    "microsoft.app/containerapps", "microsoft.containerservice/managedclusters",
    "microsoft.operationalinsights/workspaces",
)


class InventoryCollector:
    required_roles = ("Reader",)

    def __init__(self, http: ReaderHTTP, now: datetime) -> None:
        self.http = http
        self.now = now

    def discover(self, subscriptions: Sequence[str]) -> Collection:
        result = Collection(collected_at=self.now, subscriptions=list(subscriptions))
        for sid in subscriptions:
            scope = f"/subscriptions/{sid}"
            permissions = self.http.list_arm(
                ARM + scope + "/providers/Microsoft.Authorization/permissions?api-version=2022-04-01"
            )
            if rejects_broad_permissions(permissions):
                raise AccessError("permission_denied", "광범위 쓰기 권한 탐지; 진단 Reader 계정으로 실행해야 함")
            types = ",".join(f"'{value}'" for value in RESOURCE_TYPES)
            query = (
                f"Resources | where type in~ ({types}) "
                "| project id,name,type,kind,resourceGroup,subscriptionId,location,tags,"
                "properties=pack('endpoint',properties.endpoint,'endpoints',properties.endpoints,"
                "'defaultHostName',properties.defaultHostName,'retentionInDays',properties.retentionInDays,"
                "'customerId',properties.customerId,'serverFarmId',properties.serverFarmId)"
            )
            options: dict[str, Any] = {"resultFormat": "objectArray", "$top": 1000}
            seen = set()
            while True:
                page = self.http.request("POST", GRAPH_URL, body={
                    "subscriptions": [sid], "query": query, "options": options,
                })
                rows = page.get("data")
                if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                    raise AccessError("error", "Resource Graph data 배열 형식 불일치")
                for row in rows:
                    if row.get("subscriptionId", "").lower() != sid:
                        raise AccessError("error", "요청 구독 밖 Resource Graph 응답")
                result.resources.extend(rows)
                continuation = page.get("$skipToken")
                if not continuation:
                    if str(page.get("resultTruncated", "false")).lower() == "true":
                        raise AccessError("error", "Resource Graph 결과 잘림; 연속 토큰 없음")
                    break
                if continuation in seen:
                    raise AccessError("error", "Resource Graph 페이지 토큰 반복")
                seen.add(continuation)
                options["$skipToken"] = continuation
            result.completed_subscriptions.append(sid)
        result.facts["inventory_complete"] = True
        return result


def issue(http: ReaderHTTP, collector: str, target: str, error: AccessError,
          roles: tuple[str, ...]) -> Issue:
    return Issue(
        subscription_id=http.subscription, collector=collector, target=target,
        reason=error.reason, detail=str(error), required_roles=list(roles),
        evidence_refs=[http.last_ref] if http.last_ref else [],
    )
