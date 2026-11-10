"""Export administrator-visible Power Platform environments without changing settings."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential

from wasm_agent.azure import redact
from wasm_agent.collect_admin_evidence import ENVIRONMENTS_URL
from wasm_agent.models import AdminEnvironment, AdminEvidenceExport, AdminReadResult

SCOPE = "https://api.powerplatform.com/.default"


def export_environments(tenant: str) -> AdminEvidenceExport:
    tenant = str(uuid.UUID(tenant))
    verified = False
    environments = []
    now = datetime.now(UTC)
    reason = None
    detail = "공식 API 2024-10-01의 관리자 접근 가능 환경. 테넌트 전체 권한·Maker·관리형 운영 준수 증명 아님"
    try:
        with AzureCliCredential(tenant_id=tenant) as credential, requests.Session() as session:
            token = credential.get_token(SCOPE).token
            part = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            if not isinstance(claims, dict) or (
                claims.get("tid", "").lower() != tenant or not claims.get("scp") or claims.get("idtyp") == "app"
            ):
                raise ValueError("별도 관리자 사용자 로그인과 대상 테넌트 확인이 필요합니다.")
            verified = True
            session.headers["Authorization"] = "Bearer " + token
            url = ENVIRONMENTS_URL
            seen = set()
            identifiers = set()
            while url:
                parsed = urlparse(url)
                if (
                    parsed.scheme != "https" or parsed.netloc != "api.powerplatform.com"
                    or parsed.path != "/environmentmanagement/environments" or parsed.fragment or url in seen
                ):
                    raise ValueError("환경 목록 pagination 범위 또는 반복 링크 오류")
                seen.add(url)
                for attempt in range(4):
                    response = session.get(url, timeout=(10, 60), allow_redirects=False)
                    if response.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                        break
                    retry = response.headers.get("Retry-After", "")
                    delay = int(retry) if retry.isdigit() else 2**attempt
                    response.close()
                    if delay > 60:
                        raise requests.Timeout("Server retry delay exceeds export limit")
                    time.sleep(delay)
                with response:
                    if response.status_code in (401, 403):
                        reason, detail = "permission_denied", f"Power Platform HTTP {response.status_code}"
                        break
                    if response.status_code in (404, 405, 501):
                        reason, detail = "feature_unavailable", f"Power Platform HTTP {response.status_code}"
                        break
                    response.raise_for_status()
                    body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("환경 목록 응답 형식 오류")
                rows = body.get("value")
                if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                    raise ValueError("환경 목록 응답 형식 오류")
                for row in rows:
                    if str(row.get("tenantId", "")).lower() != tenant:
                        raise ValueError("응답 환경의 테넌트를 확인하지 못했습니다.")
                    identifier = row.get("id")
                    if not isinstance(identifier, str) or not identifier or identifier.lower() in identifiers:
                        raise ValueError("환경 식별자 누락·중복")
                    identifiers.add(identifier.lower())
                    values = {key: row.get(source) for key, source in (
                        ("display_name", "displayName"), ("environment_type", "type"),
                        ("protection_level", "protectionLevel"), ("region", "azureRegion"),
                    )}
                    if any(value is not None and not isinstance(value, str) for value in values.values()):
                        raise ValueError("환경 메타데이터 형식 오류")
                    environments.append(AdminEnvironment(environment_id=identifier, **values))
                next_link = body.get("@odata.nextlink")
                if next_link is not None and not isinstance(next_link, str):
                    raise ValueError("환경 pagination 링크 형식 오류")
                url = next_link or ""
    except ClientAuthenticationError:
        reason, detail = "permission_denied", "별도 관리자 Power Platform 토큰을 얻지 못함. 토큰·원문 오류 미저장"
    except requests.RequestException as exc:
        reason, detail = "error", "공식 환경 API 조회 실패: " + type(exc).__name__
    observed = datetime.now(UTC)
    return AdminEvidenceExport(
        schema_version=1, source_type="official_admin_read", tenant_id=tenant,
        tenant_verified=verified, exported_at=observed,
        reads=[AdminReadResult(
            source="powerplatform.environments", command=ENVIRONMENTS_URL,
            module_version="Power Platform API 2024-10-01",
            scope="authenticated administrator-visible environments; not asserted tenant-wide",
            observed_at=now, completed=reason is None,
            object_count=len(environments) if reason is None else None,
            environments=environments if reason is None else [],
            reason=reason, detail=detail,
        )],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=lambda value: str(uuid.UUID(value)))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise FileExistsError("기존 관리자 내보내기를 덮어쓰지 않습니다.")
        result = export_environments(args.tenant_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(redact(result.model_dump(mode="json")), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"관리자 환경 읽기 내보내기: {args.output}; 완료={result.reads[0].completed}")
        return 0 if result.reads[0].completed else 2
    except (ValueError, KeyError, IndexError, OSError) as exc:
        print(f"관리자 환경 내보내기 중단: {type(exc).__name__}. 응답·계정·토큰 원문은 출력하지 않았습니다.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
