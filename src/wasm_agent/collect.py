from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from azure.core.exceptions import ClientAuthenticationError

from wasm_agent.azure import (
    ARM,
    AccessError,
    Credential,
    EvidenceStore,
    ReaderHTTP,
    issue,
    verify_identity,
)
from wasm_agent.collect_entra import EntraCollector
from wasm_agent.collect_foundry import FoundryCollector
from wasm_agent.collect_inventory import (
    InventoryCollector,
    LangChainCollector,
    ManualCollector,
)
from wasm_agent.collect_proposals import ProposalCollector
from wasm_agent.collect_signals import SignalCollector
from wasm_agent.models import Collection, Issue, Settings, load_conventions, load_criteria


def merge(destination: Collection, source: Collection) -> None:
    for field in (
        "agents", "deployments", "evaluations", "costs", "security", "secure_scores",
        "policy_assignments", "budgets", "entra_blueprints", "entra_agent_identities",
        "logs", "proposal_observations", "issues", "resources",
        "completed_subscriptions",
    ):
        getattr(destination, field).extend(getattr(source, field))
    for key, value in source.facts.items():
        if isinstance(value, list):
            destination.facts.setdefault(key, []).extend(value)
        elif isinstance(value, bool):
            if key.endswith("_complete"):
                destination.facts[key] = destination.facts.get(key, True) and value
            else:
                destination.facts[key] = destination.facts.get(key, False) or value
        else:
            destination.facts[key] = value


def collect_subscription(
    sid: str, credential: Credential, settings: Settings, store: EvidenceStore, now: datetime,
    criteria: dict[str, Any], tags: dict[str, Any],
) -> Collection:
    http = ReaderHTTP(credential, store=store, subscription=sid)
    result = Collection(collected_at=now, subscriptions=[sid])
    try:
        inventory = InventoryCollector(http, now).discover([sid])
        merge(result, inventory)
        merge(result, FoundryCollector(http, result.resources, settings, now).discover([sid]))
        merge(result, LangChainCollector(
            result.resources, tags, settings.tenant_id, now, store,
        ).discover([sid]))
        merge(result, SignalCollector(
            http, result, now, criteria, settings.monitor, settings.subscriptions,
        ).discover([sid]))
        merge(result, ProposalCollector(http, result, now).discover([sid]))
    except AccessError as exc:
        result.facts["inventory_complete"] = False
        result.issues.append(issue(http, "subscription", sid, exc, ("Reader",)))
    except (ValueError, KeyError, TypeError, ClientAuthenticationError) as exc:
        result.facts["inventory_complete"] = False
        result.issues.append(Issue(
            subscription_id=sid, collector="subscription", target=sid, reason="error",
            detail=f"수집 응답/인증 처리 실패: {type(exc).__name__}; 원문·자격증명은 출력하지 않음",
            evidence_refs=store.refs(sid),
        ))
    finally:
        http.close()
    return result


def collect(settings: Settings, credential: Credential, now: datetime | None = None) -> Collection:
    instant = now or datetime.now(UTC)
    if not settings.tenant_id or not settings.expected_principal_id:
        raise ValueError("tenant_id와 expected_principal_id가 필요합니다. 관리자 계정으로 대체하지 않습니다.")
    verify_identity(credential, settings.tenant_id, settings.expected_principal_id)
    criteria = load_criteria(settings)
    tags = load_conventions(settings)
    subscriptions = settings.subscriptions
    if not subscriptions:
        http = ReaderHTTP(credential)
        try:
            rows = http.list_arm(ARM + "/subscriptions?api-version=2022-12-01")
            subscriptions = [
                row["subscriptionId"].lower() for row in rows
                if row.get("tenantId", "").lower() == settings.tenant_id and row.get("state") == "Enabled"
            ]
        finally:
            http.close()
    if not subscriptions:
        raise AccessError("permission_denied", "접근 가능한 활성 구독이 없습니다.")
    store = EvidenceStore(settings.evidence_dir, instant)
    result = Collection(collected_at=instant, subscriptions=sorted(set(subscriptions)))
    resolved_settings = settings.model_copy(update={"subscriptions": result.subscriptions})
    with ThreadPoolExecutor(max_workers=min(settings.workers, len(result.subscriptions))) as executor:
        futures = [
            executor.submit(
                collect_subscription, sid, credential, resolved_settings, store, instant, criteria, tags,
            ) for sid in result.subscriptions
        ]
        for future in as_completed(futures):
            merge(result, future.result())
    result.facts["entra_requested"] = True
    graph = ReaderHTTP(credential, store=store)
    try:
        merge(result, EntraCollector(graph, instant, criteria).discover())
    finally:
        graph.close()
    if settings.manual_agents:
        merge(result, ManualCollector(settings.manual_agents, instant).discover([]))
    for agent in result.agents:
        if agent.platform != "langchain":
            continue
        linked = [
            deployment for deployment in result.deployments
            if deployment.name == agent.model
            and deployment.account_id.lower() == (agent.model_resource_id or "").lower()
        ]
        if len(linked) == 1:
            agent.model, agent.model_version = linked[0].model, linked[0].version
            agent.field_status.pop("model", None)
            agent.field_status.pop("model_version", None)
    seen = set()
    for record in result.agents:
        identity = (record.platform, record.subscription_id, record.resource_id, record.agent_id)
        if identity in seen:
            raise ValueError("중복 Agent 식별자 발견; 중복 수치 집계를 중단합니다.")
        seen.add(identity)
    result.agents.sort(key=lambda row: (row.subscription_id or "", row.platform, row.agent_id))
    result.facts["inventory_complete"] = (
        result.facts.get("inventory_complete", False)
        and set(result.completed_subscriptions) == set(result.subscriptions)
    )
    result.facts["agent_inventory_complete"] = (
        result.facts["inventory_complete"]
        and not any(item.collector in ("foundry_agents", "foundry_projects") for item in result.issues)
    )
    result.facts["evidence_directory"] = str(store.path.resolve())
    return result
