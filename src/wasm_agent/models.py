from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Reason = Literal["permission_denied", "feature_unavailable", "license_missing", "not_found", "error"]
Platform = Literal["foundry", "langchain", "other", "manual"]


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldStatus(EvidenceModel):
    reason: Reason
    detail: str


class Usage(EvidenceModel):
    calls: int | None = Field(default=None, ge=0)
    tokens: int | None = Field(default=None, ge=0)


class AgentEvidence(EvidenceModel):
    collected_at: AwareDatetime
    tenant_id: str | None = None
    subscription_id: str | None = None
    resource_group: str | None = None
    platform: Platform
    agent_id: str
    agent_name: str
    agent_version: str | None = None
    resource_id: str | None = None
    hosting_type: str | None = None
    owner: str | None = None
    sponsor: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    model: str | None = None
    model_version: str | None = None
    model_resource_id: str | None = None
    cost_resource_ids: list[str] = Field(default_factory=list)
    tools: list[str] | None = None
    created_at: AwareDatetime | None = None
    deployed_at: AwareDatetime | None = None
    last_used_at: AwareDatetime | None = None
    cost_30d: float | None = None
    currency: str | None = None
    usage_30d: Usage | None = None
    calls_90d: int | None = None
    usage_coverage_start: AwareDatetime | None = None
    evaluated_before_deploy: bool | None = None
    guardrail_applied: bool | None = None
    detection_confidence: Literal["tag", "name_heuristic", "manual"]
    evidence_refs: list[str] = Field(default_factory=list)
    se_codes: list[str] = Field(default_factory=list)
    field_status: dict[str, FieldStatus] = Field(default_factory=dict)

    def mark_unknowns(self, detail: str = "응답에 해당 필드가 없음") -> AgentEvidence:
        for key in type(self).model_fields:
            if getattr(self, key) is None and key not in self.field_status:
                self.field_status[key] = FieldStatus(reason="not_found", detail=detail)
        if self.usage_30d:
            for key in ("calls", "tokens"):
                name = "usage_30d." + key
                if getattr(self.usage_30d, key) is None and name not in self.field_status:
                    self.field_status[name] = FieldStatus(reason="not_found", detail=detail)
        return self

    def unavailable(self, field: str, reason: Reason, detail: str) -> None:
        setattr(self, field, None)
        self.field_status[field] = FieldStatus(reason=reason, detail=detail)


class ModelDeployment(EvidenceModel):
    subscription_id: str
    resource_id: str
    account_id: str
    name: str
    model: str | None
    version: str | None
    format: str | None
    sku: str | None = None
    capacity: int | None = None
    state: str | None = None
    rai_policy: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class EvaluationRun(EvidenceModel):
    subscription_id: str
    project_id: str
    run_id: str
    status: str | None
    agent_id: str | None = None
    agent_version: str | None = None
    completed_at: AwareDatetime | None = None
    passed_items: int | None = Field(default=None, ge=0)
    failed_items: int | None = Field(default=None, ge=0)
    errored_items: int | None = Field(default=None, ge=0)
    total_items: int | None = Field(default=None, ge=0)
    evidence_refs: list[str] = Field(default_factory=list)


class CostRecord(EvidenceModel):
    subscription_id: str
    resource_id: str
    amount: float
    currency: str
    usage_date: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class SecurityRecommendation(EvidenceModel):
    subscription_id: str
    resource_id: str
    assessment_id: str
    severity: str | None
    status: str | None
    evidence_refs: list[str] = Field(default_factory=list)


class LogSetting(EvidenceModel):
    subscription_id: str
    resource_id: str
    enabled: bool
    workspace_id: str | None = None
    retention_days: int | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class Issue(EvidenceModel):
    subscription_id: str | None = None
    collector: str
    target: str
    reason: Reason
    detail: str
    required_roles: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class Collection(EvidenceModel):
    collected_at: AwareDatetime
    agents: list[AgentEvidence] = Field(default_factory=list)
    deployments: list[ModelDeployment] = Field(default_factory=list)
    evaluations: list[EvaluationRun] = Field(default_factory=list)
    costs: list[CostRecord] = Field(default_factory=list)
    security: list[SecurityRecommendation] = Field(default_factory=list)
    logs: list[LogSetting] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    subscriptions: list[str] = Field(default_factory=list)
    completed_subscriptions: list[str] = Field(default_factory=list)
    resources: list[dict[str, Any]] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)


class Finding(EvidenceModel):
    se_code: str
    scope: str
    metric_value: float | int | None = None
    level: Literal["L1", "L2", "L3", "L4", "L5", "N/A"]
    rationale: str
    reason: Reason | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    next_step: str | None = None
    interview_level: float | None = Field(default=None, ge=1, le=5)
    gap_flag: bool = False


def timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    from datetime import UTC

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone is required for evidence timestamps")
        return parsed
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value
    raise ValueError("Invalid evidence timestamp")
