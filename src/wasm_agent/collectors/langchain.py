from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from wasm_agent.models import AgentEvidence, Collection
from wasm_agent.utils.evidence import EvidenceStore, redact

HOSTS = {
    "microsoft.web/sites", "microsoft.app/containerapps",
    "microsoft.containerservice/managedclusters",
}


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
                evidence_refs=self.store.refs(sid), se_codes=["OT-SY-18", "OT-SY-19", "OE-SY-16"],
            ).mark_unknowns()
            record.unavailable("tools", "feature_unavailable", "호스팅 메타데이터로 실제 LangChain 도구는 확인 불가")
            record.unavailable(
                "evaluated_before_deploy", "not_found", "자체 Agent의 버전별 평가·배포 증적 미입력",
            )
            result.agents.append(record)
        return result
