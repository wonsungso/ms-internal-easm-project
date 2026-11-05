from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from wasm_agent.azure import ARM, GRAPH_URL, AccessError, ReaderHTTP, issue
from wasm_agent.collect_inventory import HOSTS
from wasm_agent.models import Collection, ProposalObservation

PRIVILEGED_ROLES = {
    "8e3af657-a8ff-443c-a75c-2fe8c4bcb635": "Owner",
    "b24988ac-6180-42a0-ab88-20f7382dd24c": "Contributor",
    "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9": "User Access Administrator",
    "f58310d9-a9f6-439a-9e8d-f62e7b41a168": "Role Based Access Control Administrator",
}
AI_ACCOUNT_KINDS = ("aiservices", "openai")
AI_TYPES = (
    "microsoft.cognitiveservices/accounts", "microsoft.web/sites", "microsoft.app/containerapps",
)
PROPERTIES_QUERY = (
    "Resources | where type in~ ({types}) | project id, name, type, kind, location,"
    " identityType=tostring(identity.type), principalId=tostring(identity.principalId),"
    " userPrincipals=extract_all('\"principalId\":\"([0-9a-f-]+)\"', tostring(identity.userAssignedIdentities)),"
    " publicNetworkAccess=tostring(properties.publicNetworkAccess),"
    " defaultAction=tostring(properties.networkAcls.defaultAction),"
    " privateEndpoints=array_length(properties.privateEndpointConnections),"
    " disableLocalAuth=tobool(properties.disableLocalAuth), httpsOnly=tobool(properties.httpsOnly),"
    " vnetSubnet=tostring(properties.virtualNetworkSubnetId),"
    " ingressExternal=tobool(properties.configuration.ingress.external),"
    " image=tostring(properties.template.containers[0].image)"
)
MONITOR_QUERY = (
    "Resources | where type in~ ('microsoft.insights/metricalerts','microsoft.insights/scheduledqueryrules',"
    "'microsoft.insights/activitylogalerts','microsoft.insights/components','microsoft.insights/actiongroups')"
    " | project id, name, type, location, enabled=tobool(properties.enabled),"
    " scopes=tostring(properties.scopes), actions=tostring(properties.actions),"
    " retentionDays=toint(properties.RetentionInDays),"
    " receivers=pack('email', array_length(properties.emailReceivers),"
    " 'sms', array_length(properties.smsReceivers), 'webhook', array_length(properties.webhookReceivers),"
    " 'armRole', array_length(properties.armRoleReceivers),"
    " 'azureFunction', array_length(properties.azureFunctionReceivers),"
    " 'logicApp', array_length(properties.logicAppReceivers),"
    " 'itsm', array_length(properties.itsmReceivers))"
)
POLICY_QUERY = (
    "PolicyResources | where type =~ 'microsoft.policyinsights/policystates'"
    " | extend resourceType=tolower(tostring(properties.resourceType))"
    " | where resourceType in~ ({types}) | project resourceId=tostring(properties.resourceId),"
    " state=tostring(properties.complianceState), definition=tostring(properties.policyDefinitionName)"
)


def quoted(values: Sequence[str]) -> str:
    return ",".join(f"'{value}'" for value in values)


def truthy(value: Any) -> bool | None:
    if value is None:
        return None
    return value in (True, 1, "true", "True")


class ProposalCollector:
    """Azure 운영 추가 제안(OE-SY-17, DS-SY-07, BI-SY-10, OE-SY-18, OE-SY-19, BI-SY-14)에 쓰는 읽기 전용 구성 사실을 수집한다."""

    required_roles = ("Reader",)

    def __init__(self, http: ReaderHTTP, data: Collection, now: datetime) -> None:
        self.http, self.data, self.now = http, data, now
        self.cache: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}

    def refs(self) -> list[str]:
        return [self.http.last_ref] if self.http.last_ref else []

    def graph(self, sid: str, query: str) -> list[dict[str, Any]]:
        page = self.http.request("POST", GRAPH_URL, body={
            "subscriptions": [sid], "query": query, "options": {"resultFormat": "objectArray", "$top": 1000},
        })
        rows = page.get("data")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise AccessError("error", "Resource Graph data 배열 형식 불일치")
        if str(page.get("resultTruncated", "false")).lower() == "true":
            raise AccessError("error", "Resource Graph 결과 잘림")
        return rows

    def discover(self, subscriptions: Sequence[str]) -> Collection:
        result = Collection(collected_at=self.now)
        for sid in subscriptions:
            for name, step in (
                ("OE-SY-17", self.identity), ("DS-SY-07", self.network), ("BI-SY-10", self.safety),
                ("OE-SY-18", self.monitoring), ("BI-SY-14", self.policy),
            ):
                try:
                    step(sid, result)
                except AccessError as exc:
                    result.issues.append(issue(self.http, "proposal_" + name, sid, exc, self.required_roles))
                    result.facts.setdefault("proposal_incomplete", []).append(name)
        return result

    def targets(self, sid: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if sid in self.cache:
            return self.cache[sid]
        host_ids = {
            (agent.resource_id or "").lower() for agent in self.data.agents
            if agent.platform == "langchain" and agent.subscription_id == sid
        }
        types = quoted(AI_TYPES)
        rows = self.graph(sid, PROPERTIES_QUERY.format(types=types))
        accounts = [
            row for row in rows
            if row["type"].lower() == AI_TYPES[0] and str(row.get("kind", "")).lower() in AI_ACCOUNT_KINDS
        ]
        hosts = [
            row for row in rows
            if row["type"].lower() in HOSTS and row["id"].lower() in host_ids
        ]
        self.cache[sid] = (accounts, hosts)
        return accounts, hosts

    def identity(self, sid: str, result: Collection) -> None:
        accounts, hosts = self.targets(sid)
        refs = self.refs()
        subjects = [*accounts, *hosts]
        principals = {
            row["id"]: {value for value in [row.get("principalId"), *(row.get("userPrincipals") or [])] if value}
            for row in subjects
        }
        wanted = set().union(*principals.values()) if principals else set()
        assignments: list[dict[str, Any]] = []
        if wanted:
            url = ARM + f"/subscriptions/{sid}/providers/Microsoft.Authorization/roleAssignments?api-version=2022-04-01"
            assignments = [
                row.get("properties") or {} for row in self.http.list_arm(url)
                if (row.get("properties") or {}).get("principalId") in wanted
            ]
            refs = self.refs()
        for row in subjects:
            own = principals[row["id"]]
            mine = [item for item in assignments if item.get("principalId") in own]
            privileged = [
                item for item in mine
                if str(item.get("roleDefinitionId", "")).rsplit("/", 1)[-1].lower() in PRIVILEGED_ROLES
            ]
            result.proposal_observations.append(ProposalObservation(
                code="OE-SY-17", subscription_id=sid, subject=row["id"],
                kind="ai_account" if row in accounts else "agent_host",
                values={
                    "identity_type": row.get("identityType") or "None",
                    "principal_count": len(own), "assignments": len(mine),
                    "privileged_assignments": len(privileged),
                    "subscription_scope_assignments": sum(
                        1 for item in mine if str(item.get("scope", "")).lower() == f"/subscriptions/{sid}"
                    ),
                    "local_auth_disabled": truthy(row.get("disableLocalAuth")) if row in accounts else None,
                },
                evidence_refs=refs,
            ))

    def network(self, sid: str, result: Collection) -> None:
        accounts, hosts = self.targets(sid)
        refs = self.refs()
        for row in accounts:
            result.proposal_observations.append(ProposalObservation(
                code="DS-SY-07", subscription_id=sid, subject=row["id"], kind="ai_account",
                values={
                    "public_network_access": row.get("publicNetworkAccess") or None,
                    "default_action": row.get("defaultAction") or None,
                    "private_endpoints": row.get("privateEndpoints"),
                },
                evidence_refs=refs,
            ))
        for row in hosts:
            restrictions = None
            if row["type"].lower() == "microsoft.web/sites":
                config = self.http.request("GET", ARM + row["id"] + "/config/web?api-version=2024-04-01")
                properties = config.get("properties") or {}
                restrictions = len(properties.get("ipSecurityRestrictions") or [])
            result.proposal_observations.append(ProposalObservation(
                code="DS-SY-07", subscription_id=sid, subject=row["id"], kind="agent_host",
                values={
                    "public_network_access": row.get("publicNetworkAccess") or None,
                    "https_only": truthy(row.get("httpsOnly")),
                    "vnet_integrated": bool(row.get("vnetSubnet")),
                    "ip_restrictions": restrictions,
                    "ingress_external": truthy(row.get("ingressExternal")),
                },
                evidence_refs=self.refs(),
            ))
            if row["type"].lower() == "microsoft.web/sites":
                runtime = str((config.get("properties") or {}).get("linuxFxVersion") or "")
                result.proposal_observations.append(ProposalObservation(
                    code="BI-SY-12", subscription_id=sid, subject=row["id"], kind="agent_host",
                    values={"runtime": runtime or None, "image": None},
                    evidence_refs=self.refs(),
                ))
            else:
                image = row.get("image") or ""
                result.proposal_observations.append(ProposalObservation(
                    code="BI-SY-12", subscription_id=sid, subject=row["id"], kind="agent_host",
                    values={"runtime": None, "image": image or None, "pinned_by_digest": "@sha256:" in image},
                    evidence_refs=refs,
                ))

    def safety(self, sid: str, result: Collection) -> None:
        accounts, _ = self.targets(sid)
        for row in accounts:
            policies = self.http.list_arm(ARM + row["id"] + "/raiPolicies?api-version=2024-10-01")
            custom = [
                item for item in policies
                if (item.get("properties") or {}).get("type") != "SystemManaged"
            ]
            filters = [
                entry for item in custom
                for entry in (item.get("properties") or {}).get("contentFilters") or []
                if isinstance(entry, dict) and entry.get("enabled") is not False
            ]
            result.proposal_observations.append(ProposalObservation(
                code="BI-SY-10", subscription_id=sid, subject=row["id"], kind="ai_account",
                values={
                    "policies": len(policies), "custom_policies": len(custom),
                    "custom_enabled_filters": len(filters),
                    "custom_policy_names": sorted(item.get("name", "") for item in custom),
                },
                evidence_refs=self.refs(),
            ))

    def monitoring(self, sid: str, result: Collection) -> None:
        rows = self.graph(sid, MONITOR_QUERY)
        refs = self.refs()
        ai_ids = [row["id"].lower() for row in self.targets(sid)[0]]
        for row in rows:
            kind = row["type"].lower().rsplit("/", 1)[-1]
            values: dict[str, Any] = {"kind": kind}
            if kind == "actiongroups":
                receivers = row.get("receivers") or {}
                values["receivers"] = {key: value for key, value in receivers.items() if value}
            elif kind == "components":
                values["retention_days"] = row.get("retentionDays")
            else:
                scopes = str(row.get("scopes") or "").lower()
                values["enabled"] = truthy(row.get("enabled"))
                values["has_action_group"] = "actiongroups" in str(row.get("actions") or "").lower()
                values["targets_ai"] = any(
                    scope and (ai.startswith(scope.rstrip("/") + "/") or ai == scope)
                    for ai in ai_ids for scope in _scope_list(scopes)
                )
            result.proposal_observations.append(ProposalObservation(
                code="OE-SY-18", subscription_id=sid, subject=row["id"], kind=kind, values=values,
                evidence_refs=refs,
            ))

    def policy(self, sid: str, result: Collection) -> None:
        types = quoted((
            "microsoft.cognitiveservices/accounts", "microsoft.cognitiveservices/accounts/projects",
            "microsoft.web/sites", "microsoft.app/containerapps",
        ))
        rows = self.graph(sid, POLICY_QUERY.format(types=types))
        refs = self.refs()
        for state in sorted({str(row.get("state") or "Unknown") for row in rows}):
            matched = [row for row in rows if str(row.get("state") or "Unknown") == state]
            result.proposal_observations.append(ProposalObservation(
                code="BI-SY-14", subscription_id=sid, subject=f"/subscriptions/{sid}", kind="policy_state",
                values={
                    "state": state, "resources": len({row.get("resourceId", "").lower() for row in matched}),
                    "definitions": len({row.get("definition") for row in matched}),
                },
                evidence_refs=refs,
            ))
        result.facts.setdefault("proposal_policy_subscriptions", []).append(sid)


def _scope_list(scopes: str) -> list[str]:
    return [part.strip('[]" ') for part in scopes.split(",") if part.strip('[]" ')]
