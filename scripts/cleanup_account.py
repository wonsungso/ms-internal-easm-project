"""Administrator-only cleanup of one explicitly recorded diagnostic identity."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

if __package__:
    from .setup_account import AzureCLI, role_spec, verify_custom_role
else:
    from setup_account import AzureCLI, role_spec, verify_custom_role


def load_target(path: Path) -> dict[str, Any]:
    target = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(target, dict):
        raise ValueError("setup.json은 객체여야 합니다.")
    for key in ("tenant_id", "client_id", "principal_id"):
        target[key] = str(uuid.UUID(target[key]))
    if target.get("account_type") != "service-principal" or not re.fullmatch(
        r"wasmagent-diagnostic(?:[-_][A-Za-z0-9_-]+)?", target.get("account_name", ""),
    ):
        raise ValueError("진단 전용 wasmagent-diagnostic 앱만 정리할 수 있습니다. 데모 ID는 삭제하지 않습니다.")
    subscriptions = target.get("subscription_ids")
    if not isinstance(subscriptions, list) or not subscriptions:
        raise ValueError("승인 subscription_ids가 필요합니다.")
    target["subscription_ids"] = list(dict.fromkeys(str(uuid.UUID(sid)) for sid in subscriptions))
    return target


def identities(cli: AzureCLI, target: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    rows = []
    for kind in ("app", "sp"):
        found = cli.run("ad", kind, "list", "--all", "--filter", f"appId eq '{target['client_id']}'")
        if not isinstance(found, list) or len(found) > 1:
            raise ValueError("진단 앱·SP 조회가 유일하게 확인되지 않았습니다.")
        for item in found:
            if (
                item.get("appId", "").lower() != target["client_id"]
                or item.get("displayName") != target["account_name"]
            ):
                raise ValueError("삭제 대상 Client ID·앱 이름이 setup.json과 다릅니다.")
            if kind == "sp" and (
                item.get("id", "").lower() != target["principal_id"]
                or item.get("servicePrincipalType") != "Application"
            ):
                raise ValueError("삭제 대상 SP 개체 ID·유형이 다릅니다. 관리 ID는 삭제하지 않습니다.")
            if kind == "app" and item.get("signInAudience") != "AzureADMyOrg":
                raise ValueError("진단용 단일 테넌트 앱만 삭제할 수 있습니다.")
            uuid.UUID(item["id"])
        rows.append(found)
    return rows[0], rows[1]


def assignments(cli: AzureCLI, subscription: str) -> list[dict]:
    rows = cli.run("role", "assignment", "list", "--all", "--subscription", subscription)
    if not isinstance(rows, list):
        raise ValueError("역할 할당 목록 형식 불일치")
    return rows


def target_assignments(cli: AzureCLI, target: dict[str, Any]) -> list[tuple[str, str]]:
    found = []
    for sid in target["subscription_ids"]:
        for row in assignments(cli, sid):
            if str(row.get("principalId", "")).lower() != target["principal_id"]:
                continue
            scope = f"/subscriptions/{sid}".lower()
            identifier = row.get("id", "")
            if not isinstance(identifier, str) or not identifier.lower().startswith(scope + "/"):
                raise ValueError("승인 구독 밖의 역할 할당 ID는 삭제하지 않습니다.")
            found.append((sid, identifier))
    return found


def eligible_role_usage(cli: AzureCLI, sid: str, role_id: str) -> bool:
    prefix = f"/subscriptions/{sid}/"
    for resource in ("roleEligibilityScheduleInstances", "roleEligibilitySchedules"):
        url = ("https://management.azure.com" + prefix
               + f"providers/Microsoft.Authorization/{resource}?api-version=2020-10-01")
        seen = set()
        while url:
            parsed = urlparse(url)
            if (
                parsed.scheme != "https" or parsed.netloc.lower() != "management.azure.com"
                or not parsed.path.lower().startswith(prefix.lower()) or parsed.fragment or url in seen
            ):
                raise ValueError("PIM 페이지 경로가 승인 범위 밖이거나 반복됩니다.")
            seen.add(url)
            payload = cli.run("rest", "--method", "GET", "--url", url)
            if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
                raise ValueError("PIM 적격 할당 목록 형식 불일치")
            if any(
                str((row.get("properties") or {}).get("roleDefinitionId", "")).split("/")[-1].lower() == role_id
                for row in payload["value"]
            ):
                return True
            url = payload.get("nextLink")
            if url is not None and not isinstance(url, str):
                raise ValueError("PIM 다음 페이지 형식 불일치")
    return False


def unused_custom_role(
    cli: AzureCLI, target: dict[str, Any],
) -> tuple[dict | None, str]:
    sid = target["subscription_ids"][0]
    spec = role_spec(target["subscription_ids"])
    rows = cli.run("role", "definition", "list", "--name", spec["Name"], "--subscription", sid)
    if not isinstance(rows, list) or len(rows) > 1:
        raise ValueError("사용자 지정 역할이 유일하게 확인되지 않았습니다.")
    if not rows:
        return None, "already_absent"
    role = rows[0]
    verify_custom_role(role, spec)
    role_id = str(uuid.UUID(role["name"]))
    if role.get("roleName") != spec["Name"]:
        raise ValueError("진단용 사용자 지정 역할 이름 불일치")
    for subscription in target["subscription_ids"]:
        if any(
            str(row.get("roleDefinitionId", "")).split("/")[-1].lower() == role_id
            for row in assignments(cli, subscription)
            if str(row.get("principalId", "")).lower() != target["principal_id"]
        ):
            return role, "retained_in_use"
        if eligible_role_usage(cli, subscription, role_id):
            return role, "retained_eligible"
    return role, "unused"


def execute(cli: AzureCLI, target: dict[str, Any], apply: bool) -> dict[str, Any]:
    if cli.run("account", "show").get("tenantId", "").lower() != target["tenant_id"]:
        raise ValueError("로그인 테넌트가 setup.json과 다릅니다.")
    for sid in target["subscription_ids"]:
        if cli.run("account", "show", "--subscription", sid).get("tenantId", "").lower() != target["tenant_id"]:
            raise ValueError("승인 구독의 테넌트가 다릅니다.")
    apps, sps = identities(cli, target)
    selected = target_assignments(cli, target)
    role, role_status = unused_custom_role(cli, target)
    summary = {
        "mode": "apply" if apply else "plan",
        "client_id": target["client_id"], "principal_id": target["principal_id"],
        "role_assignments": len(selected), "applications": len(apps), "service_principals": len(sps),
        "custom_role": "delete_after_target_assignments" if role_status == "unused" and selected else role_status,
        "permanent_delete": False, "demo_resources_modified": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not apply:
        print("PLAN: Azure·Entra 변경 없음. cleanup-apply에서만 삭제합니다.")
        return summary
    for sid, identifier in selected:
        cli.run("role", "assignment", "delete", "--ids", identifier, "--subscription", sid)
    if target_assignments(cli, target):
        raise RuntimeError("진단 SP 역할 할당이 남아 있어 앱 삭제를 중단합니다.")
    if apps:
        cli.run("ad", "app", "delete", "--id", apps[0]["id"])
    elif sps:
        cli.run("ad", "sp", "delete", "--id", target["principal_id"])
    for attempt in range(6):
        remaining_apps, remaining_sps = identities(cli, target)
        if not remaining_apps and not remaining_sps:
            break
        if attempt == 5:
            raise RuntimeError("진단 앱·SP 삭제 완료를 재조회로 확인하지 못했습니다.")
        time.sleep(2)
    if target_assignments(cli, target):
        raise RuntimeError("진단 SP의 잔여 역할 할당이 확인되었습니다.")
    role, role_status = unused_custom_role(cli, target)
    if role is not None and role_status == "unused":
        sid = target["subscription_ids"][0]
        cli.run("role", "definition", "delete", "--name", role["name"], "--subscription", sid)
        if cli.run("role", "definition", "list", "--name", role["name"], "--subscription", sid):
            raise RuntimeError("사용자 지정 역할 삭제 완료를 확인하지 못했습니다.")
        role_status = "deleted"
    summary.update({
        "verified_at": datetime.now(UTC).isoformat(), "role_assignments": 0,
        "applications": 0, "service_principals": 0, "custom_role": role_status,
    })
    if role_status.startswith("retained"):
        print("사용자 지정 역할은 다른 활성·적격 할당이 있어 보존했습니다.")
    print("정리 확인: 진단 앱·SP·해당 역할 할당 없음. 영구 삭제·파일 폐기·데모 변경은 수행하지 않았습니다.")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="진단 전용 앱·SP·미사용 역할 정리 - 기본값 조회만")
    parser.add_argument("--config-file", type=Path, required=True)
    parser.add_argument("--result-file", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.result_file and args.result_file.resolve() == args.config_file.resolve():
            raise ValueError("정리 결과로 원본 setup.json을 덮어쓸 수 없습니다.")
        target = load_target(args.config_file)
        result = execute(AzureCLI(), target, args.apply)
        if args.apply and args.result_file:
            args.result_file.parent.mkdir(parents=True, exist_ok=True)
            args.result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
        print(f"정리 중단: {exc}. 완료로 처리하지 않았습니다.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
