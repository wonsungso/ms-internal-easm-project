from __future__ import annotations

import re
import sysconfig
import xml.etree.ElementTree as ET
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import quoteattr
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook

TEMPLATE_NAME = "assessment-result-template.xlsx"
CRITERIA_SHEET = "4. 질문별 평가 기준"
RESULT_SHEET = "6. 수집 결과"
COLLECTION_METHODS = {
    "DM-SY-01": "M365 Admin Center → Agents → Settings",
    "DM-SY-02": "Power Platform Admin Center → Environments → 권한",
    "DM-SY-03": "M365 Admin Center → Agents → All agents",
    "DS-SY-04": "Power Platform Admin Center → Policies → Data policies",
    "DS-SY-05": "Entra → Agents → Agent identities / Blueprints",
    "DS-SY-06": "Azure → Microsoft Foundry → Model deployments",
    "DS-SY-07": "Azure → Foundry / App Service → Networking",
    "DS-SY-08": "Microsoft Foundry → Agents → Tools",
    "DS-SY-09": "Microsoft Foundry → Agents → Tools",
    "BI-SY-10": "Power Platform Admin Center → Environments",
    "BI-SY-11": "Microsoft Foundry → Evaluation",
    "BI-SY-12": "Azure → Defender for Cloud → Recommendations",
    "BI-SY-13": "Azure → Microsoft Foundry → Content filters",
    "BI-SY-14": "Foundry → Agent versions / App Service → Configuration",
    "BI-SY-15": "Foundry → Agent metadata / Azure → Tags",
    "BI-SY-16": "Azure → Policy → Compliance",
    "DP-SY-17": "M365 Admin Center → Agents → All agents (Agent 365)",
    "DP-SY-18": "M365 Admin Center → Agents → Details / Users",
    "DP-SY-19": "Entra → Agents → Blueprints / Foundry → Agents",
    "OE-SY-20": "Entra → Agents → Owners / Sponsors",
    "OE-SY-21": "Entra → Agents → Permissions",
    "OE-SY-22": "Azure → Monitor → Diagnostic settings",
    "OE-SY-23": "Azure → Foundry / App Service → Identity / IAM",
    "OE-SY-24": "Azure → Monitor → Alerts",
    "OE-SY-25": "Azure → Monitor → Action groups",
    "OE-SY-26": "Azure → Resource overview / Log Analytics → Retention",
    "OT-SY-27": "Agent 365 → Shadow AI Detection",
    "OT-SY-28": "Azure → Monitor → Metrics",
    "OT-SY-29": "Azure → Cost Management → Cost analysis",
    "OT-SY-30": "Microsoft Purview → DSPM for AI / Activity explorer",
    "OT-SY-31": "Azure → Cost Management → Budgets",
}
_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def assessment_template_path() -> Path:
    source = Path(__file__).resolve().parents[2] / "docs" / TEMPLATE_NAME
    installed = Path(sysconfig.get_path("data")) / "share" / "wasm-agent" / TEMPLATE_NAME
    path = source if source.is_file() else installed
    if not path.is_file():
        raise FileNotFoundError(f"평가 결과 템플릿을 찾을 수 없습니다: {path}")
    return path


def load_report_template() -> tuple[Workbook, bytes]:
    content = assessment_template_path().read_bytes()
    book = load_workbook(BytesIO(content), keep_links=False, rich_text=True)
    if len(book.worksheets) != 5 or CRITERIA_SHEET not in book.sheetnames:
        raise ValueError("평가 결과 템플릿에는 원본 1~5번 시트와 질문별 평가 기준이 필요합니다.")
    return book, content


def preserve_template_parts(path: Path, template: bytes) -> None:
    """Keep source metadata and formula caches that openpyxl does not round-trip."""
    with ZipFile(BytesIO(template)) as source, ZipFile(path) as generated:
        parts = {name: generated.read(name) for name in generated.namelist()}
        changed = {
            "[Content_Types].xml", "xl/workbook.xml",
            "xl/_rels/workbook.xml.rels", "xl/styles.xml",
        }
        for name in source.namelist():
            if name not in changed:
                parts[name] = source.read(name)
        workbook = source.read("xl/workbook.xml").decode("utf-8")
        new_workbook = ET.fromstring(generated.read("xl/workbook.xml"))
        sheets = new_workbook.find(f"{_MAIN}sheets")
        if sheets is None or len(sheets) < 6:
            raise ValueError("수집 결과 시트가 생성되지 않았습니다.")
        additions = "".join(
            "<sheet name=" + quoteattr(sheet.attrib["name"])
            + " sheetId=" + quoteattr(sheet.attrib["sheetId"])
            + " r:id=" + quoteattr(sheet.attrib[_DOC_REL + "id"]) + "/>"
            for sheet in list(sheets)[5:]
        )
        workbook, replaced = re.subn(r"</sheets>", additions + "</sheets>", workbook, count=1)
        if replaced != 1:
            raise ValueError("원본 템플릿의 시트 목록을 확장할 수 없습니다.")
        workbook = re.sub(r'\bactiveTab="\d+"', 'activeTab="5"', workbook, count=1)
        parts["xl/workbook.xml"] = workbook.encode("utf-8")
        for index in range(1, 6):
            name = f"xl/worksheets/sheet{index}.xml"
            parts[name] = re.sub(rb'\btabSelected="1"', b'tabSelected="0"', parts[name])
        relationships = ET.fromstring(generated.read("xl/_rels/workbook.xml.rels"))
        original_rels = ET.fromstring(source.read("xl/_rels/workbook.xml.rels"))
        for index, relation in enumerate(original_rels):
            kind = relation.attrib["Type"].rsplit("/", 1)[-1]
            if kind in ("sharedStrings", "calcChain"):
                relation = deepcopy(relation)
                relation.set("Id", f"templatePreserved{index}")
                relationships.append(relation)
            elif kind not in ("worksheet", "styles", "theme"):
                raise ValueError(f"지원되지 않는 템플릿 통합 문서 관계: {kind}")
        parts["xl/_rels/workbook.xml.rels"] = ET.tostring(relationships, encoding="utf-8")
        types = ET.fromstring(generated.read("[Content_Types].xml"))
        keys = {(item.tag, item.get("PartName"), item.get("Extension")) for item in types}
        for item in ET.fromstring(source.read("[Content_Types].xml")):
            key = (item.tag, item.get("PartName"), item.get("Extension"))
            if key not in keys:
                types.append(deepcopy(item))
                keys.add(key)
        parts["[Content_Types].xml"] = ET.tostring(types, encoding="utf-8")
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    path.write_bytes(output.getvalue())
