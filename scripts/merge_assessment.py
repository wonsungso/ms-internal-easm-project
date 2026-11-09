"""평가 모델의 SE 기준과 실제 점수 집계를 같은 시트/서식으로 반영한다.

원본 zip에서 시트 2, 4 XML만 직접 고치고 나머지 파트(스타일, 시트 1/3/5, 민감도 라벨 등)는
바이트 그대로 보존한다. 검토된 템플릿을 입력하면 사용자 셀 서식·점수·메모를 유지한다.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import load_workbook

from scripts.assessment_descriptions import ITEM_DETAILS
from scripts.proposal_levels import LEVELS
from wasm_agent.models import load_criteria
from wasm_agent.proposals import DOMAINS, PRODUCTS, TITLES

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHEET = "4. 질문별 평가 기준"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
Q = f"{{{NS}}}"
SHEET_QUESTIONS = "xl/worksheets/sheet2.xml"
SHEET_CRITERIA = "xl/worksheets/sheet4.xml"
DOMAIN_COLUMN = {"2. Design": "E", "3. Build": "F", "4. Deploy": "G", "5. Operate": "H", "6. Optimize": "I"}
NOTE = (
    "- System Evidence 31개를 시트 4에서 평가하고 시트 5 실제 집계에 반영. "
    "미확보·조회 실패·대상 없음은 N/A이며 L1 또는 0점으로 환산하지 않음"
)
ROW_HEIGHT = "25.05"
FIRST_DATA_ROW = 5
SHEET_SCORING = "xl/worksheets/sheet5.xml"
MANUAL_LEVELS = {
    "DM-SY-01": (
        "제작 허용 주체·Agent 유형의 통제 기준이 없음을 확인",
        "일부 제한은 있으나 승인 주체·유형 기준 또는 적용 범위 미흡",
        "승인 제작 주체·Agent 유형 기준과 실제 허용 범위 일치",
        "L3 충족, 지원 설정·승인 절차로 미승인 제작 통제와 변경 추적",
        "L4 충족, 위험·변경 이력으로 허용 범위 지속 개선",
    ),
    "DM-SY-02": (
        "제작 권한·환경 관리 기준이 없음을 확인",
        "환경·권한 일부 관리, 승인 대장과 미대사 또는 편차 존재",
        "승인 제작자와 유효 권한 대사, 용도별 환경·접근 분리",
        "L3 충족, 생성·권한 변경 승인과 편차 탐지·회수 운영",
        "L4 충족, 실제 사용·위반 이력으로 환경·권한 지속 개선",
    ),
    "DM-SY-03": (
        "생성 승인·요청 관리 절차가 없음을 확인",
        "최근 6개월 신규 Agent와 승인 요청 매칭률 80% 미만",
        "신규 Agent 80% 이상 승인 요청 매칭, 누락·중복 대사",
        "매칭률 95% 이상, 미승인 생성 자동 탐지·통보",
        "매칭률 100%, L4 충족과 추세 기반 수요 계획 개선",
    ),
    "DS-SY-04": (
        "대상 환경 확인 완료, 유효 데이터 정책 적용률 0%",
        "유효 데이터 정책 적용률 0% 초과~80% 미만",
        "대상 환경 80% 이상 승인 커넥터 분류·차단 정책 검증",
        "적용률 100%, 신규 환경 편입과 정책 편차 통제 자동화",
        "L4 충족, 위반·우회 시험으로 분류·정책 지속 개선",
    ),
    "BI-SY-10": (
        "개발·테스트와 운영의 접근·변경 분리 통제가 없음",
        "환경 일부 분리, 운영 접근·변경 또는 관리 기준 미흡",
        "개발·테스트·운영 분리, 라이선스·지원 범위 내 관리 기준 충족",
        "L3 충족, 지원 배포 경로·권한 통제로 미승인 운영 반영 차단",
        "L4 충족, 환경 이용·위반 이력으로 분리 통제 개선",
    ),
    "DP-SY-17": (
        "Agent 자산·배포 등록 절차가 없음을 확인",
        "승인 등록부·실제 Agent 정합률 90% 미만",
        "Agent·책임자·배포 범위·상태 정합률 90% 이상",
        "정합률 98% 이상, 등록 편차·변경 자동 탐지·추적",
        "정합률 100%, L4 충족과 대사·변경 관리 개선 이력",
    ),
    "DP-SY-18": (
        "Agent 공유·설치의 승인 범위 통제 기준이 없음",
        "공유·설치 일부 제한, 승인 대상·범위와 불일치",
        "지원 제품별 공유·설치 범위가 승인 대상과 일치",
        "L3 충족, 지원 설정·승인 경로로 편차 통제와 감사 추적",
        "L4 충족, 설치·공유·위반 이력으로 허용 기준 개선",
    ),
    "OT-SY-27": (
        "승인되지 않은 Agent 탐지·대사 절차가 없음을 확인",
        "미승인 비율 5% 이상 또는 탐지 건 조치율 80% 미만",
        "관측 범위·기간 명시, 미승인 비율 5% 미만과 조치율 80% 이상",
        "미승인 비율 1% 미만, L3 충족과 지원 경로별 자동 통보·통제",
        "관측 범위 내 미승인 0건, L4 충족과 탐지·수요 전환 개선",
    ),
    "OT-SY-30": (
        "민감 데이터 노출 점검·조치 절차가 없음을 확인",
        "확인된 고위험 노출 조치율 90% 미만",
        "고위험 노출 조치율 90% 이상, 지원 데이터 경로별 보호 검증",
        "미조치 고위험 0건, L3 충족과 지원 DLP·접근 통제 자동화",
        "L4 충족, 노출·오탐·사고 이력으로 보호 정책 개선",
    ),
}


def xml_bytes(root: ET.Element, original: bytes) -> bytes:
    """직렬화 후에도 Office 호환 네임스페이스 접두사(mc:Ignorable 등)가 유지되게 한다."""
    namespaces = {}
    for _, value in ET.iterparse(BytesIO(original), events=("start-ns",)):
        prefix, uri = value
        namespaces[prefix] = uri
        ET.register_namespace(prefix, uri)
    rendered = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    declared = {prefix for _, (prefix, _) in ET.iterparse(BytesIO(rendered), events=("start-ns",))}
    for prefix, uri in namespaces.items():
        if prefix not in declared:
            root.set(f"xmlns:{prefix}" if prefix else "xmlns", uri)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def cell_ref(ref: str) -> tuple[str, int]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    return match.group(1), int(match.group(2))


def shared_strings(archive: ZipFile) -> list[str]:
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.itertext()) for node in root.findall(f"{Q}si")]


def text_cell(ref: str, style: str, text: str) -> ET.Element:
    cell = ET.Element(f"{Q}c", {"r": ref, "s": style, "t": "inlineStr"})
    inline = ET.SubElement(cell, f"{Q}is")
    ET.SubElement(inline, f"{Q}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}).text = text
    return cell


def set_row_number(row: ET.Element, number: int) -> None:
    row.set("r", str(number))
    for cell in row.findall(f"{Q}c"):
        cell.set("r", f"{cell_ref(cell.get('r'))[0]}{number}")


def restyle(row: ET.Element, styles: dict[str, str]) -> None:
    for cell in row.findall(f"{Q}c"):
        cell.set("s", styles[cell_ref(cell.get("r"))[0]])


def proposal_texts() -> dict[str, dict[str, str]]:
    return {
        code: {
            "title": f"{TITLES[code]} [{PRODUCTS[code]}]",
            **dict(zip("GHIJK", LEVELS[code][:5], strict=True)),
            "evidence": LEVELS[code][5],
        }
        for code in TITLES
    }


def patch_criteria(raw: bytes, strings: list[str]) -> bytes:
    root = ET.fromstring(raw)
    data = root.find(f"{Q}sheetData")
    rows = {int(row.get("r")): row for row in data.findall(f"{Q}row")}
    blocks: dict[str, list[int]] = {}
    for number, row in rows.items():
        first = row.find(f"{Q}c")
        if first is None or first.get("t") != "s":
            continue
        code = strings[int(first.find(f"{Q}v").text)]
        if "-SY-" in code:
            domain = strings[int(row.findall(f"{Q}c")[1].find(f"{Q}v").text)]
            blocks.setdefault(domain, []).append(number)
    texts = proposal_texts()
    inserts: dict[int, list[str]] = {}
    for code, (primary, _, _) in DOMAINS.items():
        inserts.setdefault(max(blocks[primary]), []).append(code)

    def shifted(old: int) -> int:
        return old + sum(len(codes) for last, codes in inserts.items() if last < old)

    plan: list[tuple[int, ET.Element]] = []
    for number, row in rows.items():
        plan.append((shifted(number), row))
    added_rows: list[int] = []
    for last, codes in sorted(inserts.items()):
        domain_rows = sorted(number for group in blocks.values() if last in group for number in group)
        mid_row, last_row = rows[domain_rows[-2]], rows[last]
        mid = {cell_ref(c.get("r"))[0]: c.get("s") for c in mid_row.findall(f"{Q}c")}
        end = {cell_ref(c.get("r"))[0]: c.get("s") for c in last_row.findall(f"{Q}c")}
        for offset, code in enumerate(sorted(codes), 1):
            new = deepcopy(last_row)
            number = shifted(last) + offset
            set_row_number(new, number)
            new.attrib.pop("thickBot", None)
            for cell in new.findall(f"{Q}c"):
                column = cell_ref(cell.get("r"))[0]
                payload = texts[code]
                if column in ("C", "D", "E"):
                    continue
                for child in list(cell):
                    cell.remove(child)
                cell.attrib.pop("t", None)
                if column == "B":
                    inline = ET.SubElement(cell, f"{Q}is")
                    ET.SubElement(inline, f"{Q}t").text = code
                    cell.set("t", "inlineStr")
                elif column in ("F", "G", "H", "I", "J", "K", "L"):
                    key = "title" if column == "F" else "evidence" if column == "L" else column
                    inline = ET.SubElement(cell, f"{Q}is")
                    ET.SubElement(inline, f"{Q}t").text = payload[key]
                    cell.set("t", "inlineStr")
                elif column == "N":
                    inline = ET.SubElement(cell, f"{Q}is")
                    ET.SubElement(inline, f"{Q}t").text = "초안 - 점수 산정 제외"
                    cell.set("t", "inlineStr")
            restyle(new, end if offset == len(codes) else mid)
            if offset == len(codes):
                new.set("thickBot", "1")
            plan.append((number, new))
            added_rows.append(number)
        restyle(last_row, mid)
        last_row.attrib.pop("thickBot", None)
    data[:] = [row for _, row in sorted(plan, key=lambda item: item[0])]
    for old, row in rows.items():
        set_row_number(row, shifted(old))
    last_number = max(number for number, _ in plan)
    root.find(f"{Q}dimension").set("ref", f"B2:N{last_number}")
    merges = root.find(f"{Q}mergeCells")
    merges.set("count", str(len(merges)))
    scorable = [n for n in range(FIRST_DATA_ROW, last_number + 1) if n not in added_rows]
    ranges, start = [], scorable[0]
    for previous, current in zip(scorable, scorable[1:] + [None], strict=True):
        if current != previous + 1:
            ranges.append(f"M{start}" if start == previous else f"M{start}:M{previous}")
            start = current
    root.find(f"{Q}dataValidations").find(f"{Q}dataValidation").set("sqref", " ".join(ranges))
    return xml_bytes(root, raw)


def patch_questions(raw: bytes, strings: list[str]) -> bytes:
    root = ET.fromstring(raw)
    rows = {int(row.get("r")): row for row in root.find(f"{Q}sheetData").findall(f"{Q}row")}
    extra: dict[str, list[str]] = {}
    for code in sorted(DOMAINS):
        extra.setdefault(DOMAIN_COLUMN[DOMAINS[code][0]], []).append(
            f"▸ {TITLES[code]} (추가 제안)\n  [{PRODUCTS[code]}]"
        )
    lines = 1
    for cell in rows[8].findall(f"{Q}c"):
        column = cell_ref(cell.get("r"))[0]
        if column not in extra:
            continue
        original = strings[int(cell.find(f"{Q}v").text)]
        merged = original + "\n\n" + "\n\n".join(extra[column])
        replacement = text_cell(cell.get("r"), cell.get("s"), merged)
        cell.clear()
        cell.attrib.update(replacement.attrib)
        cell.extend(list(replacement))
        lines = max(lines, merged.count("\n") + 1)
    rows[8].set("ht", "345")
    note_cell = next(c for c in rows[10].findall(f"{Q}c") if cell_ref(c.get("r"))[0] == "B")
    original = strings[int(note_cell.find(f"{Q}v").text)]
    replacement = text_cell(note_cell.get("r"), note_cell.get("s"), original + "\n" + NOTE)
    note_cell.clear()
    note_cell.attrib.update(replacement.attrib)
    note_cell.extend(list(replacement))
    rows[10].set("ht", "52")
    return xml_bytes(root, raw)


def merge_assessment(source: Path, output: Path) -> dict[str, str | int]:
    if source.resolve() == output.resolve():
        raise ValueError("원본 덮어쓰기는 허용하지 않습니다.")
    raw = source.read_bytes()
    with ZipFile(BytesIO(raw)) as archive:
        if SOURCE_SHEET not in archive.read("xl/workbook.xml").decode("utf-8"):
            raise ValueError("질문별 평가 기준 시트가 있는 원본 평가 모델이 필요합니다.")
        strings = shared_strings(archive)
        book = load_workbook(BytesIO(raw))
        se_rows = [row for row in book[SOURCE_SHEET] if "-SY-" in str(row[1].value)]
        present = {
            code for code in DOMAINS
            if any(TITLES[code] in str(row[5].value) for row in se_rows)
        }
        if len(se_rows) == 31 and DOMAINS.keys() <= {str(row[1].value) for row in se_rows}:
            present = set(DOMAINS)
        if present and present != DOMAINS.keys():
            raise ValueError("SE 항목이 일부만 병합된 파일입니다. 전체 원본 또는 검토 템플릿을 사용하세요.")
        patched = {} if present else {
            SHEET_CRITERIA: patch_criteria(archive.read(SHEET_CRITERIA), strings),
            SHEET_QUESTIONS: patch_questions(archive.read(SHEET_QUESTIONS), strings),
        }
        patched = review_parts(archive, patched)
        result = BytesIO()
        with ZipFile(result, "w", ZIP_DEFLATED) as out:
            for entry in archive.infolist():
                out.writestr(entry, patched.get(entry.filename, archive.read(entry.filename)))
    if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(raw).digest():
        raise ValueError("작업 중 원본이 변경되었습니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result.getvalue())
    return {"merged_proposals": len(DOMAINS), "source_sha256": hashlib.sha256(raw).hexdigest()}


def replace_text(row: ET.Element, column: str, text: str) -> None:
    number = row.get("r")
    cell = row.find(f"{Q}c[@r='{column}{number}']")
    if cell is None:
        raise ValueError(f"필수 셀 없음: {column}{number}")
    replacement = text_cell(cell.get("r"), cell.get("s", "0"), text)
    row.insert(list(row).index(cell), replacement)
    row.remove(cell)


def replace_question(row: ET.Element, title: str, description: str) -> None:
    ref = f"F{row.get('r')}"
    cell = row.find(f"{Q}c[@r='{ref}']")
    if cell is None:
        raise ValueError(f"필수 셀 없음: {ref}")
    replacement = text_cell(ref, cell.get("s", "0"), "")
    inline = replacement.find(f"{Q}is")
    inline.clear()
    bullets = "\n".join("- " + point for point in description.splitlines())
    for text, bold in ((title, "1"), ("\n" + bullets, "0")):
        run = ET.SubElement(inline, f"{Q}r")
        properties = ET.SubElement(run, f"{Q}rPr")
        ET.SubElement(properties, f"{Q}b", {"val": bold})
        ET.SubElement(run, f"{Q}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}).text = text
    row.insert(list(row).index(cell), replacement)
    row.remove(cell)


def review_parts(archive: ZipFile, patched: dict[str, bytes]) -> dict[str, bytes]:
    strings = shared_strings(archive)

    def value(cell: ET.Element | None) -> str:
        if cell is None:
            return ""
        if cell.get("t") == "inlineStr":
            return "".join(cell.find(f"{Q}is").itertext())
        node = cell.find(f"{Q}v")
        return strings[int(node.text)] if cell.get("t") == "s" else node.text if node is not None else ""

    raw = patched.get(SHEET_CRITERIA, archive.read(SHEET_CRITERIA))
    root = ET.fromstring(raw)
    data = root.find(f"{Q}sheetData")

    def remove_assessment_row(row: ET.Element) -> None:
        removed = int(row.get("r"))
        data.remove(row)
        for remaining in data:
            number = int(remaining.get("r"))
            if number > removed:
                set_row_number(remaining, number - 1)
        dimension = root.find(f"{Q}dimension")
        dimension.set("ref", re.sub(
            r"(\d+)$", lambda match: str(int(match[1]) - 1), dimension.get("ref"),
        ))

    old_audit = next((
        row for row in data
        if value(row.find(f"{Q}c[@r='B{row.get('r')}']")) == "OE-SY-16"
        and "감사 로그" in value(row.find(f"{Q}c[@r='F{row.get('r')}']"))
    ), None)
    if old_audit is not None:
        retired = next((
            row for row in data if value(row.find(f"{Q}c[@r='B{row.get('r')}']")) == "OE-SY-15"
        ), None)
        if retired is None:
            raise ValueError("감사 로그 코드 이전에 필요한 기존 항목이 없습니다.")
        remove_assessment_row(retired)
        replace_text(old_audit, "B", "OE-SY-22")
    retired_redteam = next((
        row for row in data
        if value(row.find(f"{Q}c[@r='E{row.get('r')}']")) == "System Evidence"
        and "red team" in value(row.find(f"{Q}c[@r='F{row.get('r')}']")).lower()
    ), None)
    if retired_redteam is not None:
        remove_assessment_row(retired_redteam)
    system_rows = [
        row for row in data
        if value(row.find(f"{Q}c[@r='E{row.get('r')}']")) == "System Evidence"
    ]
    if len(system_rows) != 31:
        raise ValueError("연속 SE 번호를 부여하려면 System Evidence 31개가 필요합니다.")
    for index, row in enumerate(system_rows, 1):
        previous = value(row.find(f"{Q}c[@r='B{row.get('r')}']"))
        replace_text(row, "B", f"{previous[:2]}-SY-{index:02}")
    for row in data:
        title = value(row.find(f"{Q}c[@r='F{row.get('r')}']"))
        for code in TITLES:
            if TITLES[code] in title:
                replace_text(row, "B", code)
                break
    criteria = load_criteria()["items"]
    groups: dict[tuple[str, str], list[int]] = {}
    seen = set()
    for row in data.findall(f"{Q}row"):
        number = int(row.get("r"))
        code = value(row.find(f"{Q}c[@r='B{number}']"))
        if number >= FIRST_DATA_ROW and code:
            domain = value(row.find(f"{Q}c[@r='C{number}']"))
            perspective = value(row.find(f"{Q}c[@r='E{number}']"))
            groups.setdefault((domain, perspective), []).append(number)
            if code in criteria:
                if code not in ITEM_DETAILS:
                    raise ValueError(f"수집 항목 설명이 없습니다: {code}")
                replace_question(row, criteria[code]["title"], ITEM_DETAILS[code])
        if code not in criteria and code not in MANUAL_LEVELS:
            continue
        seen.add(code)
        if code in criteria:
            replace_text(row, "L", criteria[code]["evidence"])
        levels = criteria[code]["levels"].values() if code in criteria else MANUAL_LEVELS[code]
        for column, text in zip("GHIJK", levels, strict=True):
            replace_text(row, column, text)
        if code in DOMAINS:
            replace_text(row, "L", criteria[code]["evidence"])
            memo = row.find(f"{Q}c[@r='N{number}']")
            if value(memo) == "초안 - 점수 산정 제외":
                replace_text(row, "N", "")
    if seen != criteria.keys() | MANUAL_LEVELS.keys():
        raise ValueError("System Evidence 31개 코드가 정확히 일치하지 않습니다.")
    rows = {int(row.get("r")): row for row in data}
    replace_text(rows[3], "B", "인터뷰 54개 + SE 31개 = 85개. 1~5 정수 또는 N/A. 미확보·대상 없음은 N/A, L1은 확인된 부재. 비율 임계값은 본 진단 기준이며 Microsoft 인증 기준 아님")
    validation = root.find(f"{Q}dataValidations/{Q}dataValidation")
    validation.set("type", "custom")
    validation.set("sqref", f"M5:M{max(rows)}")
    validation.set("error", "1~5 정수 또는 N/A만 입력하세요.")
    validation.set("prompt", "미확보·조회 실패·대상 없음은 N/A")
    validation.attrib.pop("operator", None)
    validation.find(f"{Q}formula1").text = 'OR(M5="",M5="N/A",AND(ISNUMBER(M5),M5=INT(M5),M5>=1,M5<=5))'
    second = validation.find(f"{Q}formula2")
    if second is not None:
        validation.remove(second)
    patched[SHEET_CRITERIA] = xml_bytes(root, raw)

    raw = patched.get(SHEET_QUESTIONS, archive.read(SHEET_QUESTIONS))
    root = ET.fromstring(raw)
    for row in root.findall(f"{Q}sheetData/{Q}row"):
        for cell in list(row):
            text = value(cell)
            if "▸ Agent 대상 조건부 접근" in text:
                text = "\n\n".join(
                    block for block in text.split("\n\n")
                    if not block.startswith("▸ Agent 대상 조건부 접근")
                )
                replace_text(row, cell_ref(cell.get("r"))[0], text)
            if "▸ 적대적 시험" in text:
                text = "\n\n".join(
                    block for block in text.split("\n\n") if "▸ 적대적 시험" not in block
                )
                replace_text(row, cell_ref(cell.get("r"))[0], text)
            if "(추가 제안)" in text:
                replace_text(row, cell_ref(cell.get("r"))[0], text.replace(" (추가 제안)", ""))
            elif "점수 산정" in text and "포함하지 않음" in text:
                lines = [
                    line for line in text.splitlines()
                    if not any(marker in line for marker in ("추가 제안 12개", "추가 제안 13개"))
                ]
                replace_text(row, cell_ref(cell.get("r"))[0], "\n".join([*lines, NOTE]))
    summary_row = root.find(f"{Q}sheetData/{Q}row[@r='8']")
    for domain, column in DOMAIN_COLUMN.items():
        summaries = []
        for row in data:
            number = row.get("r")
            code = value(row.find(f"{Q}c[@r='B{number}']"))
            if code in criteria and value(row.find(f"{Q}c[@r='C{number}']")) == domain:
                product = PRODUCTS.get(code, "Microsoft Entra Agent ID" if criteria[code].get("requires") else "Azure API")
                summaries.append(f"▸ {code} {criteria[code]['title']}\n  [{product}]")
            elif code in MANUAL_LEVELS and value(row.find(f"{Q}c[@r='C{number}']")) == domain:
                title = value(row.find(f"{Q}c[@r='F{number}']")).split("\n", 1)[0]
                summaries.append(f"▸ {code} {title}")
        if summaries and summary_row is not None:
            replace_text(summary_row, column, "\n\n".join(summaries))
    notes_row = root.find(f"{Q}sheetData/{Q}row[@r='10']")
    if notes_row is not None:
        replace_text(notes_row, "B", NOTE + "\n- API 구성·기록의 항목별 충족률로 평가. 제품별 조회 범위와 분모는 기준표 참조")
    patched[SHEET_QUESTIONS] = xml_bytes(root, raw)

    raw = archive.read(SHEET_SCORING)
    root = ET.fromstring(raw)
    data = root.find(f"{Q}sheetData")
    example = {int(row.get("r")): row for row in data}
    if (
        value(example[46].find(f"{Q}c[@r='C46']")) == "OE-SY-22"
        and value(example[47].find(f"{Q}c[@r='C47']")) == "OE-SY-23"
    ):
        replace_text(example[46], "C", "OE-SY-22")
        old = example[46].find(f"{Q}c[@r='D46']")
        audit_score = deepcopy(example[47].find(f"{Q}c[@r='D47']"))
        audit_score.set("r", "D46")
        audit_score.set("s", old.get("s", "0"))
        example[46].insert(list(example[46]).index(old), audit_score)
        example[46].remove(old)
        replace_text(example[47], "C", "")
        replace_text(example[47], "D", "")
    # Rows 1-58 remain the original worked example; the actual assessment is separate.
    for row in list(data):
        if int(row.get("r")) >= 61:
            data.remove(row)
    new_formulas: list[str] = []

    def append(number: int, values: dict[str, str]) -> None:
        row = ET.SubElement(data, f"{Q}row", {"r": str(number), "ht": "40", "customHeight": "1"})
        for column, text in values.items():
            ref = f"{column}{number}"
            if text.startswith("="):
                cell = ET.SubElement(row, f"{Q}c", {"r": ref, "s": "51"})
                ET.SubElement(cell, f"{Q}f").text = text[1:]
                new_formulas.append(ref)
            else:
                row.append(text_cell(ref, "23" if number == 63 else "61", text))

    append(61, {"B": "실제 평가 집계 - 시트 4 입력 점수 연동 (인터뷰 54개 + System Evidence 31개)"})
    append(62, {"B": "빈칸·N/A는 평균 제외. 4개 인터뷰 관점과 SE 확보 시 영역 산정, 6개 영역 확보 시 종합 산정. 미확보는 0점 아님"})
    headers = ("영역", "Process", "People", "Data", "Technology", "System Evidence", "인터뷰 평균", "괴리", "최종 점수", "Level", "상태")
    append(63, dict(zip("BCDEFGHIJKL", headers, strict=True)))
    for number, domain in enumerate(("1. Demand", "2. Design", "3. Build", "4. Deploy", "5. Operate", "6. Optimize"), 64):
        values = {"B": domain}
        for column, perspective in zip("CDEFG", headers[1:6], strict=True):
            numbers = groups[(domain, perspective)]
            refs = ",".join(f"'{SOURCE_SHEET}'!M{n}" for n in numbers)
            values[column] = f'=IF(COUNT({refs})=0,"",ROUND(AVERAGE({refs}),1))'
        values.update({
            "H": f'=IF(COUNT(C{number}:F{number})<4,"",ROUND(AVERAGE(C{number}:F{number}),1))',
            "I": f'=IF(COUNT(G{number}:H{number})<2,"",H{number}-G{number})',
            "J": f'=IF(COUNT(G{number}:H{number})<2,"",IF(I{number}>=$C$29,ROUND(G{number}+$C$30,1),H{number}))',
            "K": f'=IF(COUNT(J{number})=0,"",LOOKUP(J{number},$C$21:$C$25,$D$21:$D$25))',
            "L": f'=IF(COUNT(J{number})=0,"판정 보류",IF(I{number}>=$C$29,"인터뷰-실측 괴리","미보정"))',
        })
        append(number, values)
    append(71, {
        "B": "종합 점수",
        "J": '=IF(COUNT(J64:J69)<6,"",ROUND(AVERAGE(J64:J69),1))',
        "K": '=IF(COUNT(J71)=0,"",LOOKUP(J71,$C$21:$C$25,$D$21:$D$25))',
        "L": '=IF(COUNT(J64:J69)<6,"판정 보류","6개 영역 집계")',
    })
    merges = root.find(f"{Q}mergeCells")
    for ref in ("B61:L61", "B62:L62"):
        if not any(cell.get("ref") == ref for cell in merges):
            ET.SubElement(merges, f"{Q}mergeCell", {"ref": ref})
    merges.set("count", str(len(merges)))
    root.find(f"{Q}dimension").set("ref", "B2:L71")
    columns = root.find(f"{Q}cols")
    for index in range(10, 13):
        if not any(int(col.get("min")) <= index <= int(col.get("max")) for col in columns):
            ET.SubElement(columns, f"{Q}col", {"min": str(index), "max": str(index), "width": "22", "customWidth": "1"})
    patched[SHEET_SCORING] = xml_bytes(root, raw)
    raw = archive.read("xl/workbook.xml")
    root = ET.fromstring(raw)
    calc = root.find(f"{Q}calcPr")
    if calc is None:
        calc = ET.SubElement(root, f"{Q}calcPr")
    calc.attrib.update({"calcMode": "auto", "fullCalcOnLoad": "1", "forceFullCalc": "1"})
    patched["xl/workbook.xml"] = xml_bytes(root, raw)
    if "xl/calcChain.xml" in archive.namelist():
        raw = archive.read("xl/calcChain.xml")
        root = ET.fromstring(raw)
        for cell in list(root):
            if cell.get("r") in new_formulas and cell.get("i") == "5":
                root.remove(cell)
        for ref in new_formulas:
            ET.SubElement(root, f"{Q}c", {"r": ref, "i": "5"})
        patched["xl/calcChain.xml"] = xml_bytes(root, raw)
    return patched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(merge_assessment(args.source, args.output))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"오류: {exc}\n")


if __name__ == "__main__":
    main()
