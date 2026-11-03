from __future__ import annotations

import csv
import os
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

from azure.core.exceptions import AzureError
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from scripts.lab.certificates import CertificateRegistry, GraphCertificates


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
            self.directory = Path(tempfile.mkdtemp(prefix="seagent-cert-")).resolve()
            restrict_directory(self.directory)
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            now = datetime.now(UTC)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "seagent-temporary-validation")])
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
