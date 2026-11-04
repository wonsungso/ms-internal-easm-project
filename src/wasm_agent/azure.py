from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import requests
from azure.core.exceptions import ClientAuthenticationError

from wasm_agent.models import Issue, Reason

ARM = "https://management.azure.com"
ARM_SCOPE = ARM + "/.default"
AI_SCOPE = "https://ai.azure.com/.default"
LOG_SCOPE = "https://api.loganalytics.io/.default"
MSGRAPH = "https://graph.microsoft.com"
MSGRAPH_SCOPE = MSGRAPH + "/.default"
GRAPH_URL = ARM + "/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01"


class Token(Protocol):
    token: str


class Credential(Protocol):
    def get_token(self, *scopes: str) -> Token: ...


class AccessError(RuntimeError):
    def __init__(self, reason: Reason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


def credential_token(credential: Credential, scope: str) -> Token:
    for attempt in range(8):
        try:
            return credential.get_token(scope)
        except ClientAuthenticationError as exc:
            if "AADSTS700027" not in str(exc) or attempt == 7:
                raise
            time.sleep(min(2**attempt, 10))
    raise AssertionError("unreachable")


def trusted_url(url: str, audience: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise ValueError("HTTPS Azure URL만 허용하며 URL 자격증명/fragment는 금지합니다.")
    if audience == ARM_SCOPE:
        allowed = parsed.hostname == "management.azure.com"
    elif audience == AI_SCOPE:
        allowed = bool(parsed.hostname and parsed.hostname.endswith(".services.ai.azure.com"))
    elif audience == LOG_SCOPE:
        allowed = parsed.hostname in ("api.loganalytics.azure.com", "api.loganalytics.io")
    elif audience == MSGRAPH_SCOPE:
        allowed = parsed.hostname == "graph.microsoft.com"
    else:
        allowed = False
    if not allowed:
        raise ValueError("인증 토큰을 허용되지 않은 대상에 전송할 수 없습니다.")


class ReaderHTTP:
    def __init__(
        self, credential: Credential, session: requests.Session | None = None,
        store: EvidenceStore | None = None, subscription: str = "",
    ) -> None:
        self.credential = credential
        self.session = session or requests.Session()
        self.store = store
        self.subscription = subscription
        self.last_ref: str | None = None

    def close(self) -> None:
        self.session.close()

    def capture_error(self, url: str, response: requests.Response) -> None:
        if self.store:
            try:
                body = response.json()
            except ValueError:
                body = {"body": "non-JSON error body withheld"}
            self.last_ref = self.store.save(
                url, {"http_status": response.status_code, "error_response": body}, self.subscription,
            )

    def request(
        self, method: str, url: str, audience: str = ARM_SCOPE,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trusted_url(url, audience)
        path = urlparse(url).path.lower()
        if method not in ("GET", "POST"):
            raise ValueError("읽기 전용 API의 GET/승인된 query POST만 허용합니다.")
        if method == "POST" and not (
            url == GRAPH_URL
            or re.fullmatch(r"/subscriptions/[0-9a-f-]+/providers/microsoft.costmanagement/query", path)
            or (audience == LOG_SCOPE and re.fullmatch(r"/v1/workspaces/[0-9a-f-]+/query", path))
        ):
            raise ValueError("승인되지 않은 POST API입니다.")
        if re.search(r"/(?:listkeys|listsecrets|listcredentials)(?:/|$)", path):
            raise ValueError("비밀 조회 API는 금지합니다.")
        token = credential_token(self.credential, audience).token
        for attempt in range(4):
            try:
                response = self.session.request(
                    method, url, json=body,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    timeout=(10, 60), allow_redirects=False,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt < 3:
                    time.sleep(2**attempt)
                    continue
                raise AccessError("error", "network_error; 요청 본문/토큰은 기록하지 않음") from exc
            code = response.status_code
            if code in (429, 500, 502, 503, 504) and attempt < 3:
                delays = [
                    response.headers.get(name, "") for name in (
                        "Retry-After",
                        "x-ms-ratelimit-microsoft.costmanagement-entity-retry-after",
                        "x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after",
                        "x-ms-ratelimit-microsoft.costmanagement-tenant-retry-after",
                        "x-ms-ratelimit-microsoft.costmanagement-clienttype-retry-after",
                    )
                ]
                seconds = max([int(value) for value in delays if value.isdigit()] or [0])
                if seconds > 60:
                    self.capture_error(url, response)
                    response.close()
                    raise AccessError("error", f"HTTP {code}; 서버가 {seconds}초 대기를 요청하여 이번 수집은 중단")
                response.close()
                time.sleep(max(seconds, 2**attempt))
                continue
            if code in (401, 403):
                self.capture_error(url, response)
                response.close()
                hint = (
                    "Graph 애플리케이션 권한, 관리자 동의, API별 라이선스 요건 확인"
                    if urlparse(url).hostname == "graph.microsoft.com" else "네트워크 ACL/역할을 함께 확인"
                )
                raise AccessError("permission_denied", f"HTTP {code}; {hint}")
            if code in (404, 405, 501):
                self.capture_error(url, response)
                response.close()
                raise AccessError("feature_unavailable", f"HTTP {code}; 리소스/지원 API 프로필 확인")
            if code == 204:
                response.close()
                return {}
            if not 200 <= code < 300:
                self.capture_error(url, response)
                response.close()
                raise AccessError("error", f"HTTP {code}; 오류 본문은 출력하지 않음")
            try:
                payload = response.json()
            except ValueError as exc:
                raise AccessError("error", "JSON 응답이 아닙니다.") from exc
            finally:
                response.close()
            if not isinstance(payload, dict):
                raise AccessError("error", "객체형 JSON 응답이 아닙니다.")
            if self.store:
                self.last_ref = self.store.save(url, payload, self.subscription)
            return payload
        raise AssertionError("unreachable")

    def list_arm(self, url: str) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        seen: set[str] = set()
        origin_path = urlparse(url).path
        while url:
            if url in seen or urlparse(url).path != origin_path:
                raise AccessError("error", "비정상 pagination 링크")
            seen.add(url)
            payload = self.request("GET", url)
            page = payload.get("value")
            if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
                raise AccessError("error", "목록 응답에 value 배열이 없습니다.")
            values.extend(page)
            url = payload.get("nextLink") or ""
        return values

    def list_graph(self, url: str) -> list[dict[str, Any]]:
        """Read every page of a Microsoft Graph collection; nextLink must stay on the same path."""
        values: list[dict[str, Any]] = []
        seen: set[str] = set()
        origin_path = urlparse(url).path
        while url:
            if url in seen or urlparse(url).path != origin_path:
                raise AccessError("error", "비정상 pagination 링크")
            seen.add(url)
            payload = self.request("GET", url, MSGRAPH_SCOPE)
            page = payload.get("value")
            if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
                raise AccessError("error", "목록 응답에 value 배열이 없습니다.")
            values.extend(page)
            url = payload.get("@odata.nextLink") or ""
        return values


SENSITIVE = re.compile(
    r"(?i)(password|secret|authorization|connection.?string|private.?key|api.?key|access.?token|refresh.?token|credential)"
)
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")


def redact(value: Any, key: str = "") -> Any:
    if key.lower() in ("owner", "sponsor") and isinstance(value, str) and value:
        return value if value.startswith("identity-") else (
            "identity-" + hashlib.sha256(value.lower().encode()).hexdigest()[:12]
        )
    if SENSITIVE.search(key) or key.lower() in (
        "token", "key", "instructions", "input", "output", "messages", "content", "environmentvariables",
    ):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = JWT.sub("[REDACTED_TOKEN]", value)
        value = re.sub(
            r"-----BEGIN (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----.*?-----END (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----",
            "[REDACTED_PRIVATE_KEY]", value, flags=re.DOTALL,
        )
        value = re.sub(r"(?i)Bearer\s+\S+", "******", value)
        value = re.sub(r"(?i)(sig|AccountKey|SharedAccessSignature|api[-_]?key|token|password|secret)=([^&;\s]+)",
                       r"\1=[REDACTED]", value)
        return EMAIL.sub(
            lambda match: "identity-" + hashlib.sha256(match[0].lower().encode()).hexdigest()[:12],
            value,
        )
    return value


class EvidenceStore:
    def __init__(self, base: Path, now: datetime | None = None) -> None:
        instant = now or datetime.now(UTC)
        self.path = base / (instant.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6])
        self.path.mkdir(parents=True, exist_ok=False)
        self._lock = threading.Lock()
        self._refs: dict[str, list[str]] = {}

    def save(self, target: str, payload: Any, subscription: str = "") -> str:
        filename = hashlib.sha256(target.encode()).hexdigest()[:16] + "-" + uuid.uuid4().hex[:8] + ".json"
        path = self.path / filename
        path.write_text(json.dumps(redact({
            "collected_at": datetime.now(UTC).isoformat(),
            "target": target,
            "subscription_id": subscription,
            "response": payload,
        }), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        ref = str(path.resolve())
        with self._lock:
            self._refs.setdefault(subscription, []).append(ref)
        return ref

    def refs(self, subscription: str) -> list[str]:
        with self._lock:
            return list(self._refs.get(subscription, []))


def issue(http: ReaderHTTP, collector: str, target: str, error: AccessError,
          roles: tuple[str, ...]) -> Issue:
    return Issue(
        subscription_id=http.subscription or None, collector=collector, target=target,
        reason=error.reason, detail=str(error), required_roles=list(roles),
        evidence_refs=[http.last_ref] if http.last_ref else [],
    )


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
