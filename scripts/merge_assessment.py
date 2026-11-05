"""원본 평가 모델 XLSX에 Azure 추가 제안 13개를 같은 시트/서식으로 병합한다.

원본 zip에서 시트 2, 4 XML만 직접 고치고 나머지 파트(스타일, 시트 1/3/5, 민감도 라벨 등)는
바이트 그대로 보존한다. 추가 제안의 L1-L5는 승인 전 초안이라 점수 산정 시트(5)는 건드리지 않는다.
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

from scripts.proposal_levels import LEVELS
from wasm_agent.proposals import DOMAINS, PRODUCTS, TITLES

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHEET = "4. 질문별 평가 기준"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
Q = f"{{{NS}}}"
SHEET_QUESTIONS = "xl/worksheets/sheet2.xml"
SHEET_CRITERIA = "xl/worksheets/sheet4.xml"
DOMAIN_COLUMN = {"2. Design": "E", "3. Build": "F", "4. Deploy": "G", "5. Operate": "H", "6. Optimize": "I"}
NOTE = (
    "- 추가 제안 13개(DS-SY-07~09, BI-SY-10~14, OE-SY-17~20, OT-SY-21)의 L1~L5는 MS Learn 근거 초안(승인 전)이며 "
    "시트 5 점수 산정·보정에는 포함하지 않음"
)
ROW_HEIGHT = "25.05"
FIRST_DATA_ROW = 5


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
        patched = {
            SHEET_CRITERIA: patch_criteria(archive.read(SHEET_CRITERIA), strings),
            SHEET_QUESTIONS: patch_questions(archive.read(SHEET_QUESTIONS), strings),
        }
        result = BytesIO()
        with ZipFile(result, "w", ZIP_DEFLATED) as out:
            for entry in archive.infolist():
                out.writestr(entry, patched.get(entry.filename, archive.read(entry.filename)))
    if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(raw).digest():
        raise ValueError("작업 중 원본이 변경되었습니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result.getvalue())
    return {"merged_proposals": len(DOMAINS), "source_sha256": hashlib.sha256(raw).hexdigest()}


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
