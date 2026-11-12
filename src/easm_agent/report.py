from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import unquote

from easm_agent.assessment_codes import ASSESSMENT_REVISION, migrate_revision_4_codes
from easm_agent.azure import redact
from easm_agent.models import Collection, Finding
from easm_agent.provenance import digest
from easm_agent.report_excel import write_workbook

RAW_PATTERN = "raw-data-*.json"
RUN_PATTERN = re.compile(r"(?P<stamp>\d{8}T\d{12}Z)(?:-(?P<sequence>\d+))?")


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")


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


def report_name(data: Collection, run_stamp: str | None = None) -> str:
    return f"report-{run_stamp or _stamp(data)}.xlsx"


def raw_name(data: Collection, run_stamp: str | None = None) -> str:
    return f"raw-data-{run_stamp or _stamp(data)}.json"


def latest_raw(output: Path) -> Path | None:
    """Find the newest run, accepting legacy flat files and a directly selected run folder."""
    candidates = list(output.glob(RAW_PATTERN))
    for directory in output.glob("*"):
        if RUN_PATTERN.fullmatch(directory.name) and directory.is_dir() and not directory.is_symlink():
            candidates.extend(directory.glob(RAW_PATTERN))
    found = []
    for path in candidates:
        if not path.is_file() or path.is_symlink():
            continue
        run = RUN_PATTERN.fullmatch(path.parent.name)
        file_stamp = path.stem.removeprefix("raw-data-")
        file_run = RUN_PATTERN.fullmatch(file_stamp)
        stamp = run["stamp"] if run else file_run["stamp"] if file_run else file_stamp
        try:
            when = datetime.strptime(stamp, "%Y%m%dT%H%M%S%fZ" if run or file_run else "%Y%m%dT%H%M%SZ")
        except ValueError:
            continue
        sequence = int((run or file_run)["sequence"] or 0) if run or file_run else 0
        found.append(((when, sequence, path.name), path))
    return max(found, key=lambda entry: entry[0])[1] if found else None


def create_run_directory(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    sequence = 0
    while True:
        path = output / (stamp if sequence == 0 else f"{stamp}-{sequence}")
        try:
            path.mkdir()
        except FileExistsError:
            sequence += 1
        else:
            return path


def load_result(output: Path) -> dict[str, Any]:
    """Return collection/findings/mode/evidence/provenance/manifest saved in the newest raw-data file."""
    path = latest_raw(output)
    if path is None:
        raise ValueError(f"{RAW_PATTERN} 파일을 찾을 수 없습니다.")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("schema_version") != 1:
        raise ValueError("지원되지 않는 결과 스키마입니다.")
    revision = result["collection"].get("facts", {}).get("assessment_revision")
    if revision not in (None, 1, 2, 3, 4, ASSESSMENT_REVISION):
        raise ValueError(f"지원되지 않는 심사 기준 버전입니다: {revision}")
    if revision not in (4, ASSESSMENT_REVISION):
        collection = result["collection"]
        legacy_audit = revision != 3 and any(
            row.get("se_code") == "OE-SY-16" for row in result.get("findings", [])
        )
        numbering = {
            "BI-SY-12": "BI-SY-11", "BI-SY-13": "BI-SY-12", "BI-SY-14": "BI-SY-13",
        }
        if revision != 3:
            numbering.update({
                "OE-SY-17": "OE-SY-16", "OE-SY-18": "OE-SY-17",
                "OE-SY-19": "OE-SY-18", "OE-SY-20": "OE-SY-19",
            })
        if legacy_audit:
            numbering["OE-SY-16"] = "OE-SY-15"
        result["findings"] = [
            {**row, "se_code": numbering.get(row["se_code"], row["se_code"])}
            for row in result.get("findings", [])
            if row["se_code"] != "BI-SY-11" and not (legacy_audit and row["se_code"] == "OE-SY-15")
        ]
        for field in ("agent_ca_policies", "risky_agents"):
            collection.pop(field, None)
        collection["issues"] = [
            row for row in collection.get("issues", [])
            if row.get("collector") not in ("conditional_access", "risky_agents", "foundry_red_teams")
        ]
        for agent in collection.get("agents", []):
            agent["se_codes"] = [
                numbering.get(code, code) for code in agent.get("se_codes", [])
                if code != "BI-SY-11" and not (legacy_audit and code == "OE-SY-15")
            ]
        for field in ("proposals", "proposal_observations"):
            collection[field] = [row for row in collection.get(field, []) if row["code"] != "BI-SY-11"]
            for row in collection[field]:
                row["code"] = numbering.get(row["code"], row["code"])
        for row in collection.get("issues", []):
            name = row["collector"].removeprefix("proposal_")
            if name in numbering and row["collector"].startswith("proposal_"):
                row["collector"] = "proposal_" + numbering[name]
        facts = collection.setdefault("facts", {})
        if "proposal_incomplete" in facts:
            facts["proposal_incomplete"] = [
                numbering.get(code, code) for code in facts["proposal_incomplete"] if code != "BI-SY-11"
            ]
        facts["assessment_revision"] = 4
    if revision != ASSESSMENT_REVISION:
        migrate_revision_4_codes(result)
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
            reference_sha256 = hashlib.sha256(redact(ref).encode("utf-8")).hexdigest()
            identifier = next((
                item["id"] for item in old_refs
                if (item.get("reference") == redact(ref) or item.get("reference_sha256") == reference_sha256)
                and item.get("status") == "attached"
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
                    **item, "reference": "evidence:" + identifier if attached else item["reference"],
                    "sha256": identifier if attached else None,
                    "status": "attached" if attached else "not_found",
                    "detail": None if attached else "파일 확인불가 - 안전한 로컬 파일 연결 불가",
                }
                if updated not in references:
                    references.append(updated)
        else:
            references.append({
                "reference": "evidence:" + identifier if attached else redact(ref),
                "reference_sha256": hashlib.sha256(redact(ref).encode("utf-8")).hexdigest(),
                "id": identifier, "sha256": identifier if attached else None,
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
    collection["facts"]["assessment_revision"] = ASSESSMENT_REVISION
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
    *, new_run: bool = True,
) -> Path:
    """Write a unique run folder, or rebuild an explicitly selected existing run."""
    output.mkdir(parents=True, exist_ok=True)
    result = normalize_result(data, findings, output, mode)
    if new_run:
        output = create_run_directory(output)
        run_stamp = output.name
    else:
        existing = latest_raw(output)
        run_stamp = existing.stem.removeprefix("raw-data-") if existing else (
            output.name if RUN_PATTERN.fullmatch(output.name) else None
        )
    normalized = Collection.model_validate(result["collection"])
    rows = [Finding.model_validate(row) for row in result["findings"]]
    workbook = output / report_name(normalized, run_stamp)
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
        atomic_write(output / raw_name(normalized, run_stamp), json_bytes(result))
    finally:
        staging.unlink(missing_ok=True)
        if new_run and not any(output.iterdir()):
            output.rmdir()
    print(f"결과 파일: {workbook} / {output / raw_name(normalized, run_stamp)}")
    return workbook
