from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from wasm_agent.azure import (
    ARM,
    GRAPH_URL,
    AccessError,
    EvidenceStore,
    ReaderHTTP,
    redact,
    rejects_broad_permissions,
)
from wasm_agent.models import AgentEvidence, Collection

HOSTS = {
    "microsoft.web/sites", "microsoft.app/containerapps",
    "microsoft.containerservice/managedclusters",
}
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


class LangChainCollector:
    required_roles = ("Reader",)

    def __init__(
        self, resources: list[dict[str, Any]], tags: dict[str, Any],
        tenant: str | None, now: datetime, store: EvidenceStore,
    ) -> None:
        self.resources, self.tags, self.tenant, self.now, self.store = resources, tags, tenant, now, store

    def discover(self, subscriptions: Sequence[str]) -> Collection:
        result = Collection(collected_at=self.now)
        for resource in self.resources:
            sid = resource["subscriptionId"]
            if sid not in subscriptions or resource["type"].lower() not in HOSTS:
                continue
            tags = resource.get("tags") or {}
            tagged = tags.get(self.tags["agent_type_key"], "").lower() in self.tags["langchain_values"]
            named = any(part.lower() in resource["name"].lower() for part in self.tags["name_patterns"])
            if not (tagged or named):
                continue
            record = AgentEvidence(
                collected_at=self.now, tenant_id=self.tenant, subscription_id=sid,
                resource_group=resource.get("resourceGroup"),
                platform="langchain", agent_id=tags.get(self.tags["agent_id_key"]) or resource["id"],
                agent_name=resource["name"], resource_id=resource["id"], hosting_type=resource["type"],
                owner=redact(tags.get(self.tags["owner_key"])),
                sponsor=redact(tags.get(self.tags["sponsor_key"])),
                tags=redact(tags), model=tags.get(self.tags["model_deployment_key"]),
                model_resource_id=tags.get(self.tags["model_resource_key"]),
                cost_resource_ids=[
                    value for value in [
                        resource["id"], (resource.get("properties") or {}).get("serverFarmId"),
                    ] if value
                ],
                detection_confidence="tag" if tagged else "name_heuristic",
                evidence_refs=self.store.refs(sid), se_codes=["OT-SY-28", "OT-SY-29", "OE-SY-22"],
            ).mark_unknowns()
            record.unavailable("tools", "feature_unavailable", "호스팅 메타데이터로 실제 LangChain 도구는 확인 불가")
            record.unavailable(
                "evaluated_before_deploy", "not_found", "자체 Agent의 버전별 평가·배포 증적 미입력",
            )
            result.agents.append(record)
        return result


class ManualCollector:
    required_roles: tuple[str, ...] = ()

    def __init__(self, path: Path, now: datetime) -> None:
        self.path, self.now = path, now

    def discover(self, subscriptions: Sequence[str]) -> Collection:
        result = Collection(collected_at=self.now)
        with self.path.open(encoding="utf-8-sig", newline="") as stream:
            for number, row in enumerate(csv.DictReader(stream), 2):
                values = {key: value for key, value in row.items() if value not in ("", None)}
                if values.get("platform", "manual") not in ("manual", "other"):
                    raise ValueError(f"{self.path.name}:{number}: manual/other 플랫폼만 허용")
                for key in ("tags", "tools", "usage_30d", "field_status", "evidence_refs", "se_codes",
                            "cost_resource_ids"):
                    if key in values:
                        values[key] = json.loads(values[key])
                values.setdefault("platform", "manual")
                values.setdefault("collected_at", self.now)
                values.setdefault("detection_confidence", "manual")
                values.setdefault("evidence_refs", [str(self.path.resolve()) + f"#row-{number}"])
                try:
                    result.agents.append(AgentEvidence.model_validate(values).mark_unknowns(
                        "수동 등록 파일에 값이 없음; Azure API로 보완하지 않음",
                    ))
                except ValidationError as exc:
                    raise ValueError(f"{self.path.name}:{number}: 공통 스키마 검증 실패") from exc
        return result
