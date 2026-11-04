from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import UTC
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import unquote

from wasm_agent.azure import redact
from wasm_agent.models import Collection, Finding
from wasm_agent.report_excel import write_workbook

RAW_PATTERN = "raw-data-*.json"


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.{uuid.uuid4().hex}.pending")
    try:
        staging.write_bytes(payload)
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def _stamp(data: Collection) -> str:
    return data.collected_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def report_name(data: Collection) -> str:
    return f"report-{_stamp(data)}.xlsx"


def raw_name(data: Collection) -> str:
    return f"raw-data-{_stamp(data)}.json"


def latest_raw(output: Path) -> Path | None:
    """Return the newest raw-data-<timestamp>.json; the UTC timestamp sorts chronologically."""
    found = sorted(path for path in output.glob(RAW_PATTERN) if path.is_file() and not path.is_symlink())
    return found[-1] if found else None


def load_result(output: Path) -> dict[str, Any]:
    """Return collection/findings/mode/evidence/provenance/manifest saved in the newest raw-data file."""
    path = latest_raw(output)
    if path is None:
        raise ValueError(f"{RAW_PATTERN} 파일을 찾을 수 없습니다.")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("schema_version") != 1:
        raise ValueError("지원되지 않는 결과 스키마입니다.")
    return result


class EvidenceLinks:
    """Resolve evidence references to safe local JSON files below the evidence directory."""

    def __init__(self, data: Collection, output: Path) -> None:
        self.output = output.resolve()
        directory = data.facts.get("evidence_directory")
        self.root = Path(directory).absolute() if directory and self.safe(str(directory)) else None

    @staticmethod
    def safe(value: str) -> bool:
        decoded = unquote(value).replace("\\", "/")
        return (
            not decoded.startswith("//")
            and ".." not in decoded.split("/")
            and not any(ord(char) < 32 for char in decoded)
            and "://" not in decoded
            and not re.search(r"(^|/)[^/]*:", decoded[2:] if re.match(r"^[A-Za-z]:/", decoded) else decoded)
        )

    def source(self, reference: str) -> Path | None:
        if self.root is None or not self.root.is_dir() or not self.safe(reference):
            return None
        path = Path(reference)
        # Reject Windows drive-relative paths, including on non-Windows test hosts.
        windows = PureWindowsPath(reference)
        if windows.drive and not windows.is_absolute():
            return None
        candidates = [path] if path.is_absolute() else [
            self.output / path, self.root / path,
            Path.cwd() / path,
        ]
        for candidate in candidates:
            try:
                if any(part.is_symlink() for part in (candidate, *candidate.parents)):
                    continue
                resolved = candidate.resolve()
                if not resolved.is_relative_to(self.root):
                    continue
                if resolved.suffix.lower() != ".json" or not resolved.is_file():
                    continue
            except (OSError, ValueError):
                continue
            return resolved
        return None


def normalize_result(
    data: Collection, findings: list[Finding], output: Path, mode: str,
) -> dict[str, Any]:
    if mode not in ("live", "fixture"):
        raise ValueError("지원되지 않는 데이터 구분입니다.")
    try:
        previous = load_result(output)
    except (OSError, KeyError, ValueError):
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


def write_reports(
    data: Collection, findings: list[Finding], output: Path, mode: str = "live",
) -> Path:
    """Write report-<timestamp>.xlsx and raw-data-<timestamp>.json; return the workbook path."""
    output.mkdir(parents=True, exist_ok=True)
    result = normalize_result(data, findings, output, mode)
    normalized = Collection.model_validate(result["collection"])
    rows = [Finding.model_validate(row) for row in result["findings"]]
    workbook = output / report_name(normalized)
    staging = output / f".report.{uuid.uuid4().hex}.pending.xlsx"
    try:
        write_workbook(normalized, rows, staging, mode, result["provenance"]["references"])
        payload = staging.read_bytes()
        result["manifest"] = {
            "product": "EASM", "mode": mode, "collected_at": normalized.collected_at.isoformat(),
            "files": [{
                "path": workbook.name, "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }],
            "credentials_included": False,
            "data_hash_scope": "UTF-8 JSON with indent=2, excluding manifest",
            "data_sha256": hashlib.sha256(json_bytes({
                key: value for key, value in result.items() if key != "manifest"
            })).hexdigest(),
        }
        os.replace(staging, workbook)
        atomic_write(output / raw_name(normalized), json_bytes(result))
    finally:
        staging.unlink(missing_ok=True)
    print(f"결과 파일: {workbook} / {output / raw_name(normalized)}")
    return workbook
