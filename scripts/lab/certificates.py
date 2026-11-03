from __future__ import annotations

import base64
import re
import uuid
from datetime import datetime
from typing import Any, Protocol

import requests
from azure.identity import DefaultAzureCredential
from cryptography import x509
from cryptography.hazmat.primitives import serialization


class CertificateRegistry(Protocol):
    def certificates(self) -> list[dict[str, Any]]: ...
    def add(self, certificate: x509.Certificate, key_id: str, start: datetime, end: datetime) -> None: ...
    def remove(self, key_id: str) -> None: ...
    def close(self) -> None: ...


class GraphCertificates:
    def __init__(self, client_id: str) -> None:
        self.client_id = str(uuid.UUID(client_id))
        self.credential = DefaultAzureCredential(
            exclude_environment_credential=True, exclude_workload_identity_credential=True,
            exclude_managed_identity_credential=True, exclude_shared_token_cache_credential=True,
            exclude_visual_studio_code_credential=True, exclude_developer_cli_credential=True,
            exclude_powershell_credential=True, exclude_broker_credential=True,
        )
        self.object_id: str | None = None

    def request(self, method: str, path: str, body: dict[str, Any] | None = None,
                params: dict[str, str] | None = None) -> dict[str, Any]:
        token = self.credential.get_token("https://graph.microsoft.com/.default").token
        response = requests.request(
            method, "https://graph.microsoft.com/v1.0" + path,
            headers={"Authorization": f"Bearer {token}"}, json=body, params=params,
            timeout=30, allow_redirects=False,
        )
        try:
            if not 200 <= response.status_code < 300:
                try:
                    code = (response.json().get("error") or {}).get("code", "")
                except ValueError:
                    code = ""
                safe = code if re.fullmatch(r"[A-Za-z0-9._-]{1,100}", code) else "unknown"
                raise RuntimeError(f"관리자 Graph 인증서 작업 실패: HTTP {response.status_code}, code={safe}")
            return response.json() if response.content else {}
        finally:
            response.close()

    def certificates(self) -> list[dict[str, Any]]:
        if self.object_id is None:
            result = self.request("GET", "/applications", params={
                "$filter": f"appId eq '{self.client_id}'", "$select": "id",
            })
            rows = result.get("value", [])
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
                raise RuntimeError("설정의 진단 앱을 유일하게 식별하지 못했습니다.")
            self.object_id = str(uuid.UUID(rows[0]["id"]))
        result = self.request("GET", "/applications/" + self.object_id, params={"$select": "keyCredentials"})
        keys = result.get("keyCredentials")
        if not isinstance(keys, list):
            raise RuntimeError("Graph keyCredentials 배열이 없습니다.")
        return keys

    def replace(self, certificates: list[dict[str, Any]]) -> None:
        if self.object_id is None:
            raise RuntimeError("Graph 진단 앱 식별 전에는 자격증명을 변경할 수 없습니다.")
        if any(not entry.get("key") for entry in certificates):
            raise RuntimeError("기존 공개 인증서 내용을 보존할 수 없어 변경하지 않습니다.")
        fields = {"keyId", "key", "type", "usage", "displayName", "customKeyIdentifier", "startDateTime", "endDateTime"}
        self.request("PATCH", "/applications/" + self.object_id, {
            "keyCredentials": [{key: value for key, value in item.items() if key in fields} for item in certificates],
        })

    def add(self, certificate: x509.Certificate, key_id: str, start: datetime, end: datetime) -> None:
        current = self.certificates()
        current.append({
            "keyId": key_id, "type": "AsymmetricX509Cert", "usage": "Verify",
            "displayName": "CN=seagent-temporary-validation",
            "key": base64.b64encode(certificate.public_bytes(serialization.Encoding.DER)).decode("ascii"),
            "startDateTime": start.isoformat(), "endDateTime": end.isoformat(),
        })
        self.replace(current)

    def remove(self, key_id: str) -> None:
        current = self.certificates()
        remaining = [entry for entry in current if entry["keyId"] != key_id]
        if len(remaining) != len(current):
            self.replace(remaining)

    def close(self) -> None:
        self.credential.close()
