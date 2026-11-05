"""원본 ZIP 파트를 보존하며 SY 목록과 승인 전 제안을 별도 시트로 추가한다."""

from __future__ import annotations

import argparse
import hashlib
import re
from copy import copy, deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from wasm_agent.proposals import DOMAINS

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHEET = "4. 질문별 평가 기준"
SY_SHEET = "SY 질문 전체"
PROPOSAL_SHEET = "Azure 운영 추가 제안"
STATE = "추가 제안 - 승인 전, Azure 구성 사실 수집만 구현(Level 미판정)"
CHECKED = "2026-11-04"
CAF = (
    "https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/"
    "ai-agents/governance-security-across-organization"
)
MONITOR = (
    "https://learn.microsoft.com/en-us/azure/foundry/observability/"
    "how-to/how-to-monitor-agents-dashboard"
)
APP = "https://learn.microsoft.com/en-us/azure/foundry-classic/how-to/monitor-applications"
COST = "https://learn.microsoft.com/en-us/azure/foundry-classic/how-to/costs-plan-manage"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ET.register_namespace("", NS)
ET.register_namespace("r", DOC_REL)

# 질문, 보완 대상, 차이, 증적, Reader 한계, 공식 절, 보조 문서/절
PROPOSALS = [
    (
        "Azure/Foundry Agent별 책임 조직, 업무 목적, 런타임, 배포 및 접근 범위를 "
        "승인된 인벤토리와 대사하고 변경 시 갱신하는가?",
        "DM-SY-03, DP-SY-10, OE-SY-13",
        "Azure 운영 자산 대사 추가. M365 Registry, Entra Agent ID 및 퇴사자 확인을 대체하지 않음.",
        "비식별 자산 대장, 책임 조직 코드, 목적, 런타임/배포 참조, 승인 및 변경 이력",
        "ARM Reader는 리소스/태그의 부분 정보만 확인. Agent 실체, 업무 목적과 책임은 별도 승인 자료 필요.",
        "2.1 AI agent control plane - 1, 2, 5",
        "", "",
    ),
    (
        "Azure Agent 워크로드가 관리 ID로 인증하고 ARM 역할의 권한과 할당 범위를 "
        "업무상 최소 권한 기준으로 정기 검토하는가?",
        "DP-SY-12, OE-SY-14, OE-SY-15",
        "ARM 관리 ID 연결과 RBAC만 보완. Entra Agent ID, Graph API 권한, 조건부 접근 진단 아님.",
        "관리 ID 연결 설정, ARM 역할 정의/할당 범위, 예외 만료일, 최소 권한 검토 승인",
        "권한이 허용된 ARM 설정만 조회 가능. ID 연결이 실제 인증 사용을 입증하지 않으며 "
        "토큰, 비밀, Graph 및 데이터 평면 유효 권한은 조회하지 않음.",
        "2.3 Agent security - 6, 7",
        "", "",
    ),
    (
        "내부/외부 Agent와 데이터의 네트워크 경계 및 외부 송신 경로를 승인하고 "
        "우회 경로를 시험하는가?",
        "DS-SY-04, BI-SY-07",
        "Azure 랜딩 존과 네트워크 경계의 신규 보완. Power Platform DLP/관리형 환경 평가 대체 아님.",
        "데이터 흐름도, 공용 접근/Private Endpoint 설정, 송신 허용 목록, 경로 검증 결과",
        "ARM 네트워크 구성은 부분 조회 가능. Reader만으로 실제 연결 차단이나 앱 내부 우회 방지 입증 불가.",
        "2.2.2 Corporate compliance - 1, 2; 2.3 - 3; 3. Prepare environment - 2",
        "", "",
    ),
    (
        "모든 대상 배포와 입력/출력 경로에 승인된 Content Safety 정책이 연결되는지 확인하고 "
        "필터 적용 범위와 실제 방어 효과를 구분해 검증하는가?",
        "DS-SY-06, BI-SY-08, BI-SY-09",
        "모델 허용 목록/평가 이력 외 안전 정책 연결 누락을 보완. 설정 존재를 방어 효과로 간주하지 않음.",
        "배포-정책 대조표, 정책 버전, 예외 승인, 입력/출력 시험 결과와 한계",
        "ARM에 노출된 배포/정책 설정만 부분 확인. 데이터 평면 정책과 효과 시험에는 별도 권한/제출 증적 필요.",
        "2.3 Agent security - 4, 5",
        "", "",
    ),
    (
        "출시 및 중요 변경 전에 프롬프트 주입, 정보 유출, 도구 오용에 대한 적대적 시험을 수행하고 "
        "승인된 릴리스 게이트로 결함 조치를 확인하는가?",
        "BI-SY-08",
        "일반 평가 수행률에 공격 시나리오, 버전별 조치 및 배포 승인 증거를 보완.",
        "버전별 red team 보고서, 시나리오 범위, 결함/예외 승인, CI 게이트 실행 이력",
        "Reader는 CI 승인, 시험 원문/결과와 배포 차단을 보장하지 않음. "
        "기존 결과를 승인 자료로 제출하며 이 도구는 시험/배포를 실행하지 않음.",
        "2.3 Agent security - 4",
        MONITOR, "View agent metrics (preview); Understand the dashboard metrics",
    ),
    (
        "Agent-모델-도구 호출의 추적 연계를 확보하고 오류, 지연, 성공률, 토큰 사용을 "
        "승인된 SLO와 연결해 탐지 및 대응하는가?",
        "BI-SY-08, OE-SY-16, OT-SY-18",
        "평가/감사 보관/활성도 외 운영 품질과 도구 호출 관측을 보완. SLO 수치는 조직 승인 필요.",
        "비식별 trace 연계 예시, 도구 오류/지연 대시보드, SLO 승인, 경보와 대응 이력",
        "ARM Reader는 Insights 연결/경보 구성 일부만 확인. 로그 권한, 계측 및 샘플링 확인 필요. "
        "보호 테이블 추가 권한이 필요할 수 있고 무기록을 무오류로 판단하지 않음.",
        "2.1 AI agent control plane - 5; 2.3 - 8",
        MONITOR, "Prerequisites; Understand the dashboard metrics",
    ),
    (
        "고위험 도구 실행에 사람의 승인, 실행 범위 제한과 실패 시 중단 경로를 두고 "
        "승인 우회 방지 및 실행 주체 귀속을 검증하는가?",
        "OE-SY-14, BI-SY-08",
        "ARM 역할 외 앱 수준 실행 통제 보완. 사람 승인 게이트는 최소 권한 원칙을 구체화한 제안.",
        "위험-도구 분류표, 승인자 역할, 실행 전 승인/거부 테스트, 비식별 승인-실행 상관 기록",
        "앱 내부 승인/도구 스코프는 ARM Reader로 입증 불가. 설계 검토 및 승인된 시험 증적 필요.",
        "2.2.2 Corporate compliance - 5; 2.3 - 7, 9",
        "", "",
    ),
    (
        "외부 MCP/A2A 상대와 도구 엔드포인트를 승인 목록으로 제한하고 "
        "인증, 데이터 전달 범위, 변경 및 예외를 검토하는가?",
        "DS-SY-04, OE-SY-14",
        "Power Platform 커넥터와 구분된 Azure 앱 통합 경계 신규 보완.",
        "비식별 엔드포인트 대장, 프로토콜/인증 방식, 데이터 범위, 허용/거부 검증과 변경 승인",
        "ARM 네트워크 구성은 보조 증거. 앱 내부 MCP/A2A 연결, 신뢰 및 프로토콜 준수는 별도 자료 필요.",
        "2.3 Agent security - 9; 2.4 Agent development standards - 2",
        "", "",
    ),
    (
        "Agent 보안/운영 경보를 SOC로 전달하고 담당자 호출, 안전한 비활성화, "
        "이전 승인 버전 복구 및 증거 보존을 모의 훈련하는가?",
        "BI-SY-09, OE-SY-16",
        "권고/로그 보관 외 사고 대응 실행 가능성을 보완. 비활성화와 롤백은 훈련 제안이며 자동 실행하지 않음.",
        "경보-대응자 매핑, 전달 시험, 사고 대응서, 중단/롤백 훈련 기록, 로그 보존 절차",
        "ARM 경보/작업 그룹 설정은 부분 확인. SOC 수신, 복구 성공, 훈련은 Reader만으로 입증 불가.",
        "2.3 Agent security - 8, 10",
        "", "",
    ),
    (
        "Agent/업무 단위 비용과 예측을 승인된 예산 및 경보 조건에 연결하고 "
        "통보 후 대응 책임과 예외를 검토하는가?",
        "OT-SY-19",
        "원 비용 항목의 예측 통제 증적을 구체화. 별도 L 레벨이나 예산 임계값을 추가하지 않음.",
        "비용 배분 근거, 예산/예측 경보 설정, 통보 및 조치 이력, 승인된 예외",
        "Cost Management의 계정/청구 범위 접근 조건 적용. Reader만으로 모든 청구 데이터를 보장하지 않으며 "
        "공유 자원 비용은 Agent별 직접 귀속이 불가할 수 있음.",
        "2.1 AI agent control plane - 6",
        COST, "Prerequisites; Plan and manage costs - hub projects 범위",
    ),
    (
        "Agent 런타임, 원천 데이터, 메모리, 로그 및 출력 저장소의 지역과 "
        "보존/삭제 책임을 추적하고 개인정보 최소 수집을 검증하는가?",
        "OE-SY-16, OT-SY-20",
        "Azure 데이터 흐름/메모리 수명 주기 보완. Purview Audit/DSPM 원 항목을 대체하지 않음.",
        "비식별 지역/데이터 흐름 대장, 메모리/로그 보존 정책, 삭제 검증, 개인정보 마스킹 검토",
        "ARM location/노출된 보존 설정은 부분 정보. 실제 처리 지역, 앱 메모리, 삭제 완료 및 "
        "Purview 정책은 Reader만으로 입증 불가.",
        "2.2.1 Regulatory compliance - 1, 2, 3",
        APP, "Collect production data for monitoring; Viewing monitoring results",
    ),
    (
        "승인된 Azure 정책과 랜딩 존 기준을 Agent 자원에 적용하고 "
        "준수 상태, 예외 만료 및 변경 후 편차를 검토하는가?",
        "DS-SY-06, BI-SY-09",
        "모델 정책과 보안 권고를 넘어 네트워크/지역/진단 등 인프라 기준을 보완.",
        "정책 할당/정의, 준수 결과, 예외 및 만료 승인, 편차 검토 기록",
        "허용된 ARM 정책/준수 정보는 읽기 가능. 정책 준수는 앱 동작/모델 안전을 보장하지 않으며 "
        "이 스크립트는 정책을 배포하거나 수정하지 않음.",
        "2.2.2 Corporate compliance - Microsoft facilitation; 3. Prepare environment - 2",
        "", "",
    ),
    (
        "승인된 SDK/프로토콜과 모델, 프롬프트, 도구, 정책 버전을 릴리스에 연결하고 "
        "출처 및 변경 승인과 재현 가능한 복구 지점을 유지하는가?",
        "DS-SY-06, BI-SY-08",
        "모델 버전 대조를 SDK/프롬프트/도구/정책 출처 추적으로 확대하는 제안.",
        "릴리스 명세, 패키지 잠금/이미지 다이제스트, 모델/프롬프트/도구/정책 버전, 승인/복구 참조",
        "ARM 배포 메타데이터는 일부만 제공. 소스/빌드 출처와 SDK 승인 여부는 "
        "CI 및 구성 관리 증적 필요. 비밀/연결 문자열은 수집하지 않음.",
        "2.4 Agent development standards - 1, 2; 2.3 - 10",
        "", "",
    ),
]


def read_contracts(notes: Path, criteria: Path) -> tuple[dict[str, dict[str, str]], set[str]]:
    text = notes.read_text(encoding="utf-8").split("## 원본 및 변환 범위")[0]
    contracts: dict[str, dict[str, str]] = {}
    for code, block in re.findall(
        r"- \*\*([A-Z]{2}-SY-\d{2})\*\*\s*(.*?)(?=- \*\*|\Z)", text, re.S
    ):
        fields = {}
        for label in ("유형", "scope", "분류 근거", "측정방법"):
            match = re.search(rf"^  - {label}: (.+)$", block, re.M)
            if not match:
                raise ValueError(f"api-notes 필드 누락: {code} / {label}")
            fields[label] = match[1]
        contracts[code] = fields
    implemented = set(re.findall(
        r"^  ([A-Z]{2}-SY-\d{2}):$", criteria.read_text(encoding="utf-8"), re.M
    ))
    if len(contracts) != 20 or len(implemented) != 11 or not implemented <= contracts.keys():
        raise ValueError("api-notes 20개 / criteria 11개 계약이 일치하지 않습니다.")
    if any((v["scope"] != "out_of_scope") != (k in implemented)
           for k, v in contracts.items()):
        raise ValueError("scope와 구현 기준 코드가 일치하지 않습니다.")
    return contracts, implemented


def sized(font: Font, size: int = 14) -> Font:
    result = copy(font)
    result.size = size
    return result


def style_sheet(sheet: Worksheet, template: Worksheet, widths: list[int], table: str) -> None:
    sheet.freeze_panes = "B5"
    sheet.sheet_view.zoomScale = 70
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.sheet_properties.tabColor = "4472C4"
    sheet.print_title_rows = "1:4"
    sheet.sheet_properties.outlinePr.summaryRight = False
    for row in sheet:
        for cell in row:
            cell.font = sized(template["F14"].font)
            cell.border = copy(template["F14"].border)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if cell.row == 4:
                cell.font = sized(template["F4"].font)
                cell.fill = copy(template["F4"].fill)
            elif cell.row > 4:
                cell.fill = PatternFill("solid", fgColor=(
                    "EAF3FB" if cell.row % 2 else "FFFFFF"
                ))
    sheet["A1"].font = Font(name=template["F14"].font.name, size=18, bold=True, color="17365D")
    sheet.row_dimensions[1].height = 34
    sheet.row_dimensions[2].height = 80
    sheet.row_dimensions[4].height = 46
    for row in range(5, sheet.max_row + 1):
        sheet.row_dimensions[row].height = 260 if sheet.title == SY_SHEET else 230
    for col, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(col)].width = round(width * 1.3)
    ref = f"A4:{get_column_letter(sheet.max_column)}{sheet.max_row}"
    item = Table(displayName=table, ref=ref)
    item.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    sheet.add_table(item)
    sheet.print_options.horizontalCentered = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    for row in (1, 2):
        sheet.merge_cells(
            start_row=row, start_column=1, end_row=row, end_column=sheet.max_column
        )


def xml_bytes(root: ET.Element, original: bytes) -> bytes:
    namespaces = {}
    for _, value in ET.iterparse(BytesIO(original), events=("start-ns",)):
        prefix, uri = value
        namespaces[prefix] = uri
        ET.register_namespace(prefix, uri)
    rendered = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    declared = {prefix for _, (prefix, _) in ET.iterparse(BytesIO(rendered), events=("start-ns",))}
    # Office stores namespace prefixes inside Ignorable/Requires attribute values.
    for prefix, uri in namespaces.items():
        if prefix not in declared:
            root.set(f"xmlns:{prefix}" if prefix else "xmlns", uri)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def preserve_parts(source: bytes, generated: bytes) -> bytes:
    """기존 시트/캐시/확장 파트는 그대로 두고 추가 시트 및 스타일만 병합한다."""
    with ZipFile(BytesIO(source)) as old, ZipFile(BytesIO(generated)) as new:
        replacements = {}
        rel_name = "xl/_rels/workbook.xml.rels"
        original_rels = ET.fromstring(old.read(rel_name))
        generated_rels = ET.fromstring(new.read(rel_name))
        known_ids = {node.get("Id") for node in original_rels}
        remap = {}
        known_targets = {
            node.get("Target", "").lstrip("/").removeprefix("xl/") for node in original_rels
        }
        for node in generated_rels:
            if node.get("Type", "").endswith("/worksheet") and (
                node.get("Target", "").lstrip("/").removeprefix("xl/") not in known_targets
            ):
                index = 1
                while f"rId{index}" in known_ids:
                    index += 1
                new_id = f"rId{index}"
                remap[node.get("Id")] = new_id
                added = deepcopy(node)
                added.set("Id", new_id)
                original_rels.append(added)
                known_ids.add(new_id)
        replacements[rel_name] = xml_bytes(original_rels, old.read(rel_name))
        for name, namespace, key in (
            ("xl/workbook.xml", NS, "sheets"),
            ("[Content_Types].xml", CT, None),
        ):
            original = ET.fromstring(old.read(name))
            updated = ET.fromstring(new.read(name))
            target = original.find(f"{{{namespace}}}{key}") if key else original
            incoming = updated.find(f"{{{namespace}}}{key}") if key else updated
            if target is None or incoming is None:
                raise ValueError(f"잘못된 통합 문서 XML: {name}")
            identity = "sheetId" if key else ("Id" if namespace == REL else "PartName")
            known = {node.get(identity) for node in target}
            for node in incoming:
                if node.get(identity) not in known:
                    added = deepcopy(node)
                    if key:
                        added.set(f"{{{DOC_REL}}}id", remap[node.get(f"{{{DOC_REL}}}id")])
                    target.append(added)
            replacements[name] = xml_bytes(original, old.read(name))
        original_styles = ET.fromstring(old.read("xl/styles.xml"))
        generated_styles = ET.fromstring(new.read("xl/styles.xml"))
        for group in generated_styles:
            existing = original_styles.find(group.tag)
            if existing is None:
                original_styles.append(deepcopy(group))
            elif len(group) > len(existing):
                existing.extend(deepcopy(list(group)[len(existing):]))
                existing.set("count", str(len(existing)))
        style_order = (
            "numFmts", "fonts", "fills", "borders", "cellStyleXfs", "cellXfs",
            "cellStyles", "dxfs", "tableStyles", "colors", "extLst",
        )
        original_styles[:] = sorted(
            original_styles, key=lambda group: style_order.index(group.tag.rsplit("}", 1)[-1])
        )
        replacements["xl/styles.xml"] = xml_bytes(original_styles, old.read("xl/styles.xml"))
        result = BytesIO()
        with ZipFile(result, "w", ZIP_DEFLATED) as out:
            for entry in old.infolist():
                out.writestr(entry, replacements.get(entry.filename, old.read(entry.filename)))
            for name in new.namelist():
                if name not in old.namelist():
                    out.writestr(name, new.read(name))
        return result.getvalue()


def build_assessment(
    source: Path,
    output: Path,
    notes: Path = ROOT / "docs" / "api-notes.md",
    criteria: Path = ROOT / "src" / "wasm_agent" / "criteria.yaml",
) -> dict[str, str | int]:
    if source.resolve() == output.resolve() or (
        source.exists() and output.exists() and source.samefile(output)
    ):
        raise ValueError("원본 덮어쓰기는 허용하지 않습니다.")
    if not source.is_file() or source.suffix.lower() != ".xlsx":
        raise ValueError("유효한 원본 XLSX 파일이 필요합니다.")
    if output.suffix.lower() != ".xlsx":
        raise ValueError("출력 확장자는 .xlsx여야 합니다.")
    raw = source.read_bytes()
    try:
        book = load_workbook(BytesIO(raw))
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError("유효한 원본 XLSX 구조가 아닙니다.") from exc
    if len(book.sheetnames) != 5 or SOURCE_SHEET not in book.sheetnames:
        raise ValueError("원본 5개 시트와 질문별 평가 기준 시트가 필요합니다.")
    original = book[SOURCE_SHEET]
    rows = [
        row for row in original
        if isinstance(row[1].value, str) and "-SY-" in row[1].value
    ]
    codes = [row[1].value for row in rows]
    contracts, implemented = read_contracts(notes, criteria)
    if len(codes) != 20 or len(set(codes)) != 20 or set(codes) != contracts.keys():
        raise ValueError("원본 SY 질문은 계약과 일치하는 고유 코드 20개여야 합니다.")
    if any(row[4].value != "System Evidence" or any(
        row[col].value is None for col in range(5, 12)
    ) for row in rows):
        raise ValueError("원본 System Evidence 유형/질문/단계/증적 필드가 누락되었습니다.")
    sy = book.create_sheet(SY_SHEET)
    sy.append(["SY 질문 전체 - 원문 보존 및 Azure 수집 범위"])
    sy.append([
        "20개 원문 질문과 L1-L5는 참조용 기준이며 실제 점수가 아님. out_of_scope는 수집/판정 없음. "
        "partial은 Azure 부분 범위만으로 조직 전체 점수를 대체하지 않음. 조회 불가는 null과 사유로 기록. "
        "L4/L5는 해당 정책/자동화 증거 필요. 범위 근거: docs/api-notes.md; 구현: criteria.yaml."
    ])
    sy.append([])
    sy.append([
        "코드", "영역", "매핑", "원문 유형", "원문 질문", "L1 원문", "L2 원문", "L3 원문",
        "L4 원문", "L5 원문", "원문 증적", "원본 시트", "원본 행", "수집 유형",
        "scope", "범위 근거", "수집/확인 방법", "기존 판정 구현", "점수 처리 원칙",
    ])
    for row in rows:
        code = row[1].value
        contract = contracts[code]
        sy.append([
            *[cell.value for cell in row[1:12]], SOURCE_SHEET, row[1].row,
            contract["유형"], contract["scope"], contract["분류 근거"], contract["측정방법"],
            f"criteria.yaml - {code}" if code in implemented else "미구현 - 범위 제외",
            "null - 범위 제외, 대체 점수 없음" if contract["scope"] == "out_of_scope"
            else "실행 결과 아님 - 증거 부족은 null; partial은 Azure 초안만, 원 항목 대체 불가",
        ])
    style_sheet(sy, original, [18, 19, 16, 20, 65, 38, 38, 38, 38, 38, 52,
                               26, 12, 12, 18, 52, 65, 37, 55], "AssessmentSY")
    for row in range(5, sy.max_row + 1):
        cell = sy.cell(row, 12)
        cell.hyperlink = f"#'{SOURCE_SHEET}'!B{sy.cell(row, 13).value}"
    proposal = book.create_sheet(PROPOSAL_SHEET)
    proposal.append(["Azure/Foundry 운영 거버넌스 - 추가 제안"])
    proposal.append([
        STATE + ". 원본 20개 SY 및 기존 점수를 변경하지 않음. 신규 L1-L5/임계값/API를 정의하지 않음. "
        "Azure 구성 사실 수집기는 구현(수집 결과는 report 'Azure 추가 제안 현황' 시트), 평가기와 Level은 없음. "
        "공식 권고를 Azure 범위에 한정해 구체화한 설계 초안. "
        "M365/Entra/Purview/Power Platform/Agent 365 진단 제외. 증적은 비밀/개인정보를 마스킹."
    ])
    proposal.append([])
    proposal.append([
        "제안 코드", "진단 영역", "영역 근거", "승인/구현 상태", "제안 질문", "기존 코드 보완 대상",
        "차이/보완 이유", "필요 증적", "Reader 조회 가능 범위/한계", "공식 출처 URL", "공식 출처 절",
        "확인일", "보조 공식 출처 URL", "보조 출처 절/제품 범위", "판정 기준",
    ])
    for number, (question, related, rationale, evidence, limits, section, extra, detail) in enumerate(
        PROPOSALS, 1
    ):
        code = f"AZ-SY-P{number:02}"
        primary, secondary, reason = DOMAINS[code]
        proposal.append([
            code, primary, reason + (f" (보조: {secondary})" if secondary else ""),
            STATE, question, related, rationale, evidence, limits,
            CAF, section, date.fromisoformat(CHECKED), extra, detail,
            "미정 - 승인 전, L1-L5/수치 임계값 없음, Level 자동 판정 없음",
        ])
    style_sheet(proposal, original, [19, 16, 60, 38, 70, 32, 60, 65, 75, 58, 50, 15, 58, 50, 48],
                "AssessmentProposals")
    for row in range(5, proposal.max_row + 1):
        proposal.cell(row, 12).number_format = "yyyy-mm-dd"
        for col in (10, 13):
            cell = proposal.cell(row, col)
            if cell.value:
                cell.hyperlink = cell.value
                cell.font = Font(name=original["F14"].font.name, size=14, color="0563C1", underline="single")
    generated = BytesIO()
    book.save(generated)
    result = preserve_parts(raw, generated.getvalue())
    verified = load_workbook(BytesIO(result))
    if len(verified.sheetnames) != 7:
        raise ValueError("출력 시트 검증 실패")
    if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(raw).digest():
        raise ValueError("작업 중 원본이 변경되었습니다. 출력을 중단합니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result)
    return {
        "original_sheets": 5, "sy_questions": len(rows), "proposals": len(PROPOSALS),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(build_assessment(args.source, args.output))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"오류: {exc}\n")


if __name__ == "__main__":
    main()
