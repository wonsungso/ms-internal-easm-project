from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from wasm_agent.models import AgentEvidence, Collection


class ManualCollector:
    required_roles: tuple[str, ...] = ()

    def __init__(self, path: Path, now: datetime) -> None:
        self.path, self.now = path, now

    def discover(self, subscriptions: Sequence[str]) -> Collection:
        result = Collection(collected_at=self.now)
        with self.path.open(encoding="utf-8-sig", newline="") as stream:
            for number, row in enumerate(csv.DictReader(stream), 2):
                values = {key: value for key, value in row.items() if value not in ("", None)}
                if values.get("platform", "manual") not in ("manual", "other"):
                    raise ValueError(f"{self.path.name}:{number}: manual/other 플랫폼만 허용")
                for key in ("tags", "tools", "usage_30d", "field_status", "evidence_refs", "se_codes",
                            "cost_resource_ids"):
                    if key in values:
                        values[key] = json.loads(values[key])
                values.setdefault("platform", "manual")
                values.setdefault("collected_at", self.now)
                values.setdefault("detection_confidence", "manual")
                values.setdefault("evidence_refs", [str(self.path.resolve()) + f"#row-{number}"])
                try:
                    result.agents.append(AgentEvidence.model_validate(values).mark_unknowns(
                        "수동 등록 파일에 값이 없음; Azure API로 보완하지 않음",
                    ))
                except ValidationError as exc:
                    raise ValueError(f"{self.path.name}:{number}: 공통 스키마 검증 실패") from exc
        return result
