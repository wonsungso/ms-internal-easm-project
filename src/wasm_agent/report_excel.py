from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import BaseModel

from wasm_agent.azure import redact
from wasm_agent.models import (
    AgentEvidence,
    Budget,
    Collection,
    CostRecord,
    EntraAgentIdentity,
    EntraBlueprint,
    EvaluationRun,
    Finding,
    Issue,
    LogSetting,
    ModelDeployment,
    PolicyAssignment,
    ProposalFinding,
    ProposalObservation,
    SecureScore,
    SecurityRecommendation,
)
from wasm_agent.proposals import DOMAINS, TITLES

LABELS = {
    "permission_denied": "조회 권한 부족",
    "feature_unavailable": "현재 환경에서 조회 기능 제공 안 됨",
    "license_missing": "필요 라이선스 확인 또는 추가 필요",
    "not_found": "확인 자료 없음",
    "error": "조회 중 오류 발생",
    "in_scope": "진단 범위에 포함",
    "partial": "진단 범위 일부 - 조직 전체 판정 아님",
    "out_of_scope": "진단 범위 밖",
    "N/A": "판정 보류",
    "null": "확인 자료 없음",
    "foundry": "Microsoft Foundry",
    "langchain": "LangChain 탐지 후보",
    "manual": "수동 등록",
    "other": "기타 플랫폼",
    "tag": "태그를 근거로 탐지",
    "name_heuristic": "이름을 근거로 추정 - Agent 여부 추가 확인 필요",
}
SE_AREAS = {
    "DM": "1. Demand", "DS": "2. Design", "BI": "3. Build",
    "DP": "4. Deploy", "OE": "5. Operate", "OT": "6. Optimize",
}
SE_NAMES = {
    "DS-SY-06": "허용 모델 사용 관리",
    "BI-SY-08": "배포 전 Agent 품질 평가",
    "BI-SY-09": "AI 워크로드 보안 관리",
    "OE-SY-15": "Agent 활동 감사 로그 관리",
    "OT-SY-18": "장기 미사용 Agent 관리",
    "OT-SY-19": "Agent별 비용 식별 및 배분",
    "DS-SY-05": "Agent ID 템플릿(Blueprint) 정의",
    "DP-SY-12": "Agent ID 부여율(Azure Agent 기준)",
    "OE-SY-13": "소유자·후원자 미지정 Agent",
    "OE-SY-14": "Agent 부여 권한·과다 권한",
    **TITLES,
}
FIELD_NAMES = {
    "tenant_id": "테넌트", "subscription_id": "구독", "resource_group": "리소스 그룹",
    "agent_version": "Agent 버전", "resource_id": "리소스",
    "hosting_type": "호스팅 유형", "owner": "담당자", "sponsor": "업무 책임자",
    "model": "사용 모델", "model_version": "모델 버전", "model_resource_id": "모델 리소스",
    "tools": "연결 도구", "created_at": "생성 시각", "deployed_at": "배포 시각",
    "last_used_at": "마지막 사용 시각", "cost_30d": "최근 30일 비용", "currency": "통화",
    "usage_30d": "최근 30일 사용량", "usage_30d.calls": "최근 30일 호출 수",
    "usage_30d.tokens": "최근 30일 토큰 수", "calls_90d": "최근 90일 호출 수",
    "usage_coverage_start": "사용 관측 시작 시각",
    "evaluated_before_deploy": "배포 전 평가 여부", "guardrail_applied": "안전장치 적용 여부",
}
RATIOS = {"DS-SY-06", "BI-SY-08", "OT-SY-18", "OT-SY-19", "DP-SY-12", "OE-SY-13", "OE-SY-14"}
RATIOS.update(TITLES)
EMPTY = "수집된 데이터 없음 - 미수행 또는 0건으로 확정하지 않음"
ORIGINAL = "원본 JSON"
FONT_SIZE = 14
_SIDE = Side(style="thin", color="8C9BB0")
BORDER = Border(left=_SIDE, right=_SIDE, top=_SIDE, bottom=_SIDE)


def readable(value: Any) -> str:
    if value is None or value == "":
        return "확인 자료 없음"
    if isinstance(value, bool):
        return "확인됨" if value else "해당하지 않음"
    text = str(redact(value)).replace("\u2014", "-").replace("\u2013", "-")
    for key, label in LABELS.items():
        text = re.sub(r"(?<![\w/-])" + re.escape(key) + r"(?![\w/-])", label, text)
    return text


def metric(finding: Finding) -> str:
    if finding.metric_value is None:
        return "확인 자료 없음" + (" - 분모 확인 안됨" if finding.se_code in RATIOS else "")
    value = finding.metric_value
    if finding.se_code in RATIOS:
        return f"{value * 100:.2f}%"
    return f"{value:g}" + ("일" if finding.se_code == "OE-SY-15" else "건")


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
    cell.font = Font(name="Arial", size=FONT_SIZE, color="172B4D")
    cell.alignment = Alignment(vertical="top", wrap_text=True)
    cell.border = BORDER
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
        cell.font = Font(name="Arial", size=FONT_SIZE, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17365D")
        sheet.column_dimensions[get_column_letter(column)].width = (
            90 if header == ORIGINAL else
            68 if header in {"원인", "근거", "다음조치", "detail", "evidence_refs", "설명"} else 34
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
    sheet.row_dimensions[1].height = 40
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
    references: list[dict[str, Any]] | None = None,
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
        {"항목": "증거 경로", "설명": "evidence:<id>는 raw-data-<타임스탬프>.json의 evidence[id]에 연결 "
         "- 누락 참조는 provenance.unattached_evidence에서 파일 확인불가로 표시 "
         "- 자동 하이퍼링크 및 외부 연결 없음"},
        {"항목": "수집 이슈", "설명": "실패 집계는 기록된 이슈 건수 - 리소스 수가 아님"},
        *({"항목": f"수집 실패 집계 - {readable(reason)}", "설명": count}
          for reason, count in sorted(counts.items())),
    ])
    checklist = _table(book, "진단 체크리스트", [
        "SE코드", "진단 영역", "항목", "확인상태", "지표", "판정", "원인", "근거", "다음조치",
        "수동검토상태", "검토메모",
    ], [
        {
            "SE코드": finding.se_code,
            "진단 영역": SE_AREAS.get(finding.se_code[:2], ""),
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
    validation.add(f"J2:J{max(2, len(findings) + 1)}")
    _table(book, "추가 제안 현황", ["코드", "진단 영역", "제안", "수집 상태", "원인", "수집 요약", "지표", "한계", "evidence_refs"], [
        {
            "코드": item.code, "진단 영역": item.area or DOMAINS.get(item.code, ("",))[0],
            "제안": item.title, "수집 상태": item.status,
            "원인": readable(item.reason) if item.reason else "해당 없음",
            "수집 요약": readable(item.observation), "지표": item.metrics, "한계": item.limit,
            "evidence_refs": item.evidence_refs,
        } for item in data.proposals
    ])
    sections = [
        ("Agent Raw 데이터", AgentEvidence, data.agents),
        ("제안 Raw 데이터", ProposalObservation, data.proposal_observations),
        ("평가 Raw 데이터", EvaluationRun, data.evaluations),
        ("모델배포 Raw 데이터", ModelDeployment, data.deployments),
        ("비용 Raw 데이터", CostRecord, data.costs),
        ("로그 Raw 데이터", LogSetting, data.logs),
        ("보안 Raw 데이터", SecurityRecommendation, data.security),
        ("보안점수 Raw 데이터", SecureScore, data.secure_scores),
        ("정책할당 Raw 데이터", PolicyAssignment, data.policy_assignments),
        ("예산 Raw 데이터", Budget, data.budgets),
        ("Blueprint Raw 데이터", EntraBlueprint, data.entra_blueprints),
        ("AgentID Raw 데이터", EntraAgentIdentity, data.entra_agent_identities),
        ("수집이슈 Raw 데이터", Issue, data.issues),
    ]
    for title, model, records in sections:
        _table(book, title, [*model.model_fields, ORIGINAL], _raw_rows(records))
    _table(book, "필드누락사유", [
        "agent_id", "subscription_id", "필드명", "field", "reason", "설명", ORIGINAL,
    ], _missing_rows(data))
    refs = []
    for title, _, records in [
        *sections, ("진단 체크리스트", Finding, findings), ("추가 제안 현황", ProposalFinding, data.proposals),
    ]:
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
    _table(book, "증거 첨부 상태", ["id", "reference", "status", "detail"], [
        {
            "id": item.get("id"), "reference": item.get("reference"), "status": item.get("status"),
            "detail": readable(item.get("detail")) if item.get("detail") else "raw-data JSON에 첨부됨",
        } for item in references or []
    ])
    metadata = data.model_dump(mode="json", exclude={
        "agents", "evaluations", "deployments", "costs", "logs", "security", "issues",
        "proposals", "proposal_observations",
    })
    _table(book, "수집 메타데이터", ["필드", "값", ORIGINAL], [
        {"필드": key, "값": value, ORIGINAL: {key: value}}
        for key, value in redact(metadata).items()
    ])
    book.save(path)
