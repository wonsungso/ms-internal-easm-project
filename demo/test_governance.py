from __future__ import annotations

import json
import os
import shutil
import site
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from demo.governance import (
    CHECK_NAMES,
    BaselineAsset,
    DemoBaseline,
    GovernanceEngine,
    GovernancePolicy,
    VerifiedRuntime,
    digest,
    generate_policy_facts,
    read_collection_file,
    run_self_test,
)
from wasm_agent.models import AgentEvidence, Budget, Collection


@pytest.fixture
def work_directory():
    directory = Path(".wasm-agent") / ("governance-tests-" + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


@pytest.fixture
def policy() -> GovernancePolicy:
    return GovernancePolicy.from_environment({"AZURE_OPENAI_ENDPOINT": "https://model.example/"})


@pytest.mark.parametrize("endpoint", [
    "http://model.example", "https://model.example.evil", "https://model.example@evil.example",
    "https://model.example?secret=test", "https://model.example/#fragment",
    "https://model.example:8443", "https://model.example/other",
    "https://model.example/../", "https://model.example/%2e", "https://model.example\\evil",
    "https://model.example:invalid", "https://user:password@model.example",
])
def test_external_endpoint_is_deny_by_default(policy: GovernancePolicy, endpoint: str) -> None:
    with pytest.raises(PermissionError):
        policy.require_endpoint(endpoint)


def test_exact_endpoint_and_empty_policy(policy: GovernancePolicy) -> None:
    assert policy.require_endpoint("https://MODEL.example:443/") == "https://MODEL.example:443/"
    with pytest.raises(PermissionError):
        GovernancePolicy.from_environment({}).require_endpoint("https://model.example")


def test_approval_is_actor_bound_one_time_and_expiring(policy: GovernancePolicy) -> None:
    engine = GovernanceEngine(policy)
    action_id = engine.propose("human-a", "synthetic-ready")
    with pytest.raises(PermissionError):
        engine.execute("human-a", action_id)
    assert not engine._records
    with pytest.raises(PermissionError):
        engine.decide("human-b", action_id, True)
    with pytest.raises(ValueError):
        engine.decide("human-a", action_id, "true")
    engine.decide("human-a", action_id, True)
    assert engine.execute("human-a", action_id) == "synthetic-ready"
    with pytest.raises(PermissionError):
        engine.execute("human-a", action_id)
    engine._actions[action_id].expires_at = 0
    with pytest.raises(PermissionError):
        engine.execute("human-a", action_id)
    assert not engine._records and not engine._actions


def test_denial_is_final_and_arbitrary_values_never_written(policy: GovernancePolicy) -> None:
    engine = GovernanceEngine(policy)
    with pytest.raises(ValueError):
        engine.propose("human-a", "customer-secret")
    action_id = engine.propose("human-a", "synthetic-reviewed")
    engine.decide("human-a", action_id, False)
    with pytest.raises(PermissionError):
        engine.decide("human-a", action_id, True)
    with pytest.raises(PermissionError):
        engine.execute("human-a", action_id)
    assert not engine._records
    engine.clear()
    assert not engine._actions


def test_action_capacity_is_bounded(policy: GovernancePolicy) -> None:
    engine = GovernanceEngine(policy)
    for _ in range(256):
        engine.propose("human-a", "synthetic-ready")
    with pytest.raises(ValueError):
        engine.propose("human-a", "synthetic-ready")
    engine.clear()


def test_report_is_deterministic_nonsecret_and_cleans_state(policy: GovernancePolicy) -> None:
    report = run_self_test(policy)
    assert report == run_self_test(policy)
    assert report.passed and set(report.checks) == CHECK_NAMES and all(report.checks.values())
    serialized = report.model_dump_json()
    assert "model.example" not in serialized and "human-a" not in serialized
    assert report.approval_actor == "synthetic_test_fixture_not_human_approval"
    assert report.scope == "local_runtime_controls_not_foundry_service"
    assert run_self_test(GovernancePolicy.from_environment({})).passed


def test_standalone_deployed_import_needs_no_collector_package_or_network(work_directory: Path) -> None:
    for dependency in (
        "flask", "azure.ai.projects", "azure.identity", "langchain",
        "langchain_core", "langchain_openai", "openai", "pydantic",
    ):
        try:
            available = find_spec(dependency) is not None
        except ModuleNotFoundError:
            available = False
        if not available:
            pytest.skip(f"Demo runtime dependency is not installed in this interpreter: {dependency}")
    directory = work_directory / "deployed"
    directory.mkdir()
    for name in ("app.py", "governance.py", "catalog.json", "chat.html"):
        shutil.copyfile(Path("demo") / name, directory / name)
    script = r'''
import builtins
import json
import socket
import sys
from pathlib import Path

excluded = {Path(value).resolve() for value in json.loads(sys.argv[2])}
sys.path = [value for value in sys.path if Path(value).resolve() not in excluded]
# Add dependency directories directly, without processing editable-install .pth files.
sys.path.extend(json.loads(sys.argv[1]))
sys.path.insert(0, ".")
assert all(Path(value).resolve() not in excluded for value in sys.path)
original_import = builtins.__import__
collector_only = {"wasm_agent", "demo", "yaml"}

def guarded_import(name, *args, **kwargs):
    if name.split(".")[0] in collector_only:
        raise AssertionError("Deployed runtime imported a collector-only package: " + name)
    return original_import(name, *args, **kwargs)

def blocked_network(*args, **kwargs):
    raise AssertionError("Standalone import or health attempted a network connection")

builtins.__import__ = guarded_import
socket.socket.connect = blocked_network
socket.socket.connect_ex = blocked_network
socket.create_connection = blocked_network
import governance
# Existing LangChain runtime dependencies import PyYAML; governance itself must not.
collector_only.remove("yaml")
import app
with app.app.test_client() as client:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json["governance"]["passed"]
    assert response.json["smoke_status"] == "not_requested"
    print(json.dumps({"health": response.status_code, "standalone": True, "network": False}))
'''
    environment = dict(os.environ)
    environment.update({
        "WASMAGENT_SMOKE_ON_START": "false",
        "AZURE_OPENAI_ENDPOINT": "https://synthetic.invalid",
        "AZURE_AI_PROJECT_ENDPOINT": "",
    })
    environment.pop("PYTHONPATH", None)
    dependency_directories = {
        str(Path(value).resolve())
        for value in [*site.getsitepackages(), site.getusersitepackages()]
        if Path(value).is_dir()
    }
    dependencies = list(dict.fromkeys(
        str(Path(value).resolve()) for value in sys.path
        if value and str(Path(value).resolve()) in dependency_directories
    ))
    excluded = [str(Path.cwd().resolve()), str((Path.cwd() / "src").resolve())]
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, json.dumps(dependencies), json.dumps(excluded)],
        cwd=directory, env=environment,
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"health": 200, "standalone": True, "network": False}


@pytest.fixture
def saved_collection(work_directory: Path):
    catalog = json.loads((Path("demo") / "catalog.json").read_text(encoding="utf-8"))
    now = datetime.now(UTC)
    assets = [
        BaselineAsset(
            catalog_id=row["id"], platform=row["platform"], resource_id="/synthetic/" + row["id"],
            agent_id=row["id"], deployed_version="v1",
        )
        for row in catalog
    ]
    baseline = DemoBaseline(demo_evidence=True, catalog_sha256=digest(catalog), assets=assets)
    data = Collection(
        collected_at=now,
        facts={"inventory_complete": True},
        agents=[
            AgentEvidence(
                collected_at=now, platform=asset.platform, resource_id=asset.resource_id,
                agent_id=asset.agent_id, agent_name=asset.catalog_id, agent_version="v1",
                detection_confidence="tag",
                tags={"owner": "synthetic-owner", "sponsor": "synthetic-sponsor",
                      "env": next(row["env"] for row in catalog if row["id"] == asset.catalog_id),
                      "cost-center": "synthetic-cost"},
                tools=["function"] if asset.catalog_id == "privacy-helper" else [],
            )
            for asset in assets
        ],
    )
    path = work_directory / "collection.json"
    path.write_text(data.model_dump_json(), encoding="utf-8")
    return path, baseline, data


def test_policy_facts_reconcile_all_catalog_assets_without_metric_override(
    saved_collection, work_directory: Path,
) -> None:
    path, baseline, _ = saved_collection
    proof = generate_policy_facts(path, baseline, work_directory / "evidence")
    assert set(proof.policy_facts) == {"asset_standardized"}
    assert proof.policy_facts["asset_standardized"].value is True
    assert {"tool_approval_assessment", "endpoint_assessment", "release_assessment"} <= set(proof.omitted)
    assert proof.deployment_required
    ref = Path(proof.policy_facts["asset_standardized"].evidence_refs[0])
    stored = ref.read_text(encoding="utf-8")
    assert '"reconciled": true' in stored and '"demo_evidence": true' in stored
    assert "synthetic-owner" not in stored and "/synthetic/" not in stored
    assert "asset_tag_ratio" not in proof.policy_facts


def test_real_schema_v1_wrapper_is_explicitly_supported(saved_collection, work_directory: Path) -> None:
    path, baseline, data = saved_collection
    document = {
        "schema_version": 1, "collection": data.model_dump(mode="json"), "findings": [],
        "evidence": {}, "mode": "live", "provenance": {}, "manifest": {},
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    loaded, sources = read_collection_file(path)
    assert loaded == data and sources == {}
    proof = generate_policy_facts(path, baseline, work_directory / "evidence")
    assert proof.policy_facts["asset_standardized"].value is True


@pytest.mark.parametrize("change", ["schema2", "bool_schema", "missing_collection", "missing_findings",
                                         "missing_evidence", "invalid_evidence"])
def test_malformed_wrapper_never_falls_back_to_collection(saved_collection, change: str) -> None:
    path, _, data = saved_collection
    document = {
        "schema_version": 1, "collection": data.model_dump(mode="json"), "findings": [], "evidence": {},
    }
    if change == "schema2":
        document["schema_version"] = 2
    elif change == "bool_schema":
        document["schema_version"] = True
    elif change.startswith("missing_"):
        document.pop(change.removeprefix("missing_"))
    else:
        document["evidence"] = {"unreadable": "not-an-object"}
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="Canonical raw JSON"):
        read_collection_file(path)


@pytest.fixture
def budget_document(saved_collection):
    path, baseline, data = saved_collection
    data.subscriptions = ["synthetic-sub-1", "synthetic-sub-2", "synthetic-sub-3"]
    data.facts["budget_complete_subscriptions"] = list(data.subscriptions)
    baseline.required_budget_amount = 100
    for index, agent in enumerate(data.agents):
        agent.subscription_id = data.subscriptions[index % 3]
    sources = {}
    for subscription in data.subscriptions:
        budget_id = f"/subscriptions/{subscription}/providers/Microsoft.Consumption/budgets/synthetic"
        notification = {
            "enabled": True, "operator": "GreaterThan", "threshold": 80,
            "contactEmails": [], "contactRoles": [], "contactGroups": ["synthetic-action-group"],
        }
        source = {
            "target": "https://management.azure.com" + budget_id.rsplit("/", 1)[0] + "?api-version=2023-05-01",
            "subscription_id": subscription,
            "collected_at": (data.collected_at + timedelta(seconds=1)).isoformat(),
            "response": {"value": [{
                "id": budget_id,
                "properties": {
                    "amount": 100, "category": "Cost", "timeGrain": "Monthly", "filter": {},
                    "timePeriod": {
                        "startDate": (data.collected_at - timedelta(days=1)).isoformat(),
                        "endDate": (data.collected_at + timedelta(days=365)).isoformat(),
                    },
                    "notifications": {
                        "actual": notification | {"thresholdType": "Actual"},
                        "forecast": notification | {"thresholdType": "Forecasted"},
                    },
                },
            }]},
        }
        reference = digest(source)
        sources[reference] = source
        data.budgets.append(Budget(
            subscription_id=subscription, budget_id=budget_id, amount=100,
            category="Cost", time_grain="Monthly", enabled_alerts=2, forecast_alerts=1,
            evidence_refs=["evidence:" + reference],
        ))
    document = {
        "schema_version": 1, "collection": data.model_dump(mode="json"), "findings": [],
        "evidence": sources, "mode": "live", "provenance": {}, "manifest": {},
    }
    return path, baseline, document


def test_budget_grade_facts_require_all_subscription_api_proofs(
    budget_document, work_directory: Path,
) -> None:
    path, baseline, document = budget_document
    path.write_text(json.dumps(document), encoding="utf-8")
    proof = generate_policy_facts(path, baseline, work_directory / "evidence")
    assert proof.policy_facts["budget_assessment"].value == {"total": 3, "compliant": 3}
    assert proof.policy_facts["budget_standardized"].value is True
    stored = Path(proof.policy_facts["budget_assessment"].evidence_refs[0]).read_text(encoding="utf-8")
    assert "synthetic-action-group" not in stored and "synthetic-sub-" not in stored
    assert len(json.loads(stored)["budget_checks"]) == 3
    assert "budget_enforced" not in proof.policy_facts and "budget_improved" not in proof.policy_facts


@pytest.mark.parametrize("change", [
    "expired", "future_start", "period_missing", "filter_missing", "filtered", "amount_mismatch",
    "amount_unknown", "amount_bool", "wrong_scope", "wrong_api", "source_time_missing",
    "missing_forecast", "disabled_forecast", "unknown_type", "unknown_operator", "unknown_threshold",
    "no_receivers", "receiver_field_missing", "missing_source", "collection_incomplete",
    "simplified_only", "cost_center_missing", "missing_subscription", "unknown_source_target",
    "conflicting_collected_amount", "unknown_completeness",
])
def test_budget_unknown_or_noncompliant_controls_are_omitted_not_zero(
    budget_document, work_directory: Path, change: str,
) -> None:
    path, baseline, document = budget_document
    source = next(iter(document["evidence"].values()))
    row = source["response"]["value"][0]
    properties = row["properties"]
    forecast = properties["notifications"]["forecast"]
    collected = datetime.fromisoformat(document["collection"]["collected_at"])
    if change == "expired":
        properties["timePeriod"]["endDate"] = (collected - timedelta(days=1)).isoformat()
    elif change == "future_start":
        properties["timePeriod"]["startDate"] = (collected + timedelta(days=1)).isoformat()
    elif change == "period_missing":
        properties.pop("timePeriod")
    elif change == "filter_missing":
        properties.pop("filter")
    elif change == "filtered":
        properties["filter"] = {"dimensions": {"name": "ResourceGroupName", "values": ["partial"]}}
    elif change == "amount_mismatch":
        properties["amount"] = 2250
    elif change == "amount_unknown":
        properties["amount"] = None
    elif change == "amount_bool":
        properties["amount"] = True
    elif change == "wrong_scope":
        row["id"] = row["id"].replace("/providers/", "/resourceGroups/partial/providers/")
        document["collection"]["budgets"][0]["budget_id"] = row["id"]
    elif change == "wrong_api":
        source["target"] = source["target"].replace("2023-05-01", "unknown")
    elif change == "source_time_missing":
        source.pop("collected_at")
    elif change == "missing_forecast":
        properties["notifications"].pop("forecast")
    elif change == "disabled_forecast":
        forecast["enabled"] = False
    elif change == "unknown_type":
        forecast.pop("thresholdType")
    elif change == "unknown_operator":
        forecast["operator"] = "Unknown"
    elif change == "unknown_threshold":
        forecast["threshold"] = None
    elif change == "no_receivers":
        forecast["contactGroups"] = []
    elif change == "receiver_field_missing":
        forecast.pop("contactEmails")
    elif change == "missing_source":
        document["evidence"].clear()
    elif change == "collection_incomplete":
        document["collection"]["facts"]["budget_complete_subscriptions"].pop(0)
    elif change == "simplified_only":
        document = document["collection"]
    elif change == "cost_center_missing":
        document["collection"]["agents"][0]["tags"].pop("cost-center")
    elif change == "missing_subscription":
        document["collection"]["agents"][0]["subscription_id"] = None
    elif change == "unknown_source_target":
        source["target"] = None
    elif change == "conflicting_collected_amount":
        document["collection"]["budgets"][0]["amount"] = 2250
    elif change == "unknown_completeness":
        document["collection"]["facts"]["budget_complete_subscriptions"] = None
    path.write_text(json.dumps(document), encoding="utf-8")
    proof = generate_policy_facts(path, baseline, work_directory / "evidence")
    assert "budget_assessment" not in proof.policy_facts
    assert "budget_standardized" not in proof.policy_facts
    assert "budget_assessment" in proof.omitted


def test_budget_amount_requirement_is_optional_but_never_inferred(
    budget_document, work_directory: Path,
) -> None:
    path, baseline, document = budget_document
    baseline.required_budget_amount = None
    for source in document["evidence"].values():
        source["response"]["value"][0]["properties"]["amount"] = 2250
    for budget in document["collection"]["budgets"]:
        budget["amount"] = 2250
    path.write_text(json.dumps(document), encoding="utf-8")
    proof = generate_policy_facts(path, baseline, work_directory / "evidence")
    assert proof.policy_facts["budget_assessment"].value == {"total": 3, "compliant": 3}


@pytest.mark.parametrize("change", [
    "unknown_inventory", "missing_agent", "extra_agent", "missing_tag", "catalog_drift",
    "metadata_redacted", "duplicate_baseline", "wrong_environment",
])
def test_unknown_or_incomplete_prerequisites_never_become_zero(
    saved_collection, work_directory: Path, change: str,
) -> None:
    path, baseline, data = saved_collection
    if change == "unknown_inventory":
        data.facts.clear()
    elif change == "missing_agent":
        data.agents.pop()
    elif change == "extra_agent":
        extra = data.agents[0].model_copy(deep=True)
        extra.agent_id = "unreconciled"
        data.agents.append(extra)
    elif change == "missing_tag":
        data.agents[0].tags.pop("sponsor")
    elif change == "catalog_drift":
        baseline.catalog_sha256 = "stale"
    elif change == "metadata_redacted":
        data.agents[0].tags["owner"] = "[REDACTED]"
    elif change == "duplicate_baseline":
        baseline.assets[-1] = baseline.assets[0]
    elif change == "wrong_environment":
        data.agents[0].tags["env"] = "unapproved-production"
    path.write_text(data.model_dump_json(), encoding="utf-8")
    proof = generate_policy_facts(path, baseline, work_directory / "evidence")
    assert not proof.policy_facts
    assert "asset_standardized" in proof.omitted


def test_verified_host_test_cannot_certify_foundry_or_version_creation(
    saved_collection, work_directory: Path, policy: GovernancePolicy,
) -> None:
    path, baseline, data = saved_collection
    report = run_self_test(policy)
    baseline.expected_policy_sha256 = report.policy_sha256
    runtime = VerifiedRuntime(
        demo_evidence=True, verification="https_observed_and_deployment_verified",
        resource_id=data.agents[0].resource_id, deployment_id="synthetic-deployment",
        deployment_status="success", verified_at=data.collected_at - timedelta(seconds=1),
        deployed_code_sha256=report.code_sha256, report=report,
    )
    proof = generate_policy_facts(path, baseline, work_directory / "evidence", [runtime])
    assert set(proof.policy_facts) == {"asset_standardized"}
    assert "release_assessment" in proof.omitted
    report.code_sha256 = "wrong-build"
    proof = generate_policy_facts(path, baseline, work_directory / "evidence", [runtime])
    stored = json.loads(Path(proof.policy_facts["asset_standardized"].evidence_refs[0]).read_text())
    assert stored["runtime_checks"][0]["verified"] is False


def test_baseline_must_be_explicitly_demo_only() -> None:
    with pytest.raises(ValueError):
        DemoBaseline(demo_evidence=False, catalog_sha256="hash", assets=[])


@pytest.mark.parametrize("amount", [True, 0, -1, float("inf"), float("nan"), "100"])
def test_required_budget_amount_must_be_explicit_positive_number(amount) -> None:
    with pytest.raises(ValueError):
        DemoBaseline(demo_evidence=True, catalog_sha256="hash", assets=[], required_budget_amount=amount)


def test_app_control_paths_are_real_and_auth_protected(monkeypatch: pytest.MonkeyPatch) -> None:
    chat = pytest.importorskip("demo.app", exc_type=ImportError)
    monkeypatch.setenv("WASMAGENT_CHAT_ALLOWED_OIDS", "allowed-user,other-user")
    monkeypatch.setenv("WASMAGENT_LOCAL_AGENT", "langchain-tools")
    monkeypatch.delenv("WEBSITE_HOSTNAME", raising=False)
    chat.governance.clear()
    headers = {
        "X-MS-CLIENT-PRINCIPAL-ID": "allowed-user", "Origin": "http://localhost",
        "X-WASMAgent-Chat": "1",
    }
    try:
        with chat.app.test_client() as client:
            assert client.post("/api/governance/actions", json={"value": "synthetic-ready"}).status_code == 403
            assert client.post(
                "/api/governance/actions", json={"value": "synthetic-ready"},
                headers=headers | {"Origin": "https://foreign.example"},
            ).status_code == 403
            proposed = client.post(
                "/api/governance/actions", json={"value": "synthetic-ready"}, headers=headers,
            )
            assert proposed.status_code == 201 and proposed.json["status"] == "pending"
            action_id = proposed.json["action_id"]
            with chat.app.test_request_context(headers=headers):
                assert chat.synthetic_record.invoke({"action_id": action_id}).startswith("denied:")
            decision = "/api/governance/actions/" + action_id + "/decision"
            assert client.post(decision, json={"approved": True}, headers=headers | {
                "X-MS-CLIENT-PRINCIPAL-ID": "other-user",
            }).status_code == 403
            assert client.post(decision, json={"approved": "true"}, headers=headers).status_code == 400
            assert client.post(decision, json={"approved": True}, headers=headers).status_code == 200
            with chat.app.test_request_context(headers=headers):
                assert chat.synthetic_record.invoke({"action_id": action_id}) == "demo evidence: synthetic-ready"
                assert chat.synthetic_record.invoke({"action_id": action_id}).startswith("denied:")
            with patch.object(chat, "invoke_agent", side_effect=AssertionError("No model call")):
                health = client.get("/health")
            assert health.status_code == 200 and health.json["governance"]["passed"]
            assert "allowed-user" not in health.text and action_id not in health.text
        assert chat.synthetic_record.invoke({"action_id": action_id}).startswith("denied:")
    finally:
        chat.governance.clear()


@pytest.mark.parametrize("platform,setting", [
    ("langchain", "AZURE_OPENAI_ENDPOINT"), ("foundry", "AZURE_AI_PROJECT_ENDPOINT"),
])
def test_app_endpoint_gate_precedes_credentials_and_model(
    monkeypatch: pytest.MonkeyPatch, platform: str, setting: str,
) -> None:
    chat = pytest.importorskip("demo.app", exc_type=ImportError)
    monkeypatch.setenv(setting, "https://unlisted.synthetic.invalid")
    with patch.object(chat, "DefaultAzureCredential", side_effect=AssertionError("No credential call")):
        with pytest.raises(PermissionError):
            chat.invoke_agent({"platform": platform}, [])


def test_real_langchain_construction_registers_execution_but_not_approval(
    monkeypatch: pytest.MonkeyPatch, policy: GovernancePolicy,
) -> None:
    chat = pytest.importorskip("demo.app", exc_type=ImportError)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://model.example")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "synthetic-model")
    monkeypatch.setattr(chat, "governance", GovernanceEngine(policy))
    message = SimpleNamespace(
        type="ai", content="synthetic-answer", usage_metadata={"input_tokens": 1, "output_tokens": 2},
    )
    with (
        patch.object(chat, "DefaultAzureCredential"),
        patch.object(chat, "get_bearer_token_provider"),
        patch.object(chat, "AzureChatOpenAI") as model,
        patch.object(chat, "create_agent") as create,
    ):
        create.return_value.invoke.return_value = {"messages": [message]}
        result = chat.invoke_agent({"platform": "langchain", "tools": True, "instructions": "synthetic"}, [])
    assert result == ("synthetic-answer", 1, 2)
    assert model.call_args.kwargs["azure_endpoint"] == "https://model.example"
    assert {tool.name for tool in create.call_args.kwargs["tools"]} == {"governance_scope", "synthetic_record"}
