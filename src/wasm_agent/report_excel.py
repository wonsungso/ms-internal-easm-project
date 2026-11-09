from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from copy import copy, deepcopy
from pathlib import Path
from typing import Any, TypedDict

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.hyperlink import Hyperlink
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
    ProposalObservation,
    SecureScore,
    SecurityRecommendation,
)
from wasm_agent.proposals import DOMAINS, TITLES, azure_agents
from wasm_agent.report_template import (
    CRITERIA_SHEET,
    RESULT_SHEET,
    load_report_template,
    preserve_template_parts,
)

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
    "DS-SY-06": "모델 배포 버전·업데이트 구성",
    "BI-SY-11": "Foundry 프로젝트 평가 실행 이력",
    "BI-SY-12": "AI 리소스 보안 권고 상태",
    "OE-SY-22": "Agent 리소스 실행 로그 연결",
    "OT-SY-28": "AI 리소스 사용량 관측 범위",
    "OT-SY-29": "AI 비용의 단일 Agent 귀속",
    "DS-SY-05": "Agent ID의 Blueprint 연결",
    "DP-SY-19": "Agent ID 부여율(Azure Agent 기준)",
    "OE-SY-20": "소유자·후원자 미지정 Agent",
    "OE-SY-21": "Agent 부여 권한·과다 권한",
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
RATIOS = set(SE_NAMES)
EMPTY = "수집된 데이터 없음 - 미수행 또는 0건으로 확정하지 않음"
ORIGINAL = "원본 JSON"
FONT_SIZE = 10
HEADER_FILL = "D9D9D9"
EVIDENCE_FILL = "EAF3FB"
_SIDE = Side(style="thin", color="000000")
_OUTER = Side(style="medium", color="000000")
BORDER = Border(left=_SIDE, right=_SIDE, top=_SIDE, bottom=_SIDE)
COLUMN_WIDTHS = {
    "SE코드": 10, "코드": 10, "진단 영역": 9, "항목": 19, "제안": 19,
    "확인상태": 10, "수집 상태": 10, "지표": 12, "판정": 7, "원인": 11,
    "근거": 27, "다음조치": 19, "수동검토상태": 10, "검토메모": 15,
    "수집 요약": 42, "한계": 38, "설명": 60, "detail": 40,
    "evidence_refs": 32, ORIGINAL: 48,
}
CENTERED = {"SE코드", "코드", "진단 영역", "확인상태", "수집 상태", "지표", "판정", "수동검토상태"}
DETAILS_TITLE = "수집결과 근거"
RAW_TITLE = "수집 Raw 데이터"


class ReviewLayout(TypedDict):
    widths: tuple[float, ...]
    height: float
    default_height: float
    default_width: float


REVIEW_LAYOUTS: dict[str, ReviewLayout] = {
    DETAILS_TITLE: {
        "widths": (10.625, 14.875, 25.5, 14.875, 10.625, 90.375, 53.125, 90.375, 65.125),
        "height": 60, "default_height": 60, "default_width": 109.625,
    },
}


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
    if finding.assessment_basis == "configuration":
        if finding.configuration_value is None:
            raise ValueError(f"{finding.se_code}: 구성 기반 등급의 관측 건수가 없습니다.")
        return f"기본 구성 {finding.configuration_value:g}건"
    if finding.metric_value is None:
        return "확인 자료 없음" + (" - 분모 확인 안됨" if finding.se_code in RATIOS else "")
    value = finding.metric_value
    if finding.se_code in RATIOS:
        return f"{value * 100:.2f}%"
    return f"{value:g}" + ("일" if finding.se_code == "OE-SY-22" else "건")


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
    cell.font = Font(name="Arial", size=FONT_SIZE, color="000000")
    cell.alignment = Alignment(vertical="center", wrap_text=True)
    cell.border = BORDER
    cell.hyperlink = None


def _table(
    book: Workbook, title: str, headers: list[str], rows: Iterable[dict[str, Any]],
    *, sheet: Worksheet | None = None, start_row: int = 1,
) -> Worksheet:
    if sheet is None:
        sheet = book.create_sheet(f"{len(book.worksheets) + 1}. {title}")
    layout = REVIEW_LAYOUTS.get(title)
    if sheet.freeze_panes is None:
        sheet.freeze_panes = f"A{start_row + 1}"
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = 80
    sheet.sheet_format.defaultRowHeight = layout["default_height"] if layout else 15
    if layout:
        sheet.sheet_format.defaultColWidth = layout["default_width"]
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    for column, header in enumerate(headers, 1):
        _cell(sheet, start_row, column, header)
        cell = sheet.cell(start_row, column)
        cell.font = Font(name="Arial", size=FONT_SIZE, bold=True, color="000000")
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        width = (
            layout["widths"][column - 1] if layout else COLUMN_WIDTHS.get(header, 18)
        )
        key = get_column_letter(column)
        previous = sheet.column_dimensions[key].width if key in sheet.column_dimensions else 0
        sheet.column_dimensions[key].width = max(previous, width)
    row_number = start_row
    for row_number, row in enumerate(rows, start_row + 1):
        safe = redact(row)
        for column, header in enumerate(headers, 1):
            _cell(sheet, row_number, column, safe.get(header))
            cell = sheet.cell(row_number, column)
            cell.fill = PatternFill() if layout else PatternFill(
                "solid", fgColor=EVIDENCE_FILL if (row_number - start_row) % 2 else "FFFFFF",
            )
            if layout:
                cell.alignment = Alignment(
                    horizontal="center" if column <= 2 else "left", vertical="center", wrap_text=True,
                )
            elif header in CENTERED:
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.row_dimensions[row_number].height = layout["height"] if layout else 33.75
    if row_number == start_row:
        for column in range(1, len(headers) + 1):
            _cell(sheet, start_row + 1, column, EMPTY if column == 1 else None)
        row_number = start_row + 1
        sheet.row_dimensions[row_number].height = layout["height"] if layout else 33.75
    for row in sheet.iter_rows(min_row=start_row, max_row=row_number, max_col=len(headers)):
        for cell in row:
            if title == DETAILS_TITLE and cell.row > start_row:
                cell.border = BORDER
                continue
            cell.border = Border(
                left=_OUTER if cell.column == 1 else _SIDE,
                right=_OUTER if cell.column == len(headers) and title != DETAILS_TITLE else _SIDE,
                top=_OUTER if cell.row == start_row else _SIDE,
                bottom=_OUTER if cell.row == row_number else _SIDE,
            )
    table = Table(
        displayName=f"EvidenceTable{book.worksheets.index(sheet) + 1}_{len(sheet.tables) + 1}",
        ref=f"A{start_row}:{get_column_letter(len(headers))}{row_number}",
    )
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleLight1", showRowStripes=False, showColumnStripes=False,
    )
    sheet.add_table(table)
    sheet.row_dimensions[start_row].height = 16.5 if layout else 33
    if sheet.print_title_rows is None:
        sheet.print_title_rows = f"{start_row}:{start_row}"
    sheet.print_options.horizontalCentered = True
    return sheet


def collection_summary(data: Collection, finding: Finding) -> tuple[str, str | None]:
    agents = azure_agents(data)
    proposal = next((item for item in data.proposals if item.code == finding.se_code), None)
    if proposal is not None:
        return proposal.status, proposal.observation
    code = finding.se_code
    summary = None
    if code == "DS-SY-06" and (data.deployments or data.facts.get("deployment_inventory_complete")):
        summary = f"모델 배포 {len(data.deployments)}개"
    elif code == "BI-SY-11" and (data.evaluations or data.facts.get("evaluation_complete_projects")):
        summary = f"평가 실행 {len(data.evaluations)}건, Azure Agent {len(agents)}개"
    elif code == "BI-SY-12" and (data.security or data.secure_scores):
        summary = f"보안 권고 {len(data.security)}건, 구독 보안 점수 {len(data.secure_scores)}건"
    elif code == "OE-SY-22" and data.logs:
        retention = [item.retention_days for item in data.logs if item.retention_days is not None]
        scope = "Agent 실행 로그" if data.facts.get("audit_log_scope") == "agent_resource_execution" else "진단 로그"
        summary = (
            f"{scope} 대상 {len(data.logs)}개, 활성 {sum(item.enabled for item in data.logs)}개"
            + (f", 확인한 최소 보존 {min(retention)}일" if retention else ", 보존기간 미확보")
        )
    elif code == "OT-SY-28" and agents:
        summary = f"Azure Agent {len(agents)}개 중 최근 사용일 확인 {sum(item.last_used_at is not None for item in agents)}개"
    elif code == "OT-SY-29" and (data.costs or data.budgets):
        summary = f"비용 행 {len(data.costs)}건, 예산 {len(data.budgets)}개"
    elif code == "DS-SY-05" and data.facts.get("entra_blueprints_complete"):
        summary = f"Blueprint {len(data.entra_blueprints)}개"
    elif code in ("DP-SY-19", "OE-SY-20", "OE-SY-21") and (
        data.entra_agent_identities or data.facts.get("entra_agents_complete")
    ):
        summary = f"Graph Agent ID {len(data.entra_agent_identities)}개, Azure Agent {len(agents)}개"
    if finding.reason in ("permission_denied", "error", "license_missing", "feature_unavailable"):
        return ("일부 수집" if summary else "수집 불가"), summary
    return ("수집됨" if summary else "증적 확인" if finding.metric_value is not None else "자료 미확보"), summary


def _raw_rows(models: Iterable[BaseModel]) -> Iterable[dict[str, Any]]:
    for model in models:
        row = redact(model.model_dump(mode="json"))
        yield {**row, ORIGINAL: row}


def _raw_sheet(
    book: Workbook, sections: Iterable[tuple[str, type[BaseModel], Sequence[BaseModel]]],
) -> None:
    sheet = book.create_sheet(f"{len(book.worksheets) + 1}. {RAW_TITLE}")
    sheet.freeze_panes = "A3"
    row = 1
    for title, model, records in sections:
        label = "구성 관측" if title == "제안 Raw 데이터" else title.removesuffix(" Raw 데이터")
        count = f"{len(records)}개 레코드" if records else "확보된 레코드 없음"
        _cell(sheet, row, 1, f"{label} - {count}")
        sheet.cell(row, 1).font = Font(name="Arial", size=FONT_SIZE, bold=True, color="000000")
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(model.model_fields) + 1)
        sheet.row_dimensions[row].height = 24
        _table(book, RAW_TITLE, [*model.model_fields, ORIGINAL], _raw_rows(records),
               sheet=sheet, start_row=row + 1)
        row += max(1, len(records)) + 4


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


def _result_sheet(book: Workbook, data: Collection, findings: list[Finding]) -> dict[str, int]:
    source = book[CRITERIA_SHEET]
    sheet = book.copy_worksheet(source)
    sheet.title = RESULT_SHEET
    for merged in list(sheet.merged_cells.ranges):
        if merged.max_col > 9:
            sheet.unmerge_cells(str(merged))
            sheet.merge_cells(
                start_row=merged.min_row, end_row=merged.max_row,
                start_column=merged.min_col, end_column=merged.max_col - 1,
            )
    sheet.delete_cols(10)
    sheet.views = deepcopy(source.views)
    sheet.sheet_view.tabSelected = True
    sheet.freeze_panes = "G5"
    sheet.auto_filter.ref = f"B4:M{source.max_row}"
    sheet.print_title_rows = "1:4"
    headers = ("확인상태", "지표", "판정", "근거", "다음조치", source.cell(4, 13).value, "검토메모")
    for column, header in enumerate(headers, 7):
        sheet.cell(4, column, header)
    sheet.cell(4, 12)._style = copy(source.cell(4, 13)._style)
    header_font = copy(sheet.cell(4, 9).font)
    header_font.bold = True
    sheet.cell(4, 9).font = header_font
    by_code = {finding.se_code: finding for finding in findings}
    if len(by_code) != len(findings):
        raise ValueError("수집 결과의 SE 코드가 중복되었습니다.")
    rows = {}
    for number in range(5, source.max_row + 1):
        code = source.cell(number, 2).value
        for column in range(7, 14):
            sheet.cell(number, column).value = None
        if not code:
            continue
        finding = by_code.get(str(code))
        if finding is None:
            values = (
                "수집하지 않음" if "-SY-" in str(code) else "인터뷰 필요",
                None, None,
                "자동 수집 결과 없음 또는 자동 수집 범위 밖 - 수동 확인 필요"
                if "-SY-" in str(code) else "인터뷰를 통해 확인하는 수동 심사 항목",
                None, None, None,
            )
        else:
            rows[finding.se_code] = number
            status, summary = collection_summary(data, finding)
            level_text = readable(finding.level)
            if finding.level != "N/A":
                legacy_grade = data.facts.get("assessment_revision") is not None and not data.facts.get("grading_profile")
                criterion = finding.level_criterion or (
                    "수집 당시 기준의 등급 - 원본 JSON 판정 근거 참조" if legacy_grade else
                    source.cell(number, 6 + int(finding.level[1:])).value
                )
                if not isinstance(criterion, str) or not criterion.strip():
                    raise ValueError(f"{finding.se_code}: {finding.level} 평가기준 문장이 없습니다.")
                level_text = f"Level {finding.level[1:]} ({criterion})"
            values = (
                "수집됨" if status in ("수집됨", "일부 수집", "증적 확인")
                else "수집하지 않음",
                metric(finding) if finding.assessment_basis == "configuration" or finding.metric_value is not None
                or not summary else "실측 구성 - 근거 참조",
                level_text,
                ("수집 결과: " + readable(summary) + "\n" if summary else "")
                + ("조회 제한: " + readable(finding.reason) + " (" + status + ")\n" if finding.reason else "")
                + "판정 근거: " + readable(finding.rationale),
                readable(finding.next_step),
                int(finding.level[1:]) if finding.level != "N/A"
                and status in ("수집됨", "일부 수집", "증적 확인") else None,
                None,
            )
        for column, value in enumerate(values, 7):
            style = copy(source.cell(number, column + (column >= 10))._style)
            _cell(sheet, number, column, value)
            sheet.cell(number, column)._style = style
        if finding is not None and finding.level != "N/A":
            label = f"Level {finding.level[1:]}"
            sheet.cell(number, 9).value = CellRichText(
                TextBlock(InlineFont(b=True), label), level_text[len(label):],
            )
            if finding.level != "L5" and not (
                data.facts.get("assessment_revision") is not None and not data.facts.get("grading_profile")
            ):
                next_level = int(finding.level[1:]) + 1
                condition = source.cell(number, 6 + next_level).value
                if not isinstance(condition, str) or not condition.strip():
                    raise ValueError(f"{finding.se_code}: L{next_level} 평가기준 문장이 없습니다.")
                sheet.cell(number, 11).value = CellRichText(
                    TextBlock(InlineFont(b=True), f"Level {next_level}"), ": " + condition,
                )
        evidence = sheet.cell(number, 10)
        if finding is not None and isinstance(evidence.value, str):
            rationale = readable(finding.rationale)
            prefix = evidence.value[:-(len("판정 근거: ") + len(rationale))]
            content = CellRichText()
            if prefix.startswith("수집 결과:"):
                content.append(TextBlock(InlineFont(b=True), "수집 결과:"))
                prefix = prefix[len("수집 결과:"):]
            if prefix:
                content.append(prefix)
            content.append(TextBlock(InlineFont(b=True), "판정 근거:"))
            content.append(" " + rationale)
            evidence.value = content
        sheet.cell(number, 12).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        if sheet.cell(number, 7).value == "수집됨":
            sheet.row_dimensions[number].height = 110
    sheet.cell(4, 12).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    if rows.keys() != by_code.keys():
        raise ValueError("평가 결과 템플릿에 없는 SE 코드가 수집 결과에 포함되었습니다.")
    for column, width in enumerate((16, 25, 55, 90, 60, 18, 30), 7):
        sheet.column_dimensions[get_column_letter(column)].width = width
    if "N" in sheet.column_dimensions:
        del sheet.column_dimensions["N"]
    validation = DataValidation(
        type="whole", operator="between", formula1="1", formula2="5", allow_blank=True,
    )
    validation.errorTitle = "평가 점수 확인"
    validation.error = "1~5 정수만 입력하세요. 판정이 없는 항목은 빈칸으로 유지하세요."
    validation.showErrorMessage = True
    validation.errorStyle = "stop"
    sheet.add_data_validation(validation)
    validation.add(f"L5:L{source.max_row}")
    book.active = sheet
    return rows


def write_workbook(
    data: Collection, findings: list[Finding], path: Path, mode: str = "live",
    references: list[dict[str, Any]] | None = None,
) -> None:
    """Extend the assessment template with a masked collected-evidence snapshot."""
    book, template = load_report_template()
    result_rows = _result_sheet(book, data, findings)
    details = [
        {
            "SE 코드": item.code, "진단 영역": item.area or DOMAINS.get(item.code, ("",))[0],
            "점검 항목": item.title, "조회 상태": item.status,
            "조회 제한 사유": readable(item.reason) if item.reason else "해당 없음",
            "수집 구성 요약": readable(item.observation), "구성 값·건수": item.metrics, "검증 한계": item.limit,
            "증적 ID": item.evidence_refs,
        } for item in data.proposals
    ]
    codes = {item["SE 코드"] for item in details}
    if len(codes) != len(details):
        raise ValueError("수집결과 근거의 SE 코드가 중복되었습니다.")
    for finding in findings:
        if finding.se_code in codes:
            continue
        status, summary = collection_summary(data, finding)
        details.append({
            "SE 코드": finding.se_code, "진단 영역": SE_AREAS.get(finding.se_code[:2], ""),
            "점검 항목": SE_NAMES.get(finding.se_code, finding.se_code), "조회 상태": status,
            "조회 제한 사유": readable(finding.reason) if finding.reason else "해당 없음",
            "수집 구성 요약": readable(summary),
            "구성 값·건수": {
                "metric_value": finding.metric_value, "assessment_basis": finding.assessment_basis,
                "configuration_value": finding.configuration_value,
            },
            "검증 한계": readable(finding.scope) + ". 등급별 승인·기간·집행 검증은 6번 판정 근거 확인",
            "증적 ID": finding.evidence_refs,
        })
    details.sort(key=lambda item: result_rows.get(item["SE 코드"], float("inf")))
    proposals_sheet = _table(book, DETAILS_TITLE, [
        "SE 코드", "진단 영역", "점검 항목", "조회 상태", "조회 제한 사유",
        "수집 구성 요약", "구성 값·건수", "검증 한계", "증적 ID",
    ], details, start_row=3)
    for row, item in enumerate(details, 4):
        code = item["SE 코드"]
        if code not in result_rows:
            continue
        cell = book[RESULT_SHEET].cell(result_rows[code], 10)
        text = str(cell.value) + "\n수집결과"
        if len(text) > 32767:
            raise ValueError(f"Excel 셀 길이 오류: {RESULT_SHEET}!{cell.coordinate} - {len(text)}자, 최대 32767자")
        content = cell.value if isinstance(cell.value, CellRichText) else CellRichText(str(cell.value))
        # Excel rejects a separate whitespace-only run before this link label.
        content.append(TextBlock(InlineFont(
            rFont=cell.font.name, sz=cell.font.sz, color="FF0563C1", u="single",
        ), "\n수집결과"))
        cell.value = content
        cell.hyperlink = Hyperlink(
            ref=cell.coordinate, location=f"'{proposals_sheet.title}'!A{row}",
            display="수집결과", tooltip=f"{code} 수집결과 근거로 이동",
        )
    _cell(proposals_sheet, 1, 1, "수집된 설정·값·건수와 검증 한계. 다음조치는 6. 수집 결과의 K열 확인")
    proposals_sheet.merge_cells("A1:I1")
    proposals_sheet.row_dimensions[1].height = 30
    proposals_sheet.print_title_rows = "1:3"
    explanations = (
        "6. 수집 결과와 연결되는 System Evidence 항목 코드",
        "항목이 속한 진단 영역", "조회한 Azure 구성 점검 항목의 이름",
        "실제 조회 상태. 등급이나 개선 필요 여부를 뜻하지 않음",
        "권한·기능·대상 없음 등 조회를 제한한 사유",
        "실제 조회된 설정과 건수를 읽기 쉽게 요약한 값",
        "원본 키를 유지한 구성 값·건수. 승인 충족률이나 효과 검증 결과가 아님",
        "구성 조회만으로 입증할 수 없는 승인·집행 효과·운영 절차",
        "원본 JSON evidence에 첨부된 마스킹 증적 ID 또는 확인이 필요한 참조",
    )
    for column, explanation in enumerate(explanations, 1):
        proposals_sheet.cell(3, column).comment = Comment(explanation, "WASM Agent")
    sections: list[tuple[str, type[BaseModel], Sequence[BaseModel]]] = [
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
    ]
    _raw_sheet(book, sections)
    issue_title = "수집이슈 Raw 데이터"
    _table(book, issue_title, [*Issue.model_fields, ORIGINAL], _raw_rows(data.issues))
    _table(book, "필드누락사유", [
        "agent_id", "subscription_id", "필드명", "field", "reason", "설명", ORIGINAL,
    ], _missing_rows(data))
    book.save(path)
    preserve_template_parts(path, template)
