"""Administrator-only Azure CLI orchestration; never imported by collectors."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROLES = {
    "Reader": "acdd72a7-3385-48ef-bd42-f606fba81ae7",
    "Cost Management Reader": "72fafb9e-0641-4937-9268-a91bfd8191a3",
    "Monitoring Reader": "43d0d8ad-25c7-4714-9337-8ba259a9fe05",
    "Log Analytics Reader": "73c42c96-874c-492b-b04d-ab87d138a893",
    "Security Reader": "39bc4728-0917-49c7-9d2c-d95423bc2eb4",
}
GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"
ENTRA_GRAPH_ROLES = (
    "AgentIdentity.Read.All", "AgentIdentityBlueprint.Read.All", "Application.Read.All",
)
DEFAULT_ROLES = ("Reader", "Cost Management Reader", "Log Analytics Reader", "Security Reader")
PROJECT_SCOPE = re.compile(
    r"^/subscriptions/([0-9a-fA-F-]{36})/resourceGroups/([^/]+)/providers/"
    r"Microsoft\.CognitiveServices/accounts/([^/]+)/projects/([^/]+)$",
    re.IGNORECASE,
)


def guid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("UUID 형식이어야 합니다.") from exc


def cli_prefix() -> list[str]:
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI가 없습니다. 설치 후 다시 실행하세요.")
    path = Path(executable)
    if path.suffix.lower() in (".cmd", ".bat"):
        interpreter = path.parent.parent / "python.exe"
        if not interpreter.is_file():
            raise RuntimeError("Azure CLI Python을 찾지 못했습니다. Azure CLI 설치를 복구하세요.")
        return [str(interpreter), "-Im", "azure.cli"]
    return [executable]


class AzureCLI:
    def __init__(self) -> None:
        self.prefix = cli_prefix()

    def run(self, *args: str) -> Any:
        environment = os.environ.copy()
        environment.update({
            "AZURE_CORE_COLLECT_TELEMETRY": "false",
            "AZURE_CORE_ONLY_SHOW_ERRORS": "true",
            "AZURE_LOGGING_ENABLE_LOG_FILE": "false",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        })
        result = subprocess.run(
            [*self.prefix, *args, "--only-show-errors", "--output", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
        )
        if result.returncode:
            # CLI diagnostics can contain request bodies; do not copy them into logs.
            operation = " ".join(args[:3])
            raise RuntimeError(
                f"Azure CLI 작업 실패: {operation} (exit={result.returncode}). "
                "관리자가 로그인·디렉터리 접근·역할 할당 권한을 확인하세요. 응답 본문은 출력하지 않았습니다."
            )
        return json.loads(result.stdout) if result.stdout.strip() else None


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="관리자 전용: 전체 진단에 필요한 읽기 권한 일괄 설정")
    result.add_argument("--config-file", type=Path)
    result.add_argument("--result-file", type=Path)
    result.add_argument("--tenant-id", type=guid)
    result.add_argument("--subscriptions", nargs="+", type=guid)
    result.add_argument("--account-type", choices=["user", "service-principal"])
    result.add_argument("--account-name")
    result.add_argument("--principal-id", type=guid)
    result.add_argument("--client-id", type=guid)
    result.add_argument("--certificate-path", type=Path)
    result.add_argument("--projects-file", type=Path)
    result.add_argument("--login-resource", choices=["arm", "graph"], default="arm")
    result.add_argument("--create-principal", action="store_true")
    result.add_argument("--cost-reader", action="store_true")
    result.add_argument("--monitoring-reader", action="store_true")
    result.add_argument("--log-analytics-reader", action="store_true")
    result.add_argument("--security-reader", action="store_true")
    result.add_argument("--foundry-project-scopes", nargs="+", default=[])
    result.add_argument("--create-foundry-read-role", action="store_true")
    result.add_argument("--entra-reader", action="store_true", help="진단 SP에 Entra Agent ID용 Graph 읽기 권한 부여")
    result.add_argument("--foundry-read-role-id", type=guid)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", "--what-if", action="store_true")
    mode.add_argument("--login", action="store_true")
    mode.add_argument("--verify", action="store_true")
    return result


def load_config(args: argparse.Namespace) -> None:
    config = {}
    if args.config_file:
        config = json.loads(args.config_file.read_text(encoding="utf-8-sig"))
        if not isinstance(config, dict):
            raise ValueError("config-file은 비밀값이 없는 JSON 객체여야 합니다.")
    for attribute, key in [
        ("tenant_id", "tenant_id"), ("subscriptions", "subscription_ids"),
        ("account_type", "account_type"), ("account_name", "account_name"),
        ("principal_id", "principal_id"), ("client_id", "client_id"),
    ]:
        if getattr(args, attribute) is None:
            setattr(args, attribute, config.get(key))
    for attribute in ("tenant_id", "principal_id", "client_id"):
        value = getattr(args, attribute)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"{attribute}는 UUID 문자열이어야 합니다.")
            setattr(args, attribute, guid(value))
    if not isinstance(args.subscriptions, list) or not args.subscriptions:
        raise ValueError("subscription_ids 배열 또는 --subscriptions를 입력하세요.")
    if not all(isinstance(sid, str) for sid in args.subscriptions):
        raise ValueError("subscription_ids는 UUID 문자열 배열이어야 합니다.")
    args.subscriptions = [guid(sid) for sid in args.subscriptions]
    if not args.tenant_id or args.account_type not in ("user", "service-principal"):
        raise ValueError("tenant_id 및 account_type(user | service-principal)을 입력하세요.")
    if not isinstance(args.account_name, str):
        raise ValueError("account_name을 입력하세요.")


def validate(args: argparse.Namespace) -> None:
    if len(set(args.subscriptions)) != len(args.subscriptions):
        raise ValueError("중복 구독 ID를 제거하세요.")
    if not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,128}", args.account_name):
        raise ValueError("계정 이름/UPN은 영문·숫자·_.@+-만 허용합니다.")
    if args.account_type != "service-principal":
        raise ValueError("전체 진단은 service-principal 모드의 진단 앱을 사용하세요. 사용자 계정으로 대체하지 않습니다.")
    if args.create_foundry_read_role and args.foundry_read_role_id:
        raise ValueError("역할 생성과 기존 역할 지정 중 하나만 선택하세요.")
    for scope in args.foundry_project_scopes:
        match = PROJECT_SCOPE.fullmatch(scope)
        if not match or guid(match.group(1)) not in args.subscriptions:
            raise ValueError("Foundry scope는 대상 구독 안의 CognitiveServices 프로젝트여야 합니다.")
        if any(c in scope for c in ('"', "'", "\n", "\r", "\\", "?", "#", "%")):
            raise ValueError("Foundry scope에 허용되지 않은 문자가 있습니다.")


def selected_roles(args: argparse.Namespace) -> list[str]:
    return [*DEFAULT_ROLES, *(["Monitoring Reader"] if args.monitoring_reader else [])]


def role_spec(subscriptions: list[str]) -> dict[str, Any]:
    path = Path(__file__).with_name("foundry-reader.json")
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["AssignableScopes"] = [f"/subscriptions/{sid}" for sid in subscriptions]
    return spec


def verify_custom_role(role: dict[str, Any], expected: dict[str, Any]) -> None:
    permissions = role.get("permissions", [])
    if len(permissions) != 1:
        raise ValueError("Foundry 역할에는 단일 명시적 권한 블록만 허용합니다.")
    permission = permissions[0]
    for key in ("actions", "notActions", "notDataActions"):
        if permission.get(key):
            raise ValueError(f"Foundry 읽기 역할의 {key}는 비어 있어야 합니다.")
    if set(permission.get("dataActions", [])) != set(expected["DataActions"]):
        raise ValueError("Foundry 읽기 역할의 DataActions가 승인된 세 read 작업과 다릅니다.")
    allowed_scopes = {s.lower() for s in expected["AssignableScopes"]}
    actual_scopes = {s.lower() for s in role.get("assignableScopes", [])}
    if actual_scopes != allowed_scopes:
        raise ValueError("Foundry 역할의 AssignableScopes가 대상 구독 목록과 다릅니다.")
    if role.get("roleType") != "CustomRole":
        raise ValueError("Foundry User 등 기본 제공 개발자 역할은 허용하지 않습니다.")


def resolve_principal(cli: AzureCLI, args: argparse.Namespace) -> dict[str, Any]:
    if args.account_type == "user":
        identity = cli.run("ad", "user", "show", "--id", args.principal_id or args.account_name)
        if identity.get("userPrincipalName", "").lower() != args.account_name.lower():
            raise ValueError("지정한 사용자 object ID와 UPN이 일치하지 않습니다.")
        return identity
    if args.principal_id:
        identity = cli.run("ad", "sp", "show", "--id", args.principal_id)
        if identity.get("displayName") != args.account_name:
            raise ValueError("지정한 SP object ID와 계정 이름이 일치하지 않습니다.")
        return identity
    identities = cli.run("ad", "sp", "list", "--display-name", args.account_name, "--all")
    identities = [i for i in identities if i.get("displayName") == args.account_name]
    if len(identities) > 1:
        raise ValueError("동일 이름의 SP가 여러 개입니다. --principal-id로 명시하세요.")
    if identities:
        return identities[0]
    if not args.create_principal:
        raise ValueError("기존 SP가 없습니다. 관리자 승인 후 --create-principal을 사용하세요.")
    apps = cli.run("ad", "app", "list", "--display-name", args.account_name, "--all")
    apps = [app for app in apps if app.get("displayName") == args.account_name]
    if len(apps) > 1:
        raise ValueError("동일 이름의 앱이 여러 개입니다. 고객 관리자가 앱을 확정하세요.")
    app = apps[0] if apps else cli.run("ad", "app", "create", "--display-name", args.account_name)
    return cli.run("ad", "sp", "create", "--id", app["appId"])


def assignment_exists(
    cli: AzureCLI, principal: str, scope: str, role_id: str
) -> bool:
    assignments = cli.run(
        "role", "assignment", "list", "--scope", scope,
        "--subscription", scope.split("/")[2],
    )
    return any(
        a.get("principalId", "").lower() == principal.lower()
        and a.get("scope", "").lower() == scope.lower()
        and a.get("roleDefinitionId", "").split("/")[-1].lower() == role_id.lower()
        for a in assignments
    )


def ensure_assignment(
    cli: AzureCLI, principal: str, principal_type: str, scope: str, role_id: str
) -> None:
    if assignment_exists(cli, principal, scope, role_id):
        return
    name = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{principal}/{scope}/{role_id}".lower()))
    cli.run(
        "role", "assignment", "create", "--assignee-object-id", principal,
        "--assignee-principal-type", principal_type, "--scope", scope,
        "--role", role_id, "--name", name, "--subscription", scope.split("/")[2],
    )
    for attempt in range(5):
        if assignment_exists(cli, principal, scope, role_id):
            return
        if attempt < 4:
            time.sleep(2**attempt)
    raise RuntimeError("역할 할당을 재조회했으나 확인되지 않았습니다. 관리자에게 전파 지연을 확인하세요.")


def ensure_graph_roles(cli: AzureCLI, principal: str, roles: tuple[str, ...] = ENTRA_GRAPH_ROLES) -> list[str]:
    graph = cli.run("ad", "sp", "show", "--id", GRAPH_APP_ID)
    available = {
        role["value"]: role["id"] for role in graph.get("appRoles", [])
        if "Application" in role.get("allowedMemberTypes", [])
    }
    missing = [role for role in roles if role not in available]
    if missing:
        raise ValueError("Microsoft Graph 애플리케이션 권한을 찾지 못했습니다: " + ", ".join(missing))
    url = f"https://graph.microsoft.com/v1.0/servicePrincipals/{principal}/appRoleAssignments"
    for role in roles:
        existing = (cli.run("rest", "--method", "GET", "--url", url) or {}).get("value", [])
        if any(
            item.get("resourceId") == graph["id"] and item.get("appRoleId") == available[role] for item in existing
        ):
            continue
        cli.run(
            "rest", "--method", "POST", "--url", url, "--headers", "Content-Type=application/json",
            "--body", json.dumps({"principalId": principal, "resourceId": graph["id"], "appRoleId": available[role]}),
        )
    final = (cli.run("rest", "--method", "GET", "--url", url) or {}).get("value", [])
    granted = {item.get("appRoleId") for item in final if item.get("resourceId") == graph["id"]}
    if any(available[role] not in granted for role in roles):
        raise RuntimeError("Graph 권한 부여를 재조회했으나 확인되지 않았습니다. 관리자에게 전파 지연을 확인하세요.")
    return list(roles)


def execute(args: argparse.Namespace, cli: AzureCLI) -> None:
    current = cli.run("account", "show")
    if current.get("tenantId", "").lower() != args.tenant_id:
        raise ValueError("현재 관리자 로그인 테넌트가 설정과 다릅니다. login부터 실행하세요.")
    for sid in args.subscriptions:
        account = cli.run("account", "show", "--subscription", sid)
        if account.get("tenantId", "").lower() != args.tenant_id:
            raise ValueError("대상 구독의 테넌트가 입력과 다릅니다. 쓰기 작업을 중단합니다.")
    identity = resolve_principal(cli, args)
    if args.client_id and identity.get("appId", "").lower() != args.client_id:
        raise ValueError("실제 서비스 주체와 설정의 client_id가 다릅니다.")
    principal = identity["id"]
    principal_type = "User" if args.account_type == "user" else "ServicePrincipal"
    roles = selected_roles(args)
    assignments = [
        (f"/subscriptions/{sid}", name, ROLES[name])
        for sid in args.subscriptions for name in roles
    ]
    scopes = args.foundry_project_scopes or [f"/subscriptions/{sid}" for sid in args.subscriptions]
    if scopes:
        spec = role_spec(args.subscriptions)
        role_name = args.foundry_read_role_id or spec["Name"]
        found = cli.run("role", "definition", "list", "--name", role_name, "--subscription", args.subscriptions[0])
        if not found and not args.foundry_read_role_id:
            cli.run(
                "role", "definition", "create", "--role-definition",
                json.dumps(spec), "--subscription", args.subscriptions[0],
            )
            found = cli.run(
                "role", "definition", "list", "--name", spec["Name"],
                "--subscription", args.subscriptions[0],
            )
        if len(found) != 1:
            raise ValueError("Foundry 사용자 지정 역할이 유일하게 확인되지 않았습니다.")
        verify_custom_role(found[0], spec)
        role_id = found[0]["name"]
        assignments.extend((scope, spec["Name"], role_id) for scope in scopes)
    print("| 주체 object ID | scope | 역할 | 검증 |")
    print("| --- | --- | --- | --- |")
    for scope, name, role_id in assignments:
        ensure_assignment(cli, principal, principal_type, scope, role_id)
        print(f"| {principal} | {scope} | {name} | 확인됨 |")
    graph_roles = ensure_graph_roles(cli, principal)
    for role in graph_roles:
        print(f"| {principal} | Microsoft Graph (application) | {role} | 확인됨 |")
    if args.account_type == "service-principal":
        print(
            f"SP client ID: {identity.get('appId')}. 시크릿은 생성하지 않았습니다. "
            "고객 관리자가 인증서 또는 워크로드 ID 연합을 구성하세요. "
            "인증서 개인키는 Key Vault 등 승인 저장소에서만 관리하세요."
        )
    print("주의: 위 표는 이 스크립트가 요청한 직접 할당만 검증하며, 상속·그룹·PIM 권한이 없음을 증명하지 않습니다.")
    if args.result_file:
        result = {
            "verified_at": datetime.now(UTC).isoformat(),
            "tenant_id": args.tenant_id,
            "account_type": args.account_type,
            "account_name": args.account_name,
            "principal_id": principal,
            "client_id": identity.get("appId"),
            "subscription_ids": args.subscriptions,
            "verified_assignments": [
                {"scope": scope, "role": name, "role_id": role_id}
                for scope, name, role_id in assignments
            ],
            "verified_graph_roles": graph_roles,
            "verification_identity": "administrator",
            "verification_scope": "requested direct role assignments only",
            "secret_created_by_setup": False,
            "certificate_created_by_setup": False,
            "diagnostic_preflight": "not_run",
        }
        args.result_file.parent.mkdir(parents=True, exist_ok=True)
        args.result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"비밀 없는 셋업 결과 저장: {args.result_file}")


def verify_environment(args: argparse.Namespace) -> dict[str, str]:
    environment = os.environ.copy()
    if args.account_type != "service-principal":
        if args.certificate_path:
            raise ValueError("--certificate-path는 서비스 주체에만 사용할 수 있습니다.")
        return environment
    if not args.client_id:
        raise ValueError("SP client_id가 없습니다. 먼저 apply로 셋업 결과를 저장하세요.")
    if environment.get("AZURE_CLIENT_SECRET"):
        raise ValueError("이 터미널의 AZURE_CLIENT_SECRET을 제거한 뒤 인증서/연합 인증을 사용하세요.")
    for key, value in (("AZURE_TENANT_ID", args.tenant_id), ("AZURE_CLIENT_ID", args.client_id)):
        if environment.get(key) and environment[key].lower() != value:
            raise ValueError(f"{key}가 설정 파일과 다릅니다. 별도 진단 터미널을 사용하세요.")
        environment[key] = value
    if args.certificate_path:
        environment["AZURE_CLIENT_CERTIFICATE_PATH"] = str(args.certificate_path.resolve())
    certificate = environment.get("AZURE_CLIENT_CERTIFICATE_PATH")
    federation = environment.get("AZURE_FEDERATED_TOKEN_FILE")
    if bool(certificate) == bool(federation):
        raise ValueError(
            "SP 인증이 필요합니다. --certificate-path로 기존 개인키 포함 인증서 경로를 지정하거나 "
            "AZURE_FEDERATED_TOKEN_FILE을 설정하세요. 두 방식은 동시에 사용하지 않습니다. "
            "인증서/연합 설정은 고객이 먼저 완료해야 하며 관리자 CLI로 대체하지 않습니다."
        )
    if not Path(certificate or federation).is_file():
        raise ValueError("지정된 인증서/연합 토큰 파일이 없습니다. 파일 내용은 출력하지 않았습니다.")
    return environment


def run_verify(args: argparse.Namespace) -> int:
    if not args.principal_id:
        raise ValueError("principal_id가 없습니다. 먼저 apply로 셋업 결과를 저장하세요.")
    environment = verify_environment(args)
    root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable, str(root / "scripts" / "verify_permissions.py"),
        "--tenant-id", args.tenant_id, "--expected-principal-id", args.principal_id,
        "--subscriptions", *args.subscriptions,
    ]
    if args.projects_file:
        command.extend(["--projects-file", str(args.projects_file.resolve())])
    return subprocess.run(command, env=environment, cwd=root, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        load_config(args)
        validate(args)
        if (args.login or args.verify) and (
            args.create_principal or any((
                args.cost_reader, args.monitoring_reader, args.log_analytics_reader, args.security_reader,
            ))
            or args.foundry_project_scopes or args.create_foundry_read_role
            or args.foundry_read_role_id or args.entra_reader
        ):
            raise ValueError("역할/계정 생성 옵션은 plan 또는 apply에서만 사용하세요.")
        if (args.certificate_path or args.projects_file) and not args.verify:
            raise ValueError("--certificate-path, --projects-file은 verify에서만 사용하세요.")
        if args.login:
            environment = os.environ.copy()
            environment["AZURE_CORE_LOGIN_EXPERIENCE_V2"] = "off"
            command = [
                *cli_prefix(), "login", "--tenant", args.tenant_id,
                "--use-device-code", "--output", "none",
            ]
            if args.login_resource == "graph":
                command.extend(["--scope", "https://graph.microsoft.com/.default"])
            return subprocess.run(command, env=environment, check=False).returncode
        if args.verify:
            return run_verify(args)
        if not args.apply:
            print("DRY-RUN: Azure CLI/인증/쓰기 API를 호출하지 않습니다.")
            print(json.dumps({
                "tenant_id": args.tenant_id,
                "account_type": args.account_type,
                "account_name": args.account_name,
                "create_principal": args.create_principal,
                "subscription_roles": selected_roles(args),
                "subscriptions": args.subscriptions,
                "foundry_project_scopes": args.foundry_project_scopes or [
                    f"/subscriptions/{sid}" for sid in args.subscriptions
                ],
                "foundry_custom_role": role_spec(args.subscriptions),
                "graph_application_roles": list(ENTRA_GRAPH_ROLES),
            }, ensure_ascii=False, indent=2))
            return 0
        execute(args, AzureCLI())
        return 0
    except (ValueError, RuntimeError, OSError, argparse.ArgumentTypeError) as exc:
        print(f"셋업 중단: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
