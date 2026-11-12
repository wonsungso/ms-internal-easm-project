from __future__ import annotations

import base64
import csv
import os
import re
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any, Protocol

import requests
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


class CertificateRegistry(Protocol):
    def certificates(self) -> list[dict[str, Any]]: ...
    def add(self, certificate: x509.Certificate, key_id: str, start: datetime, end: datetime) -> None: ...
    def remove(self, key_id: str) -> None: ...
    def close(self) -> None: ...


class GraphCertificates:
    def __init__(self, client_id: str | None = None) -> None:
        self.client_id = str(uuid.UUID(client_id)) if client_id else None
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
        if self.client_id is None:
            raise ValueError("인증서 작업에는 진단 SP client_id가 필요합니다.")
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
            "displayName": "CN=easmagent-temporary-validation",
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


def restrict_directory(path: Path) -> None:
    if os.name == "nt":
        identity = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True, text=True, check=True,
        )
        sid = next(csv.reader(StringIO(identity.stdout)))[1]
        result = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
            capture_output=True, check=False,
        )
        if result.returncode:
            raise RuntimeError("임시 인증서 폴더의 사용자 전용 ACL 설정 실패")
    else:
        path.chmod(0o700)


class TemporaryCertificate:
    def __init__(self, setup: dict[str, Any], registry: CertificateRegistry | None = None) -> None:
        self.setup = setup
        self.registry = registry or GraphCertificates(setup["client_id"])
        self.directory: Path | None = None
        self.key_id: str | None = None
        self.registration_attempted = False
        self.original_ids: set[str] = set()

    def certificate_ids(self) -> set[str]:
        rows = self.registry.certificates()
        return {row["keyId"] for row in rows}

    def __enter__(self) -> dict[str, str]:
        try:
            self.directory = Path(tempfile.mkdtemp(prefix="easmagent-cert-")).resolve()
            restrict_directory(self.directory)
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            now = datetime.now(UTC)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "easmagent-temporary-validation")])
            certificate = (
                x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                .public_key(private_key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(hours=4))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .sign(private_key, hashes.SHA256())
            )
            private_path = self.directory / "credential.pem"
            fd = os.open(private_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(private_key.private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                ))
                stream.write(certificate.public_bytes(serialization.Encoding.PEM))
            self.original_ids = self.certificate_ids()
            self.registration_attempted = True
            self.key_id = str(uuid.uuid4())
            self.registry.add(
                certificate, self.key_id, certificate.not_valid_before_utc, certificate.not_valid_after_utc,
            )
            added = self.certificate_ids() - self.original_ids
            if added != {self.key_id}:
                raise RuntimeError("추가된 임시 인증서를 유일하게 식별하지 못했습니다.")
            environment = os.environ.copy()
            for key in ("AZURE_CLIENT_SECRET", "AZURE_FEDERATED_TOKEN_FILE", "AZURE_CLIENT_CERTIFICATE_PASSWORD"):
                environment.pop(key, None)
            environment.update({
                "AZURE_TENANT_ID": self.setup["tenant_id"],
                "AZURE_CLIENT_ID": self.setup["client_id"],
                "AZURE_CLIENT_CERTIFICATE_PATH": str(private_path),
                "PYTHONIOENCODING": "utf-8",
            })
            print("진단용 임시 인증서 준비 완료: 사용자 전용 ACL, 비밀값 출력 없음", flush=True)
            return environment
        except (RuntimeError, ValueError, OSError, AzureError, subprocess.SubprocessError):
            self.cleanup()
            raise

    def cleanup(self) -> None:
        error = None
        try:
            if self.registration_attempted and self.key_id is None:
                added = self.certificate_ids() - self.original_ids
                if len(added) == 1:
                    self.key_id = added.pop()
                elif added:
                    raise RuntimeError("임시 키 식별 불가; 기존 인증서는 삭제하지 않았습니다.")
            if self.key_id:
                self.registry.remove(self.key_id)
                if self.key_id in self.certificate_ids():
                    raise RuntimeError("임시 공개 인증서 삭제 재조회 실패")
        except (RuntimeError, OSError, ValueError, AzureError) as exc:
            error = exc
        finally:
            if self.directory:
                for name in ("credential.pem", "public.pem"):
                    (self.directory / name).unlink(missing_ok=True)
                self.directory.rmdir()
                self.directory = None
            self.registry.close()
        if error:
            raise RuntimeError("임시 인증서 등록 정리 실패; 개인키 파일은 정리했습니다.") from error
        print("일회성 공개 인증서·개인키 정리 완료", flush=True)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.cleanup()
