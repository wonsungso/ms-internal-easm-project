from __future__ import annotations

from typing import Any

ASSESSMENT_REVISION = 5
REVISION_4_CODES = {
    f"{prefix}-SY-{number:02}": f"{prefix}-SY-{number + offset:02}"
    for prefix, start, end, offset in (
        ("DM", 1, 3, 0), ("DS", 4, 9, 0), ("BI", 7, 13, 3),
        ("DP", 10, 12, 7), ("OE", 13, 19, 7), ("OT", 17, 21, 10),
    )
    for number in range(start, end + 1)
}


def migrate_revision_4_codes(result: dict[str, Any]) -> None:
    collection = result["collection"]
    for row in result.get("findings", []):
        row["se_code"] = REVISION_4_CODES.get(row["se_code"], row["se_code"])
    for agent in collection.get("agents", []):
        agent["se_codes"] = [REVISION_4_CODES.get(code, code) for code in agent.get("se_codes", [])]
    for field in ("proposals", "proposal_observations"):
        for row in collection.get(field, []):
            row["code"] = REVISION_4_CODES.get(row["code"], row["code"])
    for row in collection.get("issues", []):
        if row["collector"].startswith("proposal_"):
            code = row["collector"].removeprefix("proposal_")
            row["collector"] = "proposal_" + REVISION_4_CODES.get(code, code)
    facts = collection.setdefault("facts", {})
    if "proposal_incomplete" in facts:
        facts["proposal_incomplete"] = [
            REVISION_4_CODES.get(code, code) for code in facts["proposal_incomplete"]
        ]
    facts["assessment_revision"] = ASSESSMENT_REVISION
