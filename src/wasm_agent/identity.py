from __future__ import annotations

import base64
import json
from typing import Any

from .azure import ARM_SCOPE, AccessError, Credential, credential_token


def verify_identity(credential: Credential, tenant: str, principal: str) -> None:
    token = credential_token(credential, ARM_SCOPE).token
    try:
        segment = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
        if claims.get("tid", "").lower() != tenant or claims.get("oid", "").lower() != principal:
            raise AccessError("permission_denied", "현재 자격증명이 지정한 수집 계정/테넌트와 다릅니다.")
    except (IndexError, ValueError, TypeError) as exc:
        raise AccessError("error", "자격증명에서 계정 일치 여부를 확인하지 못했습니다.") from exc


def rejects_broad_permissions(permissions: list[dict[str, Any]]) -> bool:
    for permission in permissions:
        for field in ("actions", "dataActions"):
            for action in permission.get(field, []):
                value = action.lower()
                if (
                    value == "*"
                    or value.endswith(("/write", "/delete"))
                    or value in (
                        "microsoft.authorization/*",
                        "microsoft.resources/deployments/*",
                        "microsoft.cognitiveservices/*",
                        "microsoft.cognitiveservices/accounts/listkeys/action",
                    )
                ):
                    return True
    return False
