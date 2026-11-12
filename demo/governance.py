from __future__ import annotations

import hashlib
import json
import math
import secrets
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from easm_agent.models import Collection

POLICY_REVISION = "demo-governance-v1"
RUNTIME_REVISION = "chatbot-governance-v1"
SYNTHETIC_VALUES = frozenset({"synthetic-ready", "synthetic-reviewed"})
CHECK_NAMES = frozenset({
    "endpoint_allowed", "endpoint_denied", "endpoint_credentials_denied",
    "unapproved_denied", "wrong_actor_denied", "rejected_denied",
    "approved_executed", "replay_denied", "expired_denied", "state_cleaned",
})


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(),
    ).hexdigest()


def endpoint_key(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
        or parsed.query or parsed.fragment or parsed.port not in (None, 443)
        or "\\" in url or "%" in url or any(char.isspace() for char in url)
        or any(part in (".", "..") for part in parsed.path.split("/"))
    ):
        raise ValueError("HTTPS endpoint without credentials, query or ambiguous path is required")
    return "https://" + parsed.hostname.lower() + parsed.path.rstrip("/")


@dataclass(frozen=True)
class GovernancePolicy:
    endpoints: frozenset[str]

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> GovernancePolicy:
        # These server-owned settings are the explicit allowlist, never request/model input.
        return cls(frozenset(
            endpoint_key(environment[key])
            for key in ("AZURE_OPENAI_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT")
            if environment.get(key)
        ))

    def require_endpoint(self, url: str) -> str:
        try:
            allowed = endpoint_key(url) in self.endpoints
        except ValueError:
            allowed = False
        if not allowed:
            raise PermissionError("External endpoint is not explicitly allowed")
        return url

    @property
    def fingerprint(self) -> str:
        return digest({"revision": POLICY_REVISION, "endpoints": sorted(self.endpoints)})


@dataclass
class PendingAction:
    actor: str
    value: str
    expires_at: float
    decision: Literal["pending", "approved", "denied"] = "pending"


class GovernanceEngine:
    """Only disposable synthetic memory is writable. Approval is not an LLM tool."""

    def __init__(self, policy: GovernancePolicy) -> None:
        self.policy = policy
        self._actions: dict[str, PendingAction] = {}
        self._records: dict[str, str] = {}
        self._lock = threading.Lock()

    def _prune(self) -> None:
        now = time.monotonic()
        for action_id in list(self._actions):
            if self._actions[action_id].expires_at <= now:
                self._actions.pop(action_id)
                self._records.pop(action_id, None)

    def propose(self, actor: str, value: str) -> str:
        if not actor or value not in SYNTHETIC_VALUES:
            raise ValueError("An authenticated actor and a predefined synthetic value are required")
        with self._lock:
            self._prune()
            if len(self._actions) >= 256:
                raise ValueError("Synthetic pending-action capacity reached")
            action_id = secrets.token_hex(16)
            self._actions[action_id] = PendingAction(
                hashlib.sha256(actor.encode()).hexdigest(), value, time.monotonic() + 300,
            )
            return action_id

    def _owned(self, actor: str, action_id: str) -> PendingAction:
        self._prune()
        action = self._actions.get(action_id)
        if not actor or action is None or action.actor != hashlib.sha256(actor.encode()).hexdigest():
            raise PermissionError("Action unavailable for this actor")
        return action

    def decide(self, actor: str, action_id: str, approved: bool) -> None:
        if type(approved) is not bool:
            raise ValueError("An explicit human approve/deny decision is required")
        with self._lock:
            action = self._owned(actor, action_id)
            if action.decision != "pending":
                raise PermissionError("Decision is already final")
            action.decision = "approved" if approved else "denied"

    def execute(self, actor: str, action_id: str) -> str:
        with self._lock:
            action = self._owned(actor, action_id)
            if action.decision != "approved" or action_id in self._records:
                raise PermissionError("One-time human approval is required")
            self._records[action_id] = action.value
            return action.value

    def clear(self) -> None:
        with self._lock:
            self._actions.clear()
            self._records.clear()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SelfTestReport(StrictModel):
    demo_evidence: Literal[True] = True
    scope: Literal["local_runtime_controls_not_foundry_service"] = (
        "local_runtime_controls_not_foundry_service"
    )
    approval_actor: Literal["synthetic_test_fixture_not_human_approval"] = (
        "synthetic_test_fixture_not_human_approval"
    )
    policy_revision: str = POLICY_REVISION
    runtime_revision: str = RUNTIME_REVISION
    code_sha256: str
    policy_sha256: str
    configured_endpoint_count: int = Field(ge=0)
    checks: dict[str, bool]
    passed: bool


def runtime_code_digest(directory: Path | None = None) -> str:
    directory = directory or Path(__file__).parent
    return digest({
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in ("app.py", "governance.py", "catalog.json")
    })


def run_self_test(policy: GovernancePolicy, *, code_sha256: str | None = None) -> SelfTestReport:
    engine = GovernanceEngine(policy)
    checks: dict[str, bool] = {}

    def denied(operation: Any) -> bool:
        try:
            operation()
        except PermissionError:
            return True
        return False

    try:
        if policy.endpoints:
            allowed = sorted(policy.endpoints)[0]
            checks["endpoint_allowed"] = policy.require_endpoint(allowed) == allowed
        else:
            # A separate, explicitly synthetic fixture tests the same allow branch.
            fixture = GovernancePolicy(frozenset({"https://synthetic.invalid"}))
            checks["endpoint_allowed"] = fixture.require_endpoint(
                "https://synthetic.invalid",
            ) == "https://synthetic.invalid"
        checks["endpoint_denied"] = denied(
            lambda: policy.require_endpoint("https://unlisted.synthetic.invalid"),
        )
        checks["endpoint_credentials_denied"] = denied(
            lambda: policy.require_endpoint("https://user:password@synthetic.invalid"),
        )
        action_id = engine.propose("synthetic-actor", "synthetic-ready")
        checks["unapproved_denied"] = denied(lambda: engine.execute("synthetic-actor", action_id))
        checks["wrong_actor_denied"] = denied(
            lambda: engine.decide("synthetic-other", action_id, True),
        )
        engine.decide("synthetic-actor", action_id, False)
        checks["rejected_denied"] = denied(lambda: engine.execute("synthetic-actor", action_id))
        action_id = engine.propose("synthetic-actor", "synthetic-reviewed")
        engine.decide("synthetic-actor", action_id, True)
        checks["approved_executed"] = engine.execute(
            "synthetic-actor", action_id,
        ) == "synthetic-reviewed"
        checks["replay_denied"] = denied(lambda: engine.execute("synthetic-actor", action_id))
        action_id = engine.propose("synthetic-actor", "synthetic-ready")
        engine._actions[action_id].expires_at = 0
        checks["expired_denied"] = denied(lambda: engine.execute("synthetic-actor", action_id))
    finally:
        engine.clear()
    checks["state_cleaned"] = not engine._actions and not engine._records
    return SelfTestReport(
        code_sha256=code_sha256 or runtime_code_digest(), policy_sha256=policy.fingerprint,
        configured_endpoint_count=len(policy.endpoints),
        checks=checks, passed=set(checks) == CHECK_NAMES and all(checks.values()),
    )


class BaselineAsset(StrictModel):
    catalog_id: str
    platform: Literal["foundry", "langchain"]
    resource_id: str
    agent_id: str
    deployed_version: str | None = None


class DemoBaseline(StrictModel):
    demo_evidence: Literal[True]
    customer_policy_approved: Literal[False] = False
    catalog_sha256: str
    expected_policy_sha256: str | None = None
    required_budget_amount: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    assets: list[BaselineAsset]
    mandatory_tags: list[str] = Field(default_factory=lambda: ["owner", "sponsor", "env", "cost-center"])


class VerifiedRuntime(StrictModel):
    """Caller-supplied receipt of HTTPS observation AND successful deployment verification."""

    demo_evidence: Literal[True]
    verification: Literal["https_observed_and_deployment_verified"]
    resource_id: str
    deployment_id: str = Field(min_length=1)
    deployment_status: Literal["success"]
    verified_at: AwareDatetime
    deployed_code_sha256: str
    report: SelfTestReport


class PolicyFact(StrictModel):
    value: bool | dict[str, int]
    evidence_refs: list[str]


class PolicyProof(StrictModel):
    demo_evidence: Literal[True] = True
    customer_policy_approved: Literal[False] = False
    policy_facts: dict[str, PolicyFact] = Field(default_factory=dict)
    omitted: dict[str, str] = Field(default_factory=dict)
    deployment_required: list[str] = Field(default_factory=list)


def read_collection_file(path: Path) -> tuple[Collection, dict[str, Any]]:
    """Accept an explicit Collection or schema-v1 export; malformed wrappers never fall back."""
    from easm_agent.models import Collection

    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Collection JSON must be an object")
    if any(key in document for key in ("schema_version", "collection", "findings", "evidence")):
        if (
            type(document.get("schema_version")) is not int or document["schema_version"] != 1
            or not isinstance(document.get("collection"), dict)
            or not isinstance(document.get("findings"), list)
            or not isinstance(document.get("evidence"), dict)
            or any(
                not isinstance(key, str) or not isinstance(value, dict)
                for key, value in document["evidence"].items()
            )
        ):
            raise ValueError("Canonical raw JSON requires schema_version=1, collection, findings and evidence")
        return Collection.model_validate(document["collection"]), document["evidence"]
    return Collection.model_validate(document), {}


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except ValueError:
        return None


def _positive_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _notification_verified(note: Any) -> bool:
    if not isinstance(note, dict):
        return False
    receivers = [note.get(field) for field in ("contactEmails", "contactRoles", "contactGroups")]
    return (
        note.get("enabled") is True
        and note.get("operator") in ("GreaterThan", "GreaterThanOrEqualTo")
        and _positive_number(note.get("threshold"))
        and note.get("thresholdType") in ("Actual", "Forecasted")
        and all(isinstance(value, list) for value in receivers)
        and any(
            isinstance(value, str) and bool(value.strip())
            for values in receivers for value in values
        )
    )


def _budget_checks(
    row: dict[str, Any], source: dict[str, Any], subscription: str,
    collected_at: datetime, required_amount: float | None,
) -> dict[str, bool]:
    properties = row.get("properties")
    if not isinstance(properties, dict):
        return {"properties_known": False}
    period = properties.get("timePeriod")
    period = period if isinstance(period, dict) else {}
    start, end = _instant(period.get("startDate")), _instant(period.get("endDate"))
    observed = _instant(source.get("collected_at"))
    amount = properties.get("amount")
    notes = properties.get("notifications")
    notes = notes if isinstance(notes, dict) else {}
    prefix = f"/subscriptions/{subscription}/providers/microsoft.consumption/budgets/"
    identifier = row.get("id")
    try:
        target = urlsplit(source["target"]) if isinstance(source.get("target"), str) else None
    except ValueError:
        target = None
    return {
        "subscription_scope": (
            isinstance(identifier, str) and identifier.lower().startswith(prefix)
            and bool(identifier[len(prefix):]) and "/" not in identifier[len(prefix):]
        ),
        "subscription_list_source": (
            target is not None
            and target.scheme == "https" and target.netloc.lower() == "management.azure.com"
            and target.path.lower() == prefix.rstrip("/")
            and parse_qs(target.query).get("api-version") == ["2023-05-01"]
            and str(source.get("subscription_id", "")).lower() == subscription
        ),
        "unfiltered": properties.get("filter") == {},
        "effective_period": (
            start is not None and end is not None and observed is not None
            and start <= collected_at < end and start <= observed < end
        ),
        "cost_monthly": properties.get("category") == "Cost" and properties.get("timeGrain") == "Monthly",
        "amount_defined": _positive_number(amount),
        "required_amount_matches": (
            _positive_number(amount) and (required_amount is None or amount == required_amount)
        ),
        "notifications_known": bool(notes) and all(_notification_verified(note) for note in notes.values()),
        "actual_notification": any(
            _notification_verified(note) and note["thresholdType"] == "Actual" for note in notes.values()
        ),
        "forecast_notification": any(
            _notification_verified(note) and note["thresholdType"] == "Forecasted" for note in notes.values()
        ),
    }


def _budget_facts(
    data: Collection, baseline: DemoBaseline, sources: dict[str, Any],
    proof: PolicyProof, masked: dict[str, Any],
) -> None:
    subscriptions = {sid.lower() for sid in data.subscriptions}
    complete_entries = data.facts.get("budget_complete_subscriptions")
    complete = {
        sid.lower() for sid in complete_entries
    } if isinstance(complete_entries, list) and all(isinstance(sid, str) for sid in complete_entries) else set()
    masked["budget_checks"] = []
    if (
        "asset_standardized" not in proof.policy_facts or not subscriptions
        or not subscriptions <= complete
        or any(
            not agent.subscription_id or agent.subscription_id.lower() not in subscriptions
            for agent in data.agents if agent.platform in ("foundry", "langchain")
        )
        or any(issue.collector == "budgets" for issue in data.issues)
    ):
        proof.omitted["budget_assessment"] = "데모 자산/비용센터 기준 또는 전체 구독 예산 수집 완료 증거 없음"
        return
    coverage = []
    for subscription in sorted(subscriptions):
        candidates = []
        for budget in data.budgets:
            if budget.subscription_id.lower() != subscription:
                continue
            for ref in budget.evidence_refs:
                # Canonical exports use evidence:<key>; standalone embedded keys are explicit too.
                source = sources.get(ref.removeprefix("evidence:"))
                if not isinstance(source, dict):
                    continue
                response = source.get("response")
                rows = response.get("value") if isinstance(response, dict) else None
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict) or str(row.get("id", "")).lower() != budget.budget_id.lower():
                        continue
                    checks = _budget_checks(
                        row, source, subscription, data.collected_at, baseline.required_budget_amount,
                    )
                    properties = row.get("properties")
                    notes = properties.get("notifications") if isinstance(properties, dict) else None
                    checks["collected_budget_matches"] = (
                        isinstance(properties, dict) and isinstance(notes, dict)
                        and budget.amount == properties.get("amount")
                        and budget.category == properties.get("category")
                        and budget.time_grain == properties.get("timeGrain")
                        and budget.enabled_alerts == sum(
                            isinstance(note, dict) and note.get("enabled") is True
                            for note in notes.values()
                        )
                        and budget.forecast_alerts == sum(
                            isinstance(note, dict) and note.get("enabled") is True
                            and note.get("thresholdType") == "Forecasted"
                            for note in notes.values()
                        )
                    )
                    candidates.append({
                        "budget_sha256": digest(budget.budget_id.lower()),
                        "source_sha256": digest(source), "checks": checks,
                    })
        verified = any(all(candidate["checks"].values()) for candidate in candidates)
        coverage.append(verified)
        masked["budget_checks"].append({
            "subscription_sha256": digest(subscription), "verified": verified, "candidates": candidates,
        })
    if all(coverage):
        proof.policy_facts["budget_assessment"] = PolicyFact(
            value={"total": len(subscriptions), "compliant": len(subscriptions)}, evidence_refs=[],
        )
        proof.policy_facts["budget_standardized"] = PolicyFact(value=True, evidence_refs=[])
    else:
        proof.omitted["budget_assessment"] = (
            "전체 구독의 API 증적/무필터 범위/유효 기간/금액/실제 및 예측 수신 경보 확인 불완전"
        )


def generate_policy_facts(
    collection_path: Path,
    baseline: DemoBaseline,
    evidence_directory: Path,
    verified_runtimes: list[VerifiedRuntime] | None = None,
) -> PolicyProof:
    """Read saved evidence only; never update measured metrics or assume unknowns are zero."""
    data, sources = read_collection_file(collection_path)
    catalog = json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))
    proof = PolicyProof()
    proof.deployment_required = [
        "governance.py를 app.py와 함께 패키징한 후 승인된 배포 절차로 배포",
        "배포 성공 ID와 실제 HTTPS /health governance 보고서의 코드 해시를 대조",
        "로컬 테스트는 Foundry 도구 승인 또는 서비스 endpoint 집행 증거가 아님",
    ]
    agents = [agent for agent in data.agents if agent.platform in ("foundry", "langchain")]
    expected = {(asset.platform, asset.resource_id.lower(), asset.agent_id): asset for asset in baseline.assets}
    actual = {(agent.platform, (agent.resource_id or "").lower(), agent.agent_id): agent for agent in agents}
    reconciled = (
        data.facts.get("inventory_complete") is True
        and not any(issue.collector in ("inventory", "foundry_agents", "subscription") for issue in data.issues)
        and baseline.catalog_sha256 == digest(catalog)
        and {asset.catalog_id for asset in baseline.assets} == {entry["id"] for entry in catalog}
        and len(expected) == len(baseline.assets) == len(catalog)
        and len(actual) == len(agents) == len(expected)
        and set(expected) == set(actual)
        and all(
            next(entry["platform"] for entry in catalog if entry["id"] == asset.catalog_id) == asset.platform
            for asset in baseline.assets
        )
    )
    # Store only hashes, booleans and counts; do not copy source tags, identities, URLs or receipts.
    masked: dict[str, Any] = {
        "demo_evidence": True, "customer_policy_approved": False,
        "collection_sha256": hashlib.sha256(collection_path.read_bytes()).hexdigest(),
        "baseline_sha256": digest(baseline.model_dump(mode="json")),
        "catalog_sha256": digest(catalog), "reconciled": reconciled,
        "agent_count": len(agents), "asset_checks": [], "runtime_checks": [],
    }
    if reconciled and {"owner", "sponsor", "env", "cost-center"} <= set(baseline.mandatory_tags):
        complete_tags = all(
            all(
                bool(agent.tags.get(tag) or (getattr(agent, tag, None) if tag in ("owner", "sponsor") else None))
                and agent.tags.get(tag) != "[REDACTED]"
                for tag in baseline.mandatory_tags
            )
            for agent in agents
        )
        complete_tags = complete_tags and all(
            actual[key].tags.get("env") == next(
                row["env"] for row in catalog if row["id"] == asset.catalog_id
            )
            for key, asset in expected.items()
        )
        masked["asset_checks"] = [
            {"asset_sha256": digest(key), "metadata_present": all(
                bool(agent.tags.get(tag) or (getattr(agent, tag, None) if tag in ("owner", "sponsor") else None))
                for tag in baseline.mandatory_tags
            )} for key, agent in actual.items()
        ]
        if complete_tags:
            proof.policy_facts["asset_standardized"] = PolicyFact(value=True, evidence_refs=[])
        else:
            proof.omitted["asset_standardized"] = "필수 메타데이터/환경 대조 실패 또는 마스킹으로 표준 준수 미확인"
    else:
        proof.omitted["asset_standardized"] = "전체 카탈로그/수집 범위/필수 메타데이터 기준 대조 불완전"
    _budget_facts(data, baseline, sources, proof, masked)
    runtimes: dict[str, VerifiedRuntime] = {}
    for runtime in verified_runtimes or []:
        report = runtime.report
        valid = (
            report.passed and set(report.checks) == CHECK_NAMES and all(report.checks.values())
            and report.code_sha256 == runtime.deployed_code_sha256 == runtime_code_digest()
            and report.policy_revision == POLICY_REVISION and report.runtime_revision == RUNTIME_REVISION
            and baseline.expected_policy_sha256 is not None
            and baseline.expected_policy_sha256 == report.policy_sha256
            and report.configured_endpoint_count > 0
            and runtime.verified_at <= data.collected_at
        )
        masked["runtime_checks"].append({
            "resource_sha256": digest(runtime.resource_id.lower()), "verified": valid,
            "code_sha256": report.code_sha256, "policy_sha256": report.policy_sha256,
        })
        if valid:
            runtimes[runtime.resource_id.lower()] = runtime
    controlled = (
        reconciled and bool(agents)
        and all(agent.platform == "langchain" and (agent.resource_id or "").lower() in runtimes for agent in agents)
    )
    # A host test cannot stand in for remote Foundry/MCP tool execution.
    for name in ("tool_approval", "endpoint"):
        if controlled and all(agent.tools is not None for agent in agents):
            proof.policy_facts[name + "_assessment"] = PolicyFact(
                value={"total": len(agents), "compliant": len(agents)}, evidence_refs=[],
            )
            proof.policy_facts[name + "_standardized"] = PolicyFact(value=True, evidence_refs=[])
        else:
            proof.omitted[name + "_assessment"] = (
                "전체 대상의 도구/endpoint 실행 범위와 검증 배포 증거가 없음 - Foundry 서비스는 로컬 gate 범위 밖"
            )
    releases = [
        agent.agent_version is not None and agent.deployed_at is not None
        and expected[key].deployed_version == agent.agent_version and bool(agent.evidence_refs)
        for key, agent in actual.items()
    ] if reconciled else []
    if controlled and releases and all(releases):
        proof.policy_facts["release_assessment"] = PolicyFact(
            value={"total": len(releases), "compliant": sum(releases)}, evidence_refs=[],
        )
        proof.policy_facts["release_standardized"] = PolicyFact(value=True, evidence_refs=[])
    else:
        proof.omitted["release_assessment"] = "실제 배포 시각/버전/대상별 배포 증거 불충분 - 버전 생성은 배포가 아님"
    evidence_directory.mkdir(parents=True, exist_ok=True)
    proof_path = evidence_directory / ("demo-governance-" + digest(masked)[:16] + ".json")
    proof_path.write_text(json.dumps(masked, indent=2, ensure_ascii=False), encoding="utf-8")
    for fact in proof.policy_facts.values():
        fact.evidence_refs = [str(proof_path)]
    return proof
