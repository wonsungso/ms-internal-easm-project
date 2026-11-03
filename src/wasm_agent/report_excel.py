from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import BaseModel

from wasm_agent.evidence import redact
from wasm_agent.models import (
    AgentEvidence,
    Collection,
    CostRecord,
    EvaluationRun,
    Finding,
    Issue,
    LogSetting,
    ModelDeployment,
    SecurityRecommendation,
)
from wasm_agent.report_html import FIELD_NAMES, SE_NAMES, metric, readable

EMPTY = "수집된 데이터 없음 - 미수행 또는 0건으로 확정하지 않음"
ORIGINAL = "원본 JSON"


def portable_workbook(payload: bytes, replacements: dict[str, str]) -> bytes:
    """Replace original evidence paths in a snapshot, including JSON-escaped paths."""
    variants = {}
    for source, target in replacements.items():
        if not source:
            continue
        variants[source] = target
        variants[json.dumps(source, ensure_ascii=False)[1:-1]] = (
            json.dumps(target, ensure_ascii=False)[1:-1]
        )
    pattern = re.compile("|".join(re.escape(key) for key in sorted(
        variants, key=len, reverse=True,
    ))) if variants else None
    book = load_workbook(BytesIO(payload), keep_links=False)
    try:
        for sheet in book:
            for row in sheet:
                for cell in row:
                    if not isinstance(cell.value, str):
                        continue
                    value = (
                        pattern.sub(lambda match: variants[match[0]], cell.value)
                        if pattern else cell.value
                    )
                    if len(value) > 32767:
                        raise ValueError(
                            f"Excel 셀 길이 오류: {sheet.title}!{cell.coordinate} "
                            f"- {len(value)}자, 최대 32767자"
                        )
                    cell.value = value
                    cell.data_type = "s"
                    cell.hyperlink = None
        output = BytesIO()
        book.save(output)
        return output.getvalue()
    finally:
        book.close()


def _value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def _cell(sheet: Worksheet, row: int, column: int, value: Any) -> None:
    value = _value(value)
    if isinstance(value, str) and len(value) > 32767:
        raise ValueError(
            f"Excel 셀 길이 오류: {sheet.title}!{get_column_letter(column)}{row} "
            f"- {len(value)}자, 최대 32767자"
        )
    cell = sheet.cell(row, column, value)
    if isinstance(value, str):
        # Assigning a leading '=' normally makes openpyxl create a formula.
        cell.data_type = "s"
        cell.number_format = "@"
    cell.font = Font(name="Arial", size=10, color="172B4D")
    cell.alignment = Alignment(vertical="top", wrap_text=True)
    cell.hyperlink = None


def _table(
    book: Workbook, title: str, headers: list[str], rows: Iterable[dict[str, Any]],
) -> Worksheet:
    sheet = book.create_sheet(title)
    sheet.freeze_panes = "A2"
    sheet.sheet_view.showGridLines = False
    for column, header in enumerate(headers, 1):
        _cell(sheet, 1, column, header)
        cell = sheet.cell(1, column)
        cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17365D")
        sheet.column_dimensions[get_column_letter(column)].width = (
            64 if header == ORIGINAL else
            48 if header in {"원인", "근거", "다음조치", "detail", "evidence_refs", "설명"} else 24
        )
    row_number = 1
    for row_number, row in enumerate(rows, 2):
        safe = redact(row)
        for column, header in enumerate(headers, 1):
            _cell(sheet, row_number, column, safe.get(header))
    if row_number == 1:
        for column in range(1, len(headers) + 1):
            _cell(sheet, 2, column, EMPTY if column == 1 else None)
        row_number = 2
    table = Table(
        displayName=f"EvidenceTable{len(book.worksheets)}",
        ref=f"A1:{get_column_letter(len(headers))}{row_number}",
    )
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showRowStripes=True, showColumnStripes=False,
    )
    sheet.add_table(table)
    sheet.auto_filter.ref = table.ref
    sheet.row_dimensions[1].height = 30
    return sheet


def _raw_rows(models: Iterable[BaseModel]) -> Iterable[dict[str, Any]]:
    for model in models:
        row = redact(model.model_dump(mode="json"))
        yield {**row, ORIGINAL: row}


def _missing_rows(data: Collection) -> Iterable[dict[str, Any]]:
    for agent in data.agents:
        fields = agent.model_dump(mode="json")
        missing = dict(agent.field_status)
        for field, value in fields.items():
            if value is None:
                missing.setdefault(field, None)
        if agent.usage_30d is not None:
            for field, value in agent.usage_30d.model_dump().items():
                if value is None:
                    missing.setdefault(f"usage_30d.{field}", None)
        for field, status in missing.items():
            yield {
                "agent_id": agent.agent_id,
                "subscription_id": agent.subscription_id,
                "필드명": FIELD_NAMES.get(field, field),
                "field": field,
                "reason": status.reason if status else "not_found",
                "설명": readable(status.detail) if status else
                "확인 자료 없음 - 원본 값이 null이며 별도 조회 상태 기록 없음",
                ORIGINAL: status.model_dump(mode="json") if status else None,
            }


def write_workbook(
    data: Collection, findings: list[Finding], path: Path, mode: str = "live",
) -> None:
    """Write a masked evidence snapshot, without formulas or external links."""
    book = Workbook()
    book.remove(book.active)
    counts = Counter(issue.reason for issue in data.issues)
    _table(book, "읽는법", ["항목", "설명"], [
        {"항목": "보고서 종류", "설명": "수집 시점의 실측 스냅샷 - 재계산 모델 아님"},
        {"항목": "수집 시각", "설명": data.collected_at.isoformat()},
        {"항목": "실행 모드", "설명": mode},
        {"항목": "누락과 0", "설명": "빈 셀은 원본 null - 확인 자료 없음. 숫자 0과 FALSE는 실측값"},
        {"항목": "판정", "설명": "판정 보류는 낮은 성숙도나 0으로 환산하지 않음"},
        {"항목": "수동 검토", "설명": "진단 체크리스트의 검토 상태와 메모만 수동 편집"},
        {"항목": "원본 JSON", "설명": "키 이름과 구조를 보존한 마스킹 원본 - 중첩 필드는 JSON"},
        {"항목": "증거 경로", "설명": "evidence:<id>는 ZIP data.json의 evidence[id]와 HTML 원본 JSON에 연결 "
         "- 누락 참조는 provenance.unattached_evidence에서 파일 확인불가로 표시 "
         "- 자동 하이퍼링크 및 외부 연결 없음"},
        {"항목": "수집 이슈", "설명": "실패 집계는 기록된 이슈 건수 - 리소스 수가 아님"},
        *({"항목": f"수집 실패 집계 - {readable(reason)}", "설명": count}
          for reason, count in sorted(counts.items())),
    ])
    checklist = _table(book, "진단 체크리스트", [
        "SE코드", "항목", "확인상태", "지표", "판정", "원인", "근거", "다음조치",
        "수동검토상태", "검토메모",
    ], [
        {
            "SE코드": finding.se_code,
            "항목": SE_NAMES.get(finding.se_code, finding.se_code),
            "확인상태": readable(finding.scope),
            "지표": metric(finding),
            "판정": readable(finding.level),
            "원인": readable(finding.reason) if finding.reason else "해당 없음",
            "근거": readable(finding.rationale),
            "다음조치": readable(finding.next_step),
            "수동검토상태": "미검토",
            "검토메모": None,
        } for finding in findings
    ])
    validation = DataValidation(
        type="list", formula1='"미검토,검토중,확인완료"', allow_blank=False,
    )
    validation.errorTitle = "검토 상태 확인"
    validation.error = "미검토, 검토중, 확인완료 중 선택하세요."
    validation.showErrorMessage = True
    validation.errorStyle = "stop"
    checklist.add_data_validation(validation)
    validation.add(f"I2:I{max(2, len(findings) + 1)}")
    sections = [
        ("Agent 원시데이터", AgentEvidence, data.agents),
        ("평가 원시데이터", EvaluationRun, data.evaluations),
        ("모델배포 원시데이터", ModelDeployment, data.deployments),
        ("비용 원시데이터", CostRecord, data.costs),
        ("로그 원시데이터", LogSetting, data.logs),
        ("보안 원시데이터", SecurityRecommendation, data.security),
        ("수집이슈 원시데이터", Issue, data.issues),
    ]
    for title, model, records in sections:
        _table(book, title, [*model.model_fields, ORIGINAL], _raw_rows(records))
    _table(book, "필드누락사유", [
        "agent_id", "subscription_id", "필드명", "field", "reason", "설명", ORIGINAL,
    ], _missing_rows(data))
    refs = []
    for title, _, records in [*sections, ("진단 체크리스트", Finding, findings)]:
        for index, record in enumerate(records, 1):
            raw = redact(record.model_dump(mode="json"))
            for ref in raw.get("evidence_refs", []):
                refs.append({
                    "원본 시트": title, "원본 행": index + 1,
                    "evidence_ref": ref,
                    "agent_id": raw.get("agent_id"),
                    "subscription_id": raw.get("subscription_id"),
                    "SE코드": raw.get("se_code"),
                })
    _table(book, "증거참조", [
        "원본 시트", "원본 행", "evidence_ref", "agent_id", "subscription_id", "SE코드",
    ], refs)
    metadata = data.model_dump(mode="json", exclude={
        "agents", "evaluations", "deployments", "costs", "logs", "security", "issues",
    })
    _table(book, "수집 메타데이터", ["필드", "값", ORIGINAL], [
        {"필드": key, "값": value, ORIGINAL: {key: value}}
        for key, value in redact(metadata).items()
    ])
    book.save(path)
