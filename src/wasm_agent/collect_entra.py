from __future__ import annotations

import fnmatch
import re
from datetime import datetime
from typing import Any

from wasm_agent.azure import MSGRAPH, MSGRAPH_SCOPE, AccessError, ReaderHTTP, issue
from wasm_agent.models import (
    Collection,
    EntraAgentIdentity,
    EntraBlueprint,
    try_timestamp,
)

V1 = MSGRAPH + "/v1.0"
GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
DEFAULT_ROLE_ID = "00000000-0000-0000-0000-000000000000"


def guid(value: object) -> str:
    if not isinstance(value, str) or not GUID.fullmatch(value):
        raise AccessError("error", "Graph 응답의 개체 ID 형식이 올바르지 않습니다.")
    return value


def text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


class EntraCollector:
    """Tenant-wide Microsoft Entra Agent ID evidence through read-only Microsoft Graph GET calls."""

    required_roles = (
        "AgentIdentity.Read.All", "AgentIdentityBlueprint.Read.All", "Application.Read.All",
    )

    def __init__(self, http: ReaderHTTP, now: datetime, criteria: dict[str, Any]) -> None:
        self.http, self.now = http, now
        self.patterns = [str(value) for value in criteria.get("overprivileged_permission_patterns") or []]
        self.role_names: dict[str, dict[str, str]] = {}

    def discover(self) -> Collection:
        result = Collection(collected_at=self.now)
        for name, operation, roles in (
            ("entra_blueprints", self.blueprints, ("AgentIdentityBlueprint.Read.All",)),
            ("entra_agents", self.agent_identities, ("AgentIdentity.Read.All", "Application.Read.All")),
        ):
            try:
                operation(result)
            except AccessError as exc:
                result.issues.append(issue(self.http, name, "tenant", exc, roles))
        return result

    def ref(self) -> list[str]:
        return [self.http.last_ref] if self.http.last_ref else []

    def blueprints(self, result: Collection) -> None:
        for row in self.http.list_graph(V1 + "/applications/microsoft.graph.agentIdentityBlueprint?$top=100"):
            result.entra_blueprints.append(EntraBlueprint(
                blueprint_id=guid(row.get("appId") or row.get("id")), display_name=row.get("displayName"),
                created_at=try_timestamp(row.get("createdDateTime")), tags=text_list(row.get("tags")),
                evidence_refs=self.ref(),
            ))
        result.facts["entra_blueprints_complete"] = True

    def agent_identities(self, result: Collection) -> None:
        for row in self.http.list_graph(V1 + "/servicePrincipals/microsoft.graph.agentIdentity?$top=100"):
            identity_id = guid(row.get("id"))
            base = V1 + f"/servicePrincipals/{identity_id}"
            owners = self.http.list_graph(
                base + "/microsoft.graph.agentIdentity/owners?$select=id,accountEnabled&$top=100",
            )
            sponsors = self.http.list_graph(base + "/microsoft.graph.agentIdentity/sponsors?$select=id&$top=100")
            roles = self.app_roles(identity_id)
            result.entra_agent_identities.append(EntraAgentIdentity(
                identity_id=identity_id, display_name=row.get("displayName"),
                blueprint_id=row.get("agentIdentityBlueprintId"),
                created_at=try_timestamp(row.get("createdDateTime")), account_enabled=row.get("accountEnabled"),
                owner_count=len(owners), sponsor_count=len(sponsors),
                owners_all_disabled=(
                    all(owner.get("accountEnabled") is False for owner in owners) if owners else None
                ),
                app_roles=roles,
                overprivileged_roles=[
                    role for role in roles
                    if any(fnmatch.fnmatchcase(role, pattern) for pattern in self.patterns)
                ],
                evidence_refs=self.ref(),
            ))
        result.facts["entra_agents_complete"] = True

    def app_roles(self, identity_id: str) -> list[str]:
        names: list[str] = []
        url = V1 + f"/servicePrincipals/{identity_id}/appRoleAssignments?$top=100"
        for assignment in self.http.list_graph(url):
            role_id = str(assignment.get("appRoleId") or "")
            if role_id == DEFAULT_ROLE_ID:
                continue
            resource = guid(assignment.get("resourceId"))
            if resource not in self.role_names:
                detail = self.http.request("GET", V1 + f"/servicePrincipals/{resource}?$select=id,appRoles", MSGRAPH_SCOPE)
                self.role_names[resource] = {
                    str(role.get("id")): str(role.get("value")) for role in detail.get("appRoles") or []
                    if isinstance(role, dict)
                }
            names.append(self.role_names[resource].get(role_id) or f"unresolved:{role_id}")
        return sorted(set(names))
