from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

from easm_agent.azure import redact
from easm_agent.models import AssessmentProvenance


def digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def assessment_provenance(
    criteria: dict[str, Any], conventions: dict[str, Any],
    origin: Literal["evaluation", "saved_snapshot_reassessment"],
) -> AssessmentProvenance:
    snapshot = redact(criteria)
    convention_snapshot = redact(conventions)
    try:
        collector_version = version("easm-agent")
    except PackageNotFoundError:
        collector_version = "unavailable - package metadata not installed"
    package = Path(__file__).parent
    sources = {
        path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(package.rglob("*.py"))
    }
    return AssessmentProvenance(
        evaluated_at=datetime.now(UTC), origin=origin,
        criteria_snapshot=snapshot, criteria_sha256=digest(snapshot),
        conventions_snapshot=convention_snapshot, conventions_sha256=digest(convention_snapshot),
        collector_version=collector_version, collector_source_sha256=digest(sources),
    )
