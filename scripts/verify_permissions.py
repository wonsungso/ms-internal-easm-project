"""Read-only preflight. This tool reports access, not maturity or data coverage."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from wasm_agent.azure import (
    MSGRAPH,
    MSGRAPH_SCOPE,
    AccessError,
    Credential,
    ReaderHTTP,
    rejects_broad_permissions,
    trusted_url,
    verify_identity,
)
from wasm_agent.azure import time as time

ARM = "https://management.azure.com"
ARM_SCOPE = ARM + "/.default"
AI_SCOPE = "https://ai.azure.com/.default"
GRAPH_URL = ARM + "/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01"
SE_CODES = ("DS-SY-06", "BI-SY-11", "BI-SY-12", "OE-SY-22", "OT-SY-28", "OT-SY-29")
PROJECT_PATH = re.compile(r"^/api/projects/[^/?#]+$")
RBAC_REFERENCE = """# 읽기 권한 및 접근 확인

- 수집 대상: Microsoft Foundry, Azure 자체 호스팅 Agent, Azure Monitor, 비용·보안 권고.
- 진단은 별도 Reader 계정으로 실행합니다. 관리자 준비와 진단 수집을 분리합니다.
- 기본 읽기 권한 (관리자 setup apply에서 함께 부여)
  - 승인 구독: Reader, Cost Management Reader, Log Analytics Reader, Security Reader.
  - Foundry Agent·평가: 승인 구독의 사용자 지정 읽기 역할.
  - v2 DataActions: agents/read, evaluations/read, assets/read.
  - Entra Agent ID: AgentIdentity.Read.All, AgentIdentityBlueprint.Read.All, Application.Read.All과 관리자 동의.
  - Agent 365 등록부 교차검증: CopilotPackages.Read.All과 관리자 동의·Agent 365 라이선스. 실제 조회 실패는 수집 결과에 별도 기록.
  - 승인 구독 밖 workspace·청구 범위 접근과 제품 기능·라이선스는 별도 확인.
- 최소 권한의 한계
  - agents/read의 서비스 권한 단위에는 대화 읽기도 포함되지만 수집기는 대화 본문을 조회하지 않습니다.
  - assets/read는 프로젝트 asset 메타데이터 읽기를 포함합니다.
  - Foundry User의 키 조회·쓰기 작업을 진단 역할로 사용하지 않습니다.
- 결과 해석
  - OK는 해당 API 접근 성공이며 데이터 완전성·장기 관측·성숙도 보장이 아닙니다.
  - NOT_CHECKED는 대상 없음·프로젝트 미지정으로 미점검이며, 수집 실행을 막지 않습니다.
  - 오류·권한 부족·빈 자료는 각각 원인과 함께 기록합니다.
  - 관리자는 상속·그룹·PIM 권한도 별도로 확인해야 합니다.
"""


@dataclass
class Result:
    subscription_id: str
    se_code: str
    target: str
    status: str
    reason: str | None
    detail: str


def probe(http: ReaderHTTP, sid: str, code: str, target: str, method: str, url: str,
          body: dict[str, Any] | None = None, audience: str = ARM_SCOPE) -> Result:
    try:
        http.request(method, url, audience, body)
        return Result(sid, code, target, "OK", None, "지정 API 읽기 성공; 데이터 범위/완전성은 별도 검증")
    except AccessError as exc:
        status = {
            "permission_denied": "DENIED",
            "feature_unavailable": "FEATURE_UNAVAILABLE",
            "license_missing": "FEATURE_UNAVAILABLE",
        }.get(exc.reason, "ERROR")
        return Result(sid, code, target, status, exc.reason, str(exc))


def check_subscription(
    credential: Credential, sid: str, projects: list[dict[str, str]], profile: str = "agents_v1",
) -> list[Result]:
    http = ReaderHTTP(credential)
    results: list[Result] = []
    scope = f"/subscriptions/{sid}"
    try:
        permissions = http.list_arm(
            ARM + scope + "/providers/Microsoft.Authorization/permissions?api-version=2022-04-01"
        )
        if rejects_broad_permissions(permissions):
            return [Result(sid, code, scope, "DENIED", "permission_denied",
                           "안전 가드: Owner/Contributor 또는 광범위 권한이 탐지됨; 수집 계정으로 전환")
                    for code in SE_CODES]
        resources = http.list_arm(ARM + scope + "/resources?api-version=2021-04-01")
        accounts = [r for r in resources if r.get("type", "").lower() == "microsoft.cognitiveservices/accounts"
                    and r.get("kind", "").lower() in ("aiservices", "openai")]
        for account in accounts:
            rid = account["id"]
            if not rid.lower().startswith(scope.lower() + "/"):
                raise AccessError("error", "구독 밖의 리소스 ID 응답")
            results.append(probe(http, sid, "DS-SY-06", rid, "GET",
                                 ARM + rid + "/deployments?api-version=2024-10-01"))
            results.append(probe(http, sid, "OE-SY-22", rid, "GET",
                                 ARM + rid + "/providers/Microsoft.Insights/diagnosticSettings"
                                 "?api-version=2021-05-01-preview"))
            results.append(probe(http, sid, "OT-SY-28", rid, "GET",
                                 ARM + rid + "/providers/Microsoft.Insights/metrics"
                                 "?api-version=2018-01-01"))
        for resource in resources:
            if resource.get("type", "").lower() == "microsoft.operationalinsights/workspaces":
                results.append(probe(http, sid, "OE-SY-22", resource["id"], "GET",
                                     ARM + resource["id"] + "?api-version=2022-10-01"))
        for project in projects:
            if project["subscription_id"] != sid:
                continue
            endpoint = project["endpoint"].rstrip("/")
            trusted_url(endpoint, AI_SCOPE)
            if not PROJECT_PATH.fullmatch(urlparse(endpoint).path):
                raise ValueError("Foundry endpoint는 /api/projects/<project> 형식이어야 합니다.")
            results.append(probe(http, sid, "FOUNDRY-AGENTS", endpoint, "GET",
                                 endpoint + ("/agents" if profile == "agents_v1" else "/assistants")
                                 + "?api-version=v1&limit=1", audience=AI_SCOPE))
            results.append(probe(http, sid, "BI-SY-11", endpoint, "GET",
                                 endpoint + ("/openai/v1/evals?limit=1" if profile == "agents_v1"
                                             else "/evaluations/runs?api-version=2025-05-15-preview"),
                                 audience=AI_SCOPE))
        results.append(probe(
            http, sid, "BI-SY-12", scope, "POST", GRAPH_URL,
            {"subscriptions": [sid], "query": "securityresources | where type =~ "
             "'microsoft.security/assessments' | project id | limit 1"},
        ))
        results.append(probe(
            http, sid, "BI-SY-12", scope, "GET",
            ARM + scope + "/providers/Microsoft.Security/secureScores?api-version=2020-01-01",
        ))
        results.append(probe(
            http, sid, "DS-SY-06", scope, "GET",
            ARM + scope + "/providers/Microsoft.Authorization/policyAssignments"
            "?api-version=2023-04-01&$filter=atScope()",
        ))
        results.append(probe(
            http, sid, "OT-SY-29", scope, "GET",
            ARM + scope + "/providers/Microsoft.Consumption/budgets?api-version=2023-05-01",
        ))
        now = datetime.now(UTC)
        results.append(probe(
            http, sid, "OT-SY-29", scope, "POST",
            ARM + scope + "/providers/Microsoft.CostManagement/query?api-version=2023-03-01",
            {"type": "Usage", "timeframe": "Custom",
             "timePeriod": {"from": (now - timedelta(days=30)).isoformat(), "to": now.isoformat()},
             "dataset": {"granularity": "None", "aggregation":
                         {"totalCost": {"name": "PreTaxCost", "function": "Sum"}}}},
        ))
        for code in SE_CODES:
            if not any(result.se_code == code for result in results):
                detail = "대상 AI 리소스 없음" if code != "BI-SY-11" else "프로젝트 endpoint 입력 없음; 자동 추측하지 않음"
                results.append(Result(sid, code, scope, "NOT_CHECKED", "not_found", detail))
        return results
    except AccessError as exc:
        status = "DENIED" if exc.reason == "permission_denied" else "ERROR"
        for code in SE_CODES:
            if not any(result.se_code == code for result in results):
                results.append(Result(sid, code, scope, status, exc.reason, str(exc)))
        return results
    finally:
        http.close()


def check_entra(credential: Credential, tenant_id: str) -> list[Result]:
    http = ReaderHTTP(credential)
    try:
        v1 = MSGRAPH + "/v1.0"
        return [
            probe(http, tenant_id, "DS-SY-05", "agentIdentityBlueprint", "GET",
                  v1 + "/applications/microsoft.graph.agentIdentityBlueprint?$top=1", audience=MSGRAPH_SCOPE),
            probe(http, tenant_id, "OE-SY-20", "agentIdentity", "GET",
                  v1 + "/servicePrincipals/microsoft.graph.agentIdentity?$top=1", audience=MSGRAPH_SCOPE),
            probe(http, tenant_id, "OE-SY-21", "servicePrincipals", "GET",
                  v1 + "/servicePrincipals?$top=1&$select=id", audience=MSGRAPH_SCOPE),
        ]
    finally:
        http.close()


def render_rbac(results: list[Result]) -> str:
    lines = [
        RBAC_REFERENCE, "", "## 실제 사전 점검 결과", "",
        f"- 실행 시각(UTC): {datetime.now(UTC).isoformat()}", "",
    ]
    for result in sorted(results, key=lambda row: (row.subscription_id, row.se_code, row.target)):
        for label, value in [
            ("항목", result.se_code), ("구독", result.subscription_id), ("대상", result.target),
            ("접근 상태", result.status), ("사유", result.reason or "접근 확인"),
            ("설명", result.detail),
        ]:
            prefix = "- " if label == "항목" else "  - "
            lines.append(prefix + label + ": " + value.replace("\n", " "))
    return "\n".join(lines) + "\n"


def uuid_arg(value: str) -> str:
    return str(uuid.UUID(value))


def main(argv: list[str] | None = None) -> int:
    logging.getLogger("azure.identity").setLevel(logging.ERROR)
    parser = argparse.ArgumentParser(description="수집 계정 전용: 쓰기 없는 SE 접근 사전 점검")
    parser.add_argument("--tenant-id", required=True, type=uuid_arg)
    parser.add_argument("--expected-principal-id", required=True, type=uuid_arg)
    parser.add_argument("--subscriptions", nargs="+", type=uuid_arg)
    parser.add_argument("--projects-file", type=Path)
    parser.add_argument("--foundry-profile", choices=["agents_v1", "classic_v1"], default="agents_v1")
    parser.add_argument("--rbac-path", type=Path, default=Path(".wasm-agent") / "permissions.md")
    parser.add_argument("--output", type=Path, default=Path(".wasm-agent") / "permissions.json")
    args = parser.parse_args(argv)
    from azure.core.exceptions import ClientAuthenticationError
    from azure.identity import DefaultAzureCredential

    try:
        projects = json.loads(args.projects_file.read_text(encoding="utf-8")) if args.projects_file else []
        if not isinstance(projects, list):
            raise ValueError("projects-file은 프로젝트 객체 배열이어야 합니다.")
        for project in projects:
            project["subscription_id"] = uuid_arg(project["subscription_id"])
            trusted_url(project["endpoint"], AI_SCOPE)
            if not PROJECT_PATH.fullmatch(urlparse(project["endpoint"].rstrip("/")).path):
                raise ValueError("잘못된 Foundry 프로젝트 endpoint")
        with DefaultAzureCredential() as credential:
            verify_identity(credential, args.tenant_id, args.expected_principal_id)
            if args.subscriptions:
                subscriptions = sorted(set(args.subscriptions))
            else:
                http = ReaderHTTP(credential)
                try:
                    accounts = http.list_arm(ARM + "/subscriptions?api-version=2022-12-01")
                finally:
                    http.close()
                subscriptions = [
                    uuid_arg(a["subscriptionId"]) for a in accounts
                    if a.get("tenantId", "").lower() == args.tenant_id
                    and a.get("state") == "Enabled"
                ]
            if not subscriptions:
                raise AccessError("permission_denied", "접근 가능한 활성 구독이 없습니다.")
            if any(p["subscription_id"] not in subscriptions for p in projects):
                raise ValueError("projects-file에 대상 구독 밖 프로젝트가 있습니다.")
            with ThreadPoolExecutor(max_workers=min(4, len(subscriptions))) as executor:
                groups = list(executor.map(
                    lambda sid: check_subscription(credential, sid, projects, args.foundry_profile), subscriptions,
                ))
            entra_results = check_entra(credential, args.tenant_id)
        results = [result for group in groups for result in group] + entra_results
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(
            {"collected_at": datetime.now(UTC).isoformat(), "results": [asdict(r) for r in results]},
            ensure_ascii=False, indent=2,
        ), encoding="utf-8")
        args.rbac_path.parent.mkdir(parents=True, exist_ok=True)
        args.rbac_path.write_text(render_rbac(results), encoding="utf-8")
        for result in results:
            print(f"{result.subscription_id} {result.se_code} {result.status} {result.reason or '-'}")
        failures = sum(result.status not in ("OK", "NOT_CHECKED") for result in results)
        print(
            f"사전 점검: 성공={sum(result.status == 'OK' for result in results)}, "
            f"미점검={sum(result.status == 'NOT_CHECKED' for result in results)}, 실패={failures}"
        )
        return 2 if failures else 0
    except (AccessError, ClientAuthenticationError, ValueError, KeyError, TypeError, OSError) as exc:
        message = str(exc) if isinstance(exc, (AccessError, ValueError)) else type(exc).__name__
        print(f"사전 점검 중단: {message}. 토큰·응답 본문은 출력하지 않았습니다.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
