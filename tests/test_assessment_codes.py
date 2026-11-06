from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from scripts.merge_assessment import MANUAL_LEVELS
from wasm_agent.assessment_codes import REVISION_4_CODES
from wasm_agent.models import load_criteria
from wasm_agent.report import load_result
from wasm_agent.report_template import CRITERIA_SHEET, assessment_template_path


def test_codes_follow_approved_continuous_sequence() -> None:
    expected = [
        f"{prefix}-SY-{number:02}"
        for prefix, start, end in (
            ("DM", 1, 3), ("DS", 4, 9), ("BI", 10, 16),
            ("DP", 17, 19), ("OE", 20, 26), ("OT", 27, 31),
        )
        for number in range(start, end + 1)
    ]
    assert list(REVISION_4_CODES.values()) == expected
    assert set(load_criteria()["items"]) | MANUAL_LEVELS.keys() == set(expected)
    sheet = load_workbook(assessment_template_path())[CRITERIA_SHEET]
    actual = [row[1].value for row in sheet if "-SY-" in str(row[1].value)]
    assert actual == expected


def test_revision_four_codes_migrate_once_without_moving_scores_or_evidence(tmp_path: Path) -> None:
    payload = {
        "schema_version": 1,
        "collection": {
            "facts": {"assessment_revision": 4, "proposal_incomplete": ["OE-SY-15"]},
            "agents": [{"se_codes": list(REVISION_4_CODES)}],
            "proposals": [{"code": "BI-SY-11"}],
            "proposal_observations": [{"code": "BI-SY-08"}],
            "issues": [{"collector": "proposal_OE-SY-15"}],
        },
        "findings": [
            {"se_code": code, "metric_value": index, "level": "L2", "evidence_refs": ["evidence:original"]}
            for index, code in enumerate(REVISION_4_CODES)
        ],
        "evidence": {"original": {"se_code": "BI-SY-08", "payload": "unaltered original API evidence"}},
    }
    source = tmp_path / "raw-data-20261105T000000Z.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    result = load_result(tmp_path)
    assert [row["se_code"] for row in result["findings"]] == list(REVISION_4_CODES.values())
    assert [row["metric_value"] for row in result["findings"]] == list(range(31))
    assert result["evidence"] == payload["evidence"]
    assert result["collection"]["proposals"][0]["code"] == "BI-SY-14"
    assert result["collection"]["proposal_observations"][0]["code"] == "BI-SY-11"
    assert result["collection"]["issues"][0]["collector"] == "proposal_OE-SY-22"
    assert result["collection"]["facts"] == {"assessment_revision": 5, "proposal_incomplete": ["OE-SY-22"]}
    source.write_text(json.dumps(result), encoding="utf-8")
    assert load_result(tmp_path) == result


def test_current_evaluation_code_is_not_retired_red_team(tmp_path: Path) -> None:
    payload = {
        "schema_version": 1, "collection": {"facts": {"assessment_revision": 5}},
        "findings": [{"se_code": "BI-SY-11", "level": "L3", "metric_value": 1}],
    }
    (tmp_path / "raw-data-20261105T000000Z.json").write_text(json.dumps(payload), encoding="utf-8")
    assert load_result(tmp_path) == payload


def test_unknown_future_revision_fails_instead_of_remapping_current_codes(tmp_path: Path) -> None:
    payload = {"schema_version": 1, "collection": {"facts": {"assessment_revision": 99}}}
    (tmp_path / "raw-data-20261105T000000Z.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="지원되지 않는 심사 기준 버전"):
        load_result(tmp_path)
