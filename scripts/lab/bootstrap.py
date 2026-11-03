from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    FixedRatioVersionSelectionRule,
    PromptAgentDefinition,
    ProtocolConfiguration,
    ResponsesProtocolConfiguration,
    VersionSelector,
)
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from openai import APIStatusError

from scripts.setup.setup_account import ensure_assignment, role_spec, verify_custom_role
from wasm_agent.utils.evidence import redact

from .package import build_linux_package
from .zipdeploy import deploy_zip

ARM = "https://management.azure.com"
FOUNDRY_USER = "53ca6127-db72-4b80-b1b0-d745d6d5456d"
OPENAI_USER = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"


class AdminARM:
    def __init__(self, credential: DefaultAzureCredential, groups: list[str], create_missing: bool = True) -> None:
        self.credential, self.groups = credential, [group.lower() for group in groups]
        self.session = requests.Session()
        self.create_missing = create_missing

    def request(self, method: str, resource_id: str, version: str,
                body: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not any(resource_id.lower().startswith(group + "/") for group in self.groups):
            raise ValueError("관리자 샘플 API가 승인된 리소스 그룹 밖을 요청했습니다.")
        token = self.credential.get_token(ARM + "/.default").token
        url = ARM + resource_id + "?api-version=" + version
        for attempt in range(5):
            response = self.session.request(
                method, url, json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=(10, 90), allow_redirects=False,
            )
            status = response.status_code
            if status in (429, 500, 502, 503, 504) and attempt < 4:
                response.close()
                time.sleep(2**attempt)
                continue
            if status == 404 and method == "GET":
                response.close()
                return None
            if not 200 <= status < 300:
                try:
                    error_code = (response.json().get("error") or {}).get("code", "")
                except ValueError:
                    error_code = ""
                response.close()
                safe_code = error_code if re.fullmatch(r"[A-Za-z0-9._-]{1,100}", error_code) else "unknown"
                raise RuntimeError(
                    f"샘플 관리 API {method} 실패: HTTP {status}, code={safe_code}; 응답 본문 비출력"
                )
            try:
                return response.json() if response.content else {}
            finally:
                response.close()
        raise AssertionError("unreachable")

    def ensure(self, rid: str, version: str, body: dict[str, Any], lab_id: str,
               child: bool = False) -> dict[str, Any]:
        existing = self.request("GET", rid, version)
        if existing and not child and (existing.get("tags") or {}).get("seagent-lab") != lab_id:
            raise RuntimeError("동명 리소스의 샘플 소유 태그가 다릅니다. 덮어쓰지 않습니다.")
        if not existing:
            if not self.create_missing:
                raise RuntimeError("재사용 모드의 필수 샘플 리소스가 없습니다. 새 리소스를 임의 생성하지 않습니다.")
            self.request("PUT", rid, version, body)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            result = self.request("GET", rid, version)
            if result:
                state = (result.get("properties") or {}).get("provisioningState")
                if state in ("Failed", "Canceled"):
                    raise RuntimeError(f"샘플 provisioningState={state}")
                if not state or state in ("Succeeded", "Ready"):
                    return result
            time.sleep(10)
        raise RuntimeError("샘플 리소스 생성 확인 시간 초과")


def plan(setup: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    region = options["region"]
    if len(setup["subscription_ids"]) != 3:
        raise ValueError("승인된 3개 구독 설정이 필요합니다.")
    identity = setup["tenant_id"] + setup["client_id"] + str(options.get("generation", ""))
    lab_id = hashlib.sha256(identity.encode()).hexdigest()[:10]
    groups = [
        {"subscription_id": sid, "name": f"{options['resource_group_prefix']}-{index:02d}",
         "id": f"/subscriptions/{sid}/resourceGroups/{options['resource_group_prefix']}-{index:02d}"}
        for index, sid in enumerate(setup["subscription_ids"], 1)
    ]
    return {
        "lab_id": lab_id, "region": region, "groups": groups,
        "account_name": f"seagent-{lab_id}", "project_name": options["project_name"],
        "deployment_name": options["deployment_name"], "model": options["model"],
        "model_version": options["model_version"], "sku": options["model_sku"], "capacity": options["model_capacity"],
        "host_names": [f"seagent-lc-{lab_id}-02", f"seagent-lc-{lab_id}-03"],
        "retention_days": options["retention_days"], "after_run": options["after_run"],
        "budget_usd": options["budget_usd"],
        "b1_plans_usd_per_hour": 0.036,
    }


def deployment_parameters(lab: dict[str, Any], index: int) -> list[str]:
    group = lab["groups"][index]
    parameters = {
        "location": lab["region"], "resourceGroupName": group["name"],
        "labId": lab["lab_id"], "workload": "foundry" if index == 0 else "langchain",
        "accountName": lab["account_name"], "projectName": lab["project_name"],
        "deploymentName": lab["deployment_name"], "modelName": lab["model"],
        "modelVersion": lab["model_version"], "modelSku": lab["sku"],
        "modelCapacity": lab["capacity"], "retentionDays": lab["retention_days"],
        "hostName": "" if index == 0 else lab["host_names"][index - 1],
        "modelResourceId": lab["groups"][0]["id"]
        + "/providers/Microsoft.CognitiveServices/accounts/" + lab["account_name"],
    }
    return [f"{key}={value}" for key, value in parameters.items()]


def deploy(
    cli: Any, setup: dict[str, Any], options: dict[str, Any], root: Path,
    reuse_infrastructure: bool = False,
) -> dict[str, Any]:
    result = plan(setup, options)
    region = result["region"]
    current = cli.run("account", "show")
    if current["tenantId"].lower() != setup["tenant_id"]:
        raise ValueError("관리자 테넌트 불일치. 디바이스 코드로 올바른 테넌트에 로그인하세요.")
    lab_id, groups = result["lab_id"], result["groups"]
    tags = {"seagent-lab": lab_id, "owner": "governance-sample-team",
            "sponsor": "governance-sample", "env": "test", "cost-center": "governance-lab"}
    for index, group in enumerate(groups):
        sid = group["subscription_id"]
        providers = cli.run("provider", "list", "--subscription", sid)
        required = ["Microsoft.OperationalInsights", "Microsoft.Insights",
                    "Microsoft.CognitiveServices" if group is groups[0] else "Microsoft.Web"]
        for namespace in required:
            state = next((p["registrationState"] for p in providers
                          if p["namespace"].lower() == namespace.lower()), None)
            if state != "Registered":
                cli.run("provider", "register", "--namespace", namespace, "--subscription", sid, "--wait")
        existing = next((row for row in cli.run("group", "list", "--subscription", sid)
                         if row["name"].lower() == group["name"]), None)
        if existing and (existing.get("tags") or {}).get("seagent-lab") != lab_id:
            raise RuntimeError("샘플 그룹 이름이 기존 다른 그룹과 충돌합니다.")
        if reuse_infrastructure and not existing:
            raise RuntimeError("재사용할 샘플 그룹이 없습니다.")
        if existing:
            for resource in cli.run("resource", "list", "--resource-group", group["name"], "--subscription", sid):
                if resource["type"].lower() == "microsoft.cognitiveservices/accounts/deployments":
                    continue
                if (resource.get("tags") or {}).get("seagent-lab") != lab_id:
                    raise RuntimeError("샘플 그룹 안에 소유 태그가 다른 리소스가 있습니다. 덮어쓰지 않습니다.")
        print(f"샘플 인프라 {'재사용' if reuse_infrastructure else '배포'}: 구독 {index + 1}/3, "
              f"workload={'foundry' if index == 0 else 'langchain'}",
              flush=True)
        if not reuse_infrastructure:
            cli.run(
                "deployment", "sub", "create", "--subscription", sid, "--location", region,
                "--name", f"seagent-lab-{lab_id}-{index + 1}",
                "--template-file", str(root / "infra" / "main.bicep"),
                "--parameters", *deployment_parameters(result, index),
            )
    with DefaultAzureCredential(
        exclude_environment_credential=True, exclude_workload_identity_credential=True,
        exclude_managed_identity_credential=True, exclude_shared_token_cache_credential=True,
        exclude_visual_studio_code_credential=True, exclude_developer_cli_credential=True,
        exclude_powershell_credential=True, exclude_broker_credential=True,
    ) as credential:
        arm = AdminARM(credential, [group["id"] for group in groups], create_missing=not reuse_infrastructure)
        first = groups[0]
        base = first["id"]
        account_id = base + "/providers/Microsoft.CognitiveServices/accounts/" + result["account_name"]
        account = arm.ensure(account_id, "2025-06-01", {
            "location": region, "kind": "AIServices", "sku": {"name": "S0"},
            "identity": {"type": "SystemAssigned"}, "tags": tags,
            "properties": {"customSubDomainName": result["account_name"],
                           "allowProjectManagement": True, "disableLocalAuth": True,
                           "publicNetworkAccess": "Enabled"},
        }, lab_id)
        project_id = account_id + "/projects/" + result["project_name"]
        project = arm.ensure(project_id, "2025-06-01", {
            "location": region, "identity": {"type": "SystemAssigned"}, "tags": tags,
            "properties": {"displayName": "Governance sample", "description": "Synthetic governance validation"},
        }, lab_id)
        arm.ensure(account_id + "/deployments/" + result["deployment_name"], "2024-10-01", {
            "sku": {"name": result["sku"], "capacity": result["capacity"]},
            "properties": {"model": {"format": "OpenAI", "name": result["model"],
                                     "version": result["model_version"]}},
        }, lab_id, child=True)
        endpoints = project.get("properties", {}).get("endpoints") or {}
        project_endpoint = next((
            value for value in endpoints.values() if isinstance(value, str) and "/api/projects/" in value
        ), None)
        if not project_endpoint:
            raise RuntimeError("생성된 Foundry 프로젝트 응답에 데이터 endpoint가 없습니다.")
        account_endpoints = account.get("properties", {}).get("endpoints") or {}
        model_endpoint = next((
            value for key, value in account_endpoints.items()
            if isinstance(value, str) and ("openai" in key.lower() or ".openai.azure.com" in value)
        ), None)
        if not model_endpoint:
            raise RuntimeError("생성된 Foundry 계정 응답에 OpenAI endpoint가 없습니다.")
        if urlparse(model_endpoint).scheme != "https":
            raise RuntimeError("모델 endpoint가 HTTPS가 아닙니다.")
        raw_token = credential.get_token(ARM + "/.default").token
        segment = raw_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
        creator_type = "ServicePrincipal" if current["user"]["type"] == "servicePrincipal" else "User"
        ensure_assignment(cli, claims["oid"], creator_type, account_id, FOUNDRY_USER)
        project_principal = (project.get("identity") or {}).get("principalId")
        if project_principal:
            ensure_assignment(cli, project_principal, "ServicePrincipal", account_id, FOUNDRY_USER)
        spec = role_spec(setup["subscription_ids"])
        roles = cli.run("role", "definition", "list", "--name", spec["Name"], "--subscription", first["subscription_id"])
        if not roles:
            cli.run("role", "definition", "create", "--role-definition", json.dumps(spec),
                    "--subscription", first["subscription_id"])
            roles = cli.run("role", "definition", "list", "--name", spec["Name"],
                            "--subscription", first["subscription_id"])
        if len(roles) != 1:
            raise RuntimeError("Foundry 진단 읽기 역할이 유일하지 않습니다.")
        verify_custom_role(roles[0], spec)
        ensure_assignment(cli, setup["principal_id"], "ServicePrincipal", project_id, roles[0]["name"])
        agent_name = "governance-foundry-sample"
        for attempt in range(8):
            try:
                with AIProjectClient(endpoint=project_endpoint, credential=credential, allow_preview=True) as client:
                    try:
                        agent = client.agents.get(agent_name=agent_name)
                        agent_id = agent.id
                        latest = next(iter(client.agents.list_versions(agent_name=agent_name)), None)
                        if latest is None:
                            raise RuntimeError("샘플 Agent에 읽을 수 있는 버전이 없습니다.")
                        agent_version = latest.version
                    except ResourceNotFoundError:
                        version = client.agents.create_version(
                            agent_name=agent_name,
                            definition=PromptAgentDefinition(
                                model=result["deployment_name"],
                                instructions="Respond briefly to synthetic governance validation only.",
                            ),
                            metadata=tags,
                        )
                        agent_id = client.agents.get(agent_name=agent_name).id
                        agent_version = version.version
                    client.agents.update_details(
                        agent_name=agent_name,
                        agent_endpoint=AgentEndpointConfig(
                            version_selector=VersionSelector(version_selection_rules=[
                                FixedRatioVersionSelectionRule(
                                    agent_version=agent_version, traffic_percentage=100,
                                ),
                            ]),
                            protocol_configuration=ProtocolConfiguration(responses=ResponsesProtocolConfiguration()),
                        ),
                    )
                    with client.get_openai_client(agent_name=agent_name) as agent_client:
                        response = agent_client.responses.create(
                            input="Reply READY. This is a synthetic governance validation.",
                            max_output_tokens=32,
                        )
                        if response.status != "completed" or not response.output_text:
                            raise RuntimeError("Foundry 샘플 Agent의 실제 합성 응답 완료를 확인하지 못했습니다.")
                        foundry_smoke = {
                            "status": response.status, "has_output": True,
                            "usage": response.usage.model_dump() if response.usage else None,
                            "identity": "administrator sample publisher; not diagnostic evidence",
                        }
                break
            except (HttpResponseError, APIStatusError) as exc:
                if exc.status_code in (403, 404, 429, 500, 502, 503, 504) and attempt < 7:
                    time.sleep(15)
                    continue
                raise RuntimeError(
                    f"Foundry 샘플 Agent 생성/조회 실패: HTTP {exc.status_code}; 원문 비출력"
                ) from exc
        workspace_id = base + "/providers/Microsoft.OperationalInsights/workspaces/seagent-observability"
        workspace = arm.ensure(workspace_id, "2022-10-01", {
            "location": region, "tags": {**tags, "agent-type": "shared-observability"},
            "properties": {"sku": {"name": "PerGB2018"}, "retentionInDays": result["retention_days"],
                           "workspaceCapping": {"dailyQuotaGb": 1}},
        }, lab_id)
        result.update({
            "account_id": account_id, "project_id": project_id, "project_endpoint": project_endpoint,
            "agent_id": agent_id, "foundry_smoke": foundry_smoke,
            "workspace_id": workspace_id,
            "workspace_customer_id": workspace["properties"]["customerId"],
            "hosts": [],
        })
        partial_path = root / "output" / "lab.partial.json"
        partial_path.write_text(json.dumps(redact(result), ensure_ascii=False, indent=2), encoding="utf-8")
        hosts = []
        archive = build_linux_package(root)
        for group, name in reversed(list(zip(groups[1:], result["host_names"], strict=True))):
            sid = group["subscription_id"]
            plan_name = name + "-plan"
            host_tags = {**tags, "agent-type": "langchain", "agent-id": name,
                         "model-resource-id": account_id, "model-deployment": result["deployment_name"]}
            existing_sites = cli.run("webapp", "list", "--resource-group", group["name"], "--subscription", sid)
            if not any(site["name"] == name for site in existing_sites):
                if reuse_infrastructure:
                    raise RuntimeError("재사용할 샘플 웹 앱이 없습니다.")
                cli.run("appservice", "plan", "create", "--name", plan_name, "--resource-group", group["name"],
                        "--subscription", sid, "--location", region, "--sku", "B1", "--is-linux",
                        "--tags", *[f"{key}={value}" for key, value in host_tags.items()])
                site = cli.run(
                    "webapp", "create", "--name", name, "--resource-group", group["name"],
                    "--subscription", sid, "--plan", plan_name, "--runtime", "PYTHON:3.11",
                    "--assign-identity", "[system]", "--startup-file",
                    "gunicorn --bind=0.0.0.0 --timeout 120 --workers 1 app:app",
                    "--tags", *[f"{key}={value}" for key, value in host_tags.items()],
                )
            else:
                site = next(site for site in existing_sites if site["name"] == name)
                if (site.get("tags") or {}).get("seagent-lab") != lab_id:
                    raise RuntimeError("동명 웹 앱의 소유 태그 불일치")
            principal = (site.get("identity") or {}).get("principalId")
            if not principal:
                raise RuntimeError("샘플 웹 앱 Managed Identity가 없습니다.")
            ensure_assignment(cli, principal, "ServicePrincipal", account_id, OPENAI_USER)
            site_id = site["id"]
            public_settings = {
                "SCM_DO_BUILD_DURING_DEPLOYMENT": "false",
                "ENABLE_ORYX_BUILD": "false",
                "PYTHONPATH": "/home/site/wwwroot:/home/site/wwwroot/.python_packages/lib/site-packages",
                "AZURE_OPENAI_ENDPOINT": model_endpoint,
                "AZURE_OPENAI_DEPLOYMENT": result["deployment_name"],
                "SEAGENT_AGENT_ID": name, "SEAGENT_SMOKE_ON_START": "true",
            }
            cli.run(
                "webapp", "config", "appsettings", "set", "--name", name,
                "--resource-group", group["name"], "--subscription", sid,
                "--settings", *[f"{key}={value}" for key, value in public_settings.items()],
            )
            cli.run(
                "webapp", "log", "config", "--name", name, "--resource-group", group["name"],
                "--subscription", sid, "--docker-container-logging", "filesystem",
                "--application-logging", "filesystem", "--level", "information",
            )
            cli.run(
                "webapp", "config", "set", "--name", name, "--resource-group", group["name"],
                "--subscription", sid, "--startup-file",
                "gunicorn --chdir /home/site/wwwroot --bind=0.0.0.0 --timeout 120 --workers 1 app:app",
            )
            arm.request("PUT", site_id + "/providers/Microsoft.Insights/diagnosticSettings/seagent-sample",
                        "2021-05-01-preview", {"properties": {
                            "workspaceId": workspace_id,
                            "logs": [{"category": "AppServiceConsoleLogs", "enabled": True}],
                            "logAnalyticsDestinationType": "Dedicated",
                        }})
            previous = cli.run(
                "webapp", "log", "deployment", "list", "--name", name,
                "--resource-group", group["name"], "--subscription", sid,
            )
            previous_ids = {row["id"] for row in previous}
            deployments = [deploy_zip(site, archive, credential, previous_ids)]
            host = site.get("defaultHostName")
            if not host:
                raise RuntimeError("생성된 웹 앱 응답에 defaultHostName이 없습니다.")
            health = "https://" + host + "/health"
            smoke_state = None
            for attempt in range(30):
                try:
                    response = requests.get(health, timeout=30)
                    try:
                        payload = response.json()
                    except ValueError:
                        print(f"샘플 앱 준비 대기: HTTP {response.status_code}, 아직 JSON health가 아님", flush=True)
                        time.sleep(10)
                        continue
                    if payload.get("smoke_status") == "failed":
                        error_type = str(payload.get("error_type", "unknown"))
                        safe_error = error_type if re.fullmatch(r"[A-Za-z_]{1,100}", error_type) else "unknown"
                        raise RuntimeError(f"LangChain 샘플 smoke 실패: {safe_error}")
                    if response.status_code == 200:
                        if payload.get("smoke_status") == "completed":
                            smoke_state = payload
                            break
                except (requests.Timeout, requests.ConnectionError):
                    if attempt == 29:
                        raise
                time.sleep(10)
            if not smoke_state:
                raise RuntimeError("LangChain sample의 실제 모델 smoke 완료 확인 시간 초과")
            cli.run(
                "webapp", "config", "appsettings", "set", "--name", name,
                "--resource-group", group["name"], "--subscription", sid,
                "--settings", "SEAGENT_SMOKE_ON_START=false",
            )
            hosts.append({
                "id": site_id, "name": name, "health_url": health, "smoke": smoke_state,
                "deployment_id": deployments[0]["id"], "deployment_verified": True,
            })
            result["hosts"] = hosts
            partial_path.write_text(json.dumps(redact(result), ensure_ascii=False, indent=2), encoding="utf-8")
        result.update({
            "account_id": account_id, "project_id": project_id, "project_endpoint": project_endpoint,
            "agent_id": agent_id, "foundry_smoke": foundry_smoke,
            "workspace_id": workspace_id, "workspace_customer_id":
                workspace["properties"]["customerId"], "hosts": hosts,
            "deployed_at": datetime.now(UTC).isoformat(),
            "functional_smoke_complete": len(hosts) == 2,
        })
        arm.session.close()
    return result
