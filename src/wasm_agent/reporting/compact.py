from __future__ import annotations

import hashlib
import json
import os
import uuid
import zipfile
from pathlib import Path
from typing import Any

from wasm_agent.models import Collection, Finding
from wasm_agent.reporting.presentation import EvidenceLinks
from wasm_agent.utils.evidence import redact

STATE_ROOT = Path(__file__).resolve().parents[3] / ".wasm-agent" / "results"


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def snapshot_path(output: Path) -> Path:
    key = hashlib.sha256(str(output.resolve()).encode("utf-8")).hexdigest()
    return STATE_ROOT / f"{key}.json"


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.{uuid.uuid4().hex}.pending")
    try:
        staging.write_bytes(payload)
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def load_result(output: Path) -> dict[str, Any]:
    """Return collection/findings/mode/evidence/provenance/manifest, snapshot before ZIP.

    Legacy collection.json and findings.json are accepted only as migration input.
    """
    snapshot = snapshot_path(output)
    if snapshot.is_file():
        return json.loads(snapshot.read_text(encoding="utf-8"))
    archive = output / "results.zip"
    if archive.is_file() and not archive.is_symlink():
        with zipfile.ZipFile(archive) as bundle:
            result = json.loads(bundle.read("data.json"))
        if result.get("schema_version") != 1:
            raise ValueError("지원되지 않는 결과 스키마입니다.")
        return result
    collection = json.loads((output / "collection.json").read_text(encoding="utf-8"))
    findings = json.loads((output / "findings.json").read_text(encoding="utf-8"))
    return {
        "schema_version": 1, "collection": collection, "findings": findings,
        "mode": collection.get("facts", {}).get("data_mode"),
        "evidence": {}, "provenance": {}, "manifest": {},
    }


def normalize_result(
    data: Collection, findings: list[Finding], output: Path, mode: str,
) -> dict[str, Any]:
    if mode not in ("live", "fixture"):
        raise ValueError("지원되지 않는 데이터 구분입니다.")
    try:
        previous = load_result(output)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        previous = {}
    cached = previous.get("evidence", {})
    collection = data.model_dump(mode="json")
    rows = [finding.model_dump(mode="json") for finding in findings]
    refs: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "evidence_refs" and isinstance(item, list):
                    refs.update(ref for ref in item if isinstance(ref, str))
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(collection)
    collect(rows)
    links = EvidenceLinks(data, output)
    evidence: dict[str, Any] = {}
    references: list[dict[str, Any]] = []
    replacements: dict[str, str] = {}
    old_refs = previous.get("provenance", {}).get("references", [])
    for ref in sorted(refs):
        payload = None
        attached = False
        identifier = ref.removeprefix("evidence:") if ref.startswith("evidence:") else ""
        if not identifier:
            identifier = next((
                item["id"] for item in old_refs
                if item.get("reference") == redact(ref) and item.get("status") == "attached"
            ), "")
        source = links.source(ref) if not ref.startswith("evidence:") else None
        if source is not None:
            try:
                payload = redact(json.loads(source.read_text(encoding="utf-8")))
                identifier, attached = digest(payload), True
            except (OSError, ValueError):
                pass
        elif identifier in cached and digest(cached[identifier]) == identifier:
            path = Path(ref)
            replayable = ref.startswith("evidence:") or (
                links.safe(ref) and not path.exists()
                and not any(part.is_symlink() for part in (path, *path.parents))
            )
            if replayable:
                payload, attached = cached[identifier], True
        if not attached:
            identifier = identifier if len(identifier) == 64 else hashlib.sha256(ref.encode()).hexdigest()
        replacements[ref] = "evidence:" + identifier
        replacements[redact(ref)] = "evidence:" + identifier
        if attached:
            evidence[identifier] = payload
        originals = [item for item in old_refs if item.get("id") == identifier]
        if ref.startswith("evidence:") and originals:
            for item in originals:
                updated = {
                    **item, "sha256": identifier if attached else None,
                    "status": "attached" if attached else "not_found",
                    "detail": None if attached else "파일 확인불가 - 안전한 로컬 파일 연결 불가",
                }
                if updated not in references:
                    references.append(updated)
        else:
            references.append({
                "reference": redact(ref), "id": identifier, "sha256": identifier if attached else None,
                "status": "attached" if attached else "not_found",
                "detail": None if attached else "파일 확인불가 - 안전한 로컬 파일 연결 불가",
            })

    def normalized(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: normalized(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalized(item) for item in value]
        if isinstance(value, str):
            return replacements.get(value, value)
        return value

    collection = normalized(redact(collection))
    collection["facts"]["data_mode"] = mode
    if "evidence_directory" in collection["facts"]:
        collection["facts"]["evidence_directory"] = "embedded:evidence"
    return {
        "schema_version": 1, "collection": collection, "findings": normalized(redact(rows)), "mode": mode,
        "evidence": evidence,
        "provenance": {
            "evidence_hash_scope": "SHA-256 - masked JSON, UTF-8, sorted keys, compact separators",
            "references": references,
            "unattached_evidence": [item for item in references if item["status"] != "attached"],
        },
        "manifest": {"credentials_included": False, "files": []},
    }
