from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
        value = re.sub(r"(?i)Bearer\s+\S+", "Bearer [REDACTED]", value)
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
