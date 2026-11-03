"""Convert the supplied OOXML/text sources without changing the originals."""

from __future__ import annotations

import argparse
import posixpath
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
P = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CODE = re.compile(r"^(?:DM|DS|BI|DP|OE|OT)-SY-\d{2}$")


def markdown_cell(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(
        ">", "&gt;"
    ).replace("|", "&#124;").replace("\r\n", "\n").replace("\n", "<br>")


def markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(map(len, rows))
    lines = []
    for index, row in enumerate(rows):
        padded = row + [""] * (width - len(row))
        lines.append("| " + " | ".join(markdown_cell(c) for c in padded) + " |")
        if index == 0:
            lines.append("| " + " | ".join(["---"] * width) + " |")
    return "\n".join(lines)


def word_paragraph(node: ET.Element) -> str:
    parts = []
    for item in node.iter():
        if item.tag == W + "t":
            parts.append(item.text or "")
        elif item.tag in (W + "br", W + "cr"):
            parts.append("\n")
        elif item.tag == W + "tab":
            parts.append("\t")
    return "".join(parts)


def word_table(node: ET.Element) -> list[list[str]]:
    rows = []
    for tr in node.findall(W + "tr"):
        row = []
        for tc in tr.findall(W + "tc"):
            row.append("\n".join(word_paragraph(p) for p in tc.findall(W + "p")))
            span = tc.find(W + "tcPr/" + W + "gridSpan")
            row.extend([""] * (int(span.get(W + "val", "1")) - 1) if span is not None else [])
        rows.append(row)
    return rows


def read_word(path: Path) -> tuple[str, list[list[list[str]]]]:
    with ZipFile(path) as archive:
        body = ET.fromstring(archive.read("word/document.xml")).find(W + "body")
    if body is None:
        raise ValueError(f"{path.name}: document body missing")
    blocks, tables = [], []
    for node in body:
        if node.tag == W + "tbl":
            rows = word_table(node)
            tables.append(rows)
            blocks.append(markdown_table(rows))
        elif node.tag == W + "p":
            text = word_paragraph(node)
            if text:
                blocks.append(markdown_cell(text))
    if not blocks:
        raise ValueError(f"{path.name}: no readable content")
    return "\n\n".join(blocks), tables


def column_index(reference: str) -> int:
    value = 0
    for letter in re.match(r"[A-Z]+", reference).group():
        value = value * 26 + ord(letter) - ord("A") + 1
    return value - 1


def column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def read_workbook(path: Path) -> tuple[str, dict[str, list[dict[str, str]]]]:
    sections, sheets = [], {}
    with ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = [
                "".join(node.itertext())
                for node in ET.fromstring(archive.read("xl/sharedStrings.xml"))
            ]
        relationships = {
            node.get("Id"): node.get("Target", "")
            for node in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels")).findall(P + "Relationship")
        }
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        for sheet in workbook.findall(S + "sheets/" + S + "sheet"):
            name = sheet.get("name", "")
            target = relationships[sheet.get(R + "id")]
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            root = ET.fromstring(archive.read(target))
            parsed, max_column = [], 0
            for row in root.findall(S + "sheetData/" + S + "row"):
                values = {}
                for cell in row.findall(S + "c"):
                    address = cell.get("r", "")
                    value_node = cell.find(S + "v")
                    value = value_node.text or "" if value_node is not None else ""
                    if cell.get("t") == "s":
                        value = shared[int(value)]
                    elif cell.get("t") == "inlineStr":
                        value = "".join(t.text or "" for t in cell.iter(S + "t"))
                    formula = cell.find(S + "f")
                    if formula is not None:
                        value = f"{value} [formula: ={formula.text or ''}; cached value only]"
                    if value:
                        values[address] = value
                        max_column = max(max_column, column_index(address) + 1)
                if values:
                    parsed.append(values)
            sheets[name] = parsed
            rows = [["Excel 행"] + [column_name(i) for i in range(1, max_column + 1)]]
            for values in parsed:
                first = next(iter(values))
                row_number = re.search(r"\d+$", first).group()
                row = [""] * max_column
                for address, value in values.items():
                    row[column_index(address)] = value
                rows.append([row_number] + row)
            merges = [node.get("ref", "") for node in root.findall(S + "mergeCells/" + S + "mergeCell")]
            sections.append(
                f"## {name}\n\n병합 셀: {', '.join(merges) or '없음'}. "
                "병합 영역은 원본처럼 좌상단 셀에만 값이 있습니다. "
                "수식은 재계산하지 않고 캐시값과 수식 원문을 병기합니다.\n\n"
                + markdown_table(rows)
            )
    return "\n\n".join(sections), sheets


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    encodings = ("utf-16",) if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "cp949")
    for encoding in encodings:
        try:
            value = raw.decode(encoding)
            if "\x00" in value:
                raise ValueError(f"{path.name}: embedded NUL; unsupported text format")
            return value
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name}: unsupported text encoding; request Markdown conversion")


SCOPES = {
    "DS-SY-06": ("in_scope", "Foundry 모델 배포 및 고객 허용 모델 목록이 Azure 담당 범위이다."),
    "BI-SY-08": ("in_scope", "Foundry 평가 이력과 배포 전 평가 여부가 Azure 담당 범위이다."),
    "BI-SY-09": ("partial", "Defender for Cloud의 Azure AI 워크로드 권고만 포함하며 타 제품 Defender 영역은 제외한다."),
    "OE-SY-16": ("partial", "Azure 진단 로그·Activity Log·보존 설정만 대체 증적으로 수집하며 Purview Audit는 제외한다."),
    "OT-SY-18": ("partial", "Azure Monitor로 확인 가능한 Azure 호스팅 Agent만 포함하며 M365·Agent 365 사용 분석은 제외한다."),
    "OT-SY-19": ("partial", "Azure Cost Management 비용만 포함하며 M365 Billing policy는 제외한다."),
}

METHODS = {
    "DS-SY-06": "ARM 모델 배포 목록과 고객 허용 모델 목록을 모델·버전 기준 대조; 배포를 분모로 집계",
    "BI-SY-08": "평가 이력을 Agent·배포 버전에 연결하고 성공 평가 종료일과 실제 배포일 비교; 생성일을 배포일로 대체하지 않음",
    "BI-SY-09": "Azure AI 리소스에 연결된 Defender 권고·심각도·조치 이력·보안 점수 조회; 내부 보안 점수 기준 별도 입력",
    "OE-SY-16": "Azure 진단 설정·로그 목적지·Log Analytics 보존 기간 조회; 내부 보관 규정과 대조; Purview와 동등 판정 금지",
    "OT-SY-18": "최근 90일 관측 구간 전체의 Agent별 호출·토큰·최종 사용일 조회; 수집 공백을 비활성으로 간주하지 않음",
    "OT-SY-19": "최근 30일 Azure AI 비용 총액 대비 중복 없이 Agent에 귀속 가능한 비용 비율; 통화별 분리 및 월별 집계 증적 구분",
}


def build_scope(
    source_name: str,
    tables: list[list[list[str]]],
    sheets: dict[str, list[dict[str, str]]],
) -> str:
    item_tables = [t for t in tables if t and t[0][:2] == ["코드", "수집 항목"]]
    level_tables = [t for t in tables if t and t[0][0] == "코드" and t[0][1].startswith("L1")]
    if len(item_tables) != 5 or len(level_tables) != 1:
        raise ValueError("Unexpected source tables; do not infer missing criteria")
    levels = {row[0]: row[1:6] for row in level_tables[0][1:]}
    rows = []
    for index, table in enumerate(item_tables, 1):
        for row in table[1:]:
            code, name, product, _, _, evidence, _ = row
            scope, reason = SCOPES.get(
                code, ("out_of_scope", f"원 항목의 담당 제품은 {product}이며 Azure/Foundry 담당 범위가 아니다.")
            )
            rows.append([
                code, name, f"T{index}", product,
                METHODS.get(code, f"타 담당 확인: {evidence}; 본 프로젝트에서는 구현하지 않음"),
                *levels[code], scope, reason,
            ])
    if len(rows) != 20 or len({r[0] for r in rows}) != 20 or len(levels) != 20:
        raise ValueError("Expected exactly 20 unique System Evidence items")
    workbook_levels = {}
    for records in sheets.values():
        for cells in records:
            for address, code in cells.items():
                if CODE.fullmatch(code) and address.startswith("B"):
                    number = re.search(r"\d+$", address).group()
                    if all(f"{c}{number}" in cells for c in "GHIJK"):
                        workbook_levels[code] = [cells[f"{c}{number}"] for c in "GHIJK"]
    def normalize(value: str) -> str:
        return re.sub(r"\s+", "", value)
    mismatches = [
        code for code, values in levels.items()
        if code not in workbook_levels
        or [normalize(v) for v in values] != [normalize(v) for v in workbook_levels[code]]
    ]
    if mismatches:
        raise ValueError(f"DOCX/XLSX criteria mismatch: {mismatches}; manual confirmation required")
    rows.sort(key=lambda row: int(row[0][-2:]))
    header = [
        "코드", "항목명", "유형", "제품/메뉴", "측정방법",
        "L1", "L2", "L3", "L4", "L5", "scope", "분류 근거",
    ]
    mapping = [
        ["개발 안건", "프로젝트 산출물", "현재 상태/한계"],
        ["1. 항목 정의", "docs/api-notes.md", "20개 원 항목과 추가 제안을 구분; 추가 제안은 미구현"],
        ["2. 측정 방안", "docs/api-notes.md, docs/guide.md, src/wasm_agent/", "설계·API 근거·읽기 권한"],
        ["3. 분석 기준", "config/criteria.yaml, src/wasm_agent/evaluation.py, tests/", "원문 미정의 구간은 임의 보간 금지"],
        ["4. 보고서", "output/report.html, output/report.xlsx, output/results.zip", "사용자 보고서와 통합 원시 데이터"],
        ["5. 개선 과제", "criteria.yaml 기반 다음 단계 조건, 보고서 개선 후보", "Step 8 예정; 자동 변경/정책 적용은 하지 않음"],
        ["6. 이기종 적용", "공통 AgentEvidence, config/manual_agents.csv, docs/api-notes.md", "사례/AI Gateway/OpenTelemetry는 검증 필요"],
    ]
    return (
        "# System Evidence 범위 및 기준\n\n"
        f"기준 원본: [{source_name}](source/{source_name}.md). "
        "평가 모델 XLSX의 `4. 질문별 평가 기준`에 있는 20개 SE 행의 L1~L5와 "
        "공백 차이를 제외하고 일치함을 변환 시 검증했습니다.\n\n"
        "## 범위 원칙\n\n"
        "- in_scope 2개, partial 4개, out_of_scope 14개. out_of_scope는 문서에만 표시하며 수집·판정하지 않습니다.\n"
        "- Azure 인벤토리의 ID·소유자 태그는 Entra Agent ID, Agent Registry, 퇴사자 확인을 대체하지 않습니다. "
        "따라서 DM-SY-03, DP-SY-10, OE-SY-13을 Azure 인벤토리로 재해석하지 않습니다.\n"
        "- partial의 수치와 L 레벨은 Azure 부분 범위의 초안이며 조직 전체 원 항목의 최종 점수가 아닙니다. "
        "특히 OE-SY-16의 Azure 로그는 Purview Audit 보관을 입증하지 못합니다.\n"
        "- L1~L5는 원문 그대로 보존합니다. 권한 거부·기능 미제공을 L1로 취급하지 않고 null 및 사유를 남깁니다. "
        "실제 통제가 없다는 증거와 통제를 조회할 수 없다는 상태를 구분합니다.\n"
        "- 예: DS-SY-06의 80% 초과~90% 미만, BI-SY-08의 30% 이상~80% 미만처럼 "
        "원문이 다루지 않는 구간은 임의로 L2/L3에 배정하지 않습니다. "
        "L4/L5의 자동화·정책·지속 운영은 비율만으로 충족 처리할 수 없습니다.\n"
        "- OE-SY-16의 1년은 내부 규정의 예시이지 모든 고객에게 적용할 고정 임계값이 아닙니다. "
        "BI-SY-09의 내부 보안 점수 기준도 고객 입력이 필요합니다.\n"
        "- 평가 원문은 인터뷰와의 괴리 시 영역 점수 보정도 설명하나, 이번 요청의 자동 기능은 괴리 플래그입니다. "
        "영역 점수 자동 보정은 별도 승인 없이 구현하지 않습니다.\n\n"
        "## 20개 항목\n\n" + markdown_table([header, *rows])
        + "\n\n## 원본 및 변환 범위\n\n"
        "DOCX 1개, XLSX 1개(5개 시트), TXT 2개를 같은 디렉터리에 `.원본확장자.md`로 변환합니다. "
        "헤더에 원본 파일명을 보존하고 표는 Markdown 표로 유지합니다. "
        "PPTX 3개는 보조 제안 자료이며 Step 0의 명시된 DOCX/XLSX/TXT 변환 대상 및 판정 기준 출처에 포함하지 않았습니다. "
        "원본 파일은 변경하지 않습니다. 회의록에는 개인 식별 정보가 있을 수 있으므로 외부 보고서에 그대로 복사하지 않습니다.\n\n"
        "## 개발필요항목의 6개 안건 매핑\n\n" + markdown_table(mapping) + "\n"
    )


def convert(source_dir: Path, scope_path: Path) -> list[Path]:
    pending: dict[Path, str] = {}
    word_sources, workbook_sources = [], []
    for path in sorted(source_dir.iterdir()):
        if path.suffix.lower() not in (".docx", ".xlsx", ".txt"):
            continue
        if path.suffix.lower() == ".docx":
            content, tables = read_word(path)
            word_sources.append((path.name, tables))
        elif path.suffix.lower() == ".xlsx":
            content, sheets = read_workbook(path)
            workbook_sources.append(sheets)
        else:
            content = read_text(path)
        pending[path.with_suffix(path.suffix + ".md")] = (
            f"# 원본: {path.name}\n\n"
            "자동 변환본입니다. 원본 파일은 수정하지 않았습니다. "
            "출력 문장부호는 ASCII 하이픈으로 정규화합니다.\n\n" + content + "\n"
        )
    if len(word_sources) != 1 or len(workbook_sources) != 1:
        raise ValueError("Expected one criteria DOCX and one assessment XLSX")
    source_name, tables = word_sources[0]
    pending[scope_path] = build_scope(source_name, tables, workbook_sources[0])
    for path, content in pending.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.replace(chr(0x2014), "-"), encoding="utf-8")
    return list(pending)


def main() -> None:
    parser = argparse.ArgumentParser(description="원본 DOCX/XLSX/TXT -> Markdown 및 scope 생성")
    parser.add_argument("--source-dir", type=Path, default=Path("docs") / "source")
    parser.add_argument("--scope-path", type=Path, default=Path(".wasm-agent") / "source-scope.md")
    args = parser.parse_args()
    try:
        paths = convert(args.source_dir, args.scope_path)
    except (ValueError, KeyError, ET.ParseError, OSError, BadZipFile) as exc:
        parser.exit(1, f"자료 변환 중단: {exc}. 원문 확인 또는 .md/.csv 변환본이 필요합니다.\n")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
