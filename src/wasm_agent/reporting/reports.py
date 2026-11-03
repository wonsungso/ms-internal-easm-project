from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from wasm_agent.models import AgentEvidence, Collection, Finding
from wasm_agent.reporting.presentation import (
    EVALUATION_FIELDS,
    FIELD_NAMES,
    SE_NAMES,
    customer_document,
    evaluation_columns,
    html_document,
    metric,
    readable,
)
from wasm_agent.utils.evidence import redact


def json_file(path: Path, value: Any) -> None:
    path.write_text(json.dumps(redact(value), ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def csv_file(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            values = {}
            for key in fields:
                value = redact(row.get(key), key)
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                    value = "'" + value
                values[key] = value
            writer.writerow(values)


def md_cell(value: Any) -> str:
    if value is None:
        return "null"
    return str(value).replace("|", "&#124;").replace("\n", "<br>").replace(chr(0x2014), "-")


def write_reports(data: Collection, findings: list[Finding], output: Path, mode: str = "live") -> None:
    output.mkdir(parents=True, exist_ok=True)
    agents = [agent.model_dump(mode="json") for agent in data.agents]
    rows = [finding.model_dump(mode="json") for finding in findings]
    json_file(output / "inventory.json", agents)
    json_file(output / "collection.json", data.model_dump(mode="json"))
    json_file(output / "findings.json", rows)
    csv_file(output / "inventory.csv", agents, list(AgentEvidence.model_fields))
    csv_file(output / "summary.csv", rows, [
        "se_code", "scope", "metric_value", "level", "reason", "rationale",
        "interview_level", "gap_flag", "next_step", "evidence_refs",
    ])
    monthly: dict[tuple[str, str, str], float] = defaultdict(float)
    for row in data.costs:
        date = row.usage_date
        if date:
            month = date[:6] if date.isdigit() else date[:7]
            monthly[(row.subscription_id, row.currency, month)] += row.amount
    csv_file(output / "cost_monthly.csv", [
        {"subscription_id": sid, "currency": currency, "month": month, "amount": amount}
        for (sid, currency, month), amount in sorted(monthly.items())
    ], ["subscription_id", "currency", "month", "amount"])
    csv_file(output / "customer_summary.csv", [
        {
            "SE 코드": f.se_code, "관리 항목": SE_NAMES.get(f.se_code, "관리 항목"),
            "진단 범위": readable(f.scope), "실측값": metric(f), "판정": readable(f.level),
            "보류 또는 조회 사유": readable(f.reason) if f.reason else "해당 없음",
            "판정 근거": readable(f.rationale), "다음 조치": readable(f.next_step),
            "인터뷰 단계": readable(f.interview_level),
            "차이 확인": "검토 필요" if f.gap_flag else "차이 경고 없음",
            "증거 참조": f.evidence_refs,
        } for f in findings
    ], ["SE 코드", "관리 항목", "진단 범위", "실측값", "판정", "보류 또는 조회 사유",
        "판정 근거", "다음 조치", "인터뷰 단계", "차이 확인", "증거 참조"])
    csv_file(output / "customer_inventory.csv", [
        {
            "Agent 이름": a.agent_name, "Agent 식별자": a.agent_id,
            "구독": readable(a.subscription_id), "플랫폼": readable(a.platform),
            "탐지 근거": readable(a.detection_confidence), "사용 모델": readable(a.model),
            "담당자": readable(redact(a.owner, "owner")),
            "최근 30일 비용": readable(a.cost_30d), "통화": readable(a.currency),
            "필드 확인 상태": "; ".join(
                f"{FIELD_NAMES.get(key, key)}: {readable(status.reason)} - {readable(status.detail)}"
                for key, status in a.field_status.items()
            ) or "별도 조회 상태 기록 없음 - 값 누락은 확인 자료 없음으로 해석",
            **evaluation_columns(a, data),
        } for a in data.agents
    ], ["Agent 이름", "Agent 식별자", "구독", "플랫폼", "탐지 근거", "사용 모델",
        "담당자", "최근 30일 비용", "통화", "필드 확인 상태", *EVALUATION_FIELDS])
    document = customer_document(data, findings, output, mode)
    (output / "report.md").write_text("\n".join(document.markdown) + "\n", encoding="utf-8")
    (output / "report.html").write_text(html_document(document), encoding="utf-8")
