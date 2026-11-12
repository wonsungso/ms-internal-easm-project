from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.utils import range_boundaries
from openpyxl.worksheet.worksheet import Worksheet

from easm_agent.models import (
    AgentEvidence,
    Collection,
    EntraAgentIdentity,
    Finding,
    ModelDeployment,
    ProposalObservation,
)
from easm_agent.report_excel import write_workbook
from easm_agent.report_resources import resource_names, resource_summary

NOW = datetime(2026, 11, 9, tzinfo=UTC)
SID = "11111111-1111-4111-8111-111111111111"
ACCOUNT = f"/subscriptions/{SID}/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/account"


@pytest.mark.parametrize(("platform", "category"), [("custom", "자체 Agent"), ("langchain", "LangChain Agent")])
def test_host_names_keep_custom_classification(platform: str, category: str) -> None:
    host = AgentEvidence(
        collected_at=NOW, platform=platform, agent_id="support", agent_name="support-host",
        subscription_id=SID, resource_id=f"/subscriptions/{SID}/resourceGroups/rg/providers/Microsoft.Web/sites/support",
        detection_confidence="tag",
    )
    data = Collection(collected_at=NOW, agents=[host])
    resources = resource_names(data, "BI-SY-15")
    assert len(resources) == 1 and resources[0].category == category
    assert resources[0].name == "support-host"
    assert [row.identifier for row in resource_names(data, "OT-SY-28")] == [host.resource_id.lower()]


def resource_rows(book: Workbook) -> tuple[Worksheet, range]:
    sheet = book["7. 수집결과 근거"]
    table = next(table for table in sheet.tables.values() if table.tableColumns[1].name == "리소스 유형")
    _, header, _, last = range_boundaries(table.ref)
    return sheet, range(header + 1, last + 1)


def test_same_names_are_not_deduplicated_across_resource_ids() -> None:
    data = Collection(collected_at=NOW)
    for sid in (SID, "22222222-2222-4222-8222-222222222222"):
        data.deployments.append(ModelDeployment(
            subscription_id=sid, resource_id=f"{ACCOUNT.replace(SID, sid)}/deployments/shared-name",
            account_id=ACCOUNT.replace(SID, sid), name="shared-name", model=None, version=None, format=None,
        ))
    resources = resource_names(data, "DS-SY-06")
    assert len(resources) == 2
    assert all(row.name == "shared-name" and row.resource_group == "rg" for row in resources)
    assert SID in resource_summary(resources)
    assert "22222222-2222-4222-8222-222222222222" in resource_summary(resources)


def test_graph_permission_names_do_not_include_unrelated_azure_agents() -> None:
    data = Collection(collected_at=NOW, entra_agent_identities=[
        EntraAgentIdentity(identity_id="identity", display_name="graph-agent"),
    ], agents=[AgentEvidence(
        collected_at=NOW, platform="langchain", agent_id="host", agent_name="azure-host",
        detection_confidence="tag",
    )])
    assert [row.name for row in resource_names(data, "OE-SY-21")] == ["graph-agent"]


def test_tool_lists_include_only_mcp_agents_and_preserve_missing_names() -> None:
    data = Collection(collected_at=NOW, proposal_observations=[
        ProposalObservation(code="DS-SY-08", subject="function", kind="agent_tools",
                            values={"mcp_approval_modes": []}),
        ProposalObservation(code="DS-SY-08", subject="mcp-id", kind="agent_tools",
                            values={"mcp_approval_modes": ["always"]}),
    ])
    resources = resource_names(data, "DS-SY-08")
    assert len(resources) == 1 and resources[0].identifier == "mcp-id"
    assert resources[0].name is None


def test_full_list_keeps_every_resource_while_summary_explicitly_points_to_it(tmp_path: Path) -> None:
    data = Collection(collected_at=NOW, facts={"entra_agents_complete": True})
    for index in range(8):
        data.entra_agent_identities.append(EntraAgentIdentity(
            identity_id=f"identity-{index}", display_name=f"agent-{index}",
        ))
    finding = Finding(se_code="OE-SY-21", level="L5", scope="in_scope", metric_value=1, rationale="verified")
    path = tmp_path / "resources.xlsx"
    write_workbook(data, [finding], path)
    book = load_workbook(path)
    sheet = book["6. 수집 결과"]
    row = next(row for row in range(5, 90) if sheet.cell(row, 2).value == "OE-SY-21")
    text = sheet.cell(row, 10).value
    assert "agent-0" in text and "외 5개" in text and "전체 8개" in text
    assert "11. 리소스 목록" not in text and len(book.sheetnames) == 10
    names, rows = resource_rows(book)
    resource_table = next(table for table in names.tables.values() if table.tableColumns[1].name == "리소스 유형")
    assert [column.name for column in resource_table.tableColumns] == [
        "SE 코드", "리소스 유형", "리소스 이름", "구독 ID", "리소스 그룹", "식별자",
    ]
    assert sheet["G4"].value == "확인상태"
    assert {names.cell(row, 3).value for row in rows} == {
        f"agent-{index}" for index in range(8)
    }
    assert finding.level == "L5" and sheet.cell(row, 13).value == 5


def test_resource_names_cannot_be_excel_formulas(tmp_path: Path) -> None:
    data = Collection(collected_at=NOW, entra_agent_identities=[EntraAgentIdentity(
        identity_id="identity", display_name='=HYPERLINK("https://example.invalid","click")',
    )])
    path = tmp_path / "safe.xlsx"
    write_workbook(data, [Finding(
        se_code="OE-SY-21", level="N/A", scope="in_scope", rationale="unknown",
    )], path)
    sheet, rows = resource_rows(load_workbook(path))
    cell = sheet.cell(rows.start, 3)
    assert cell.data_type == "s" and cell.hyperlink is None


def test_resource_name_emails_are_masked_in_summary_and_full_list(tmp_path: Path) -> None:
    data = Collection(collected_at=NOW, entra_agent_identities=[EntraAgentIdentity(
        identity_id="identity", display_name="person@example.invalid",
    )])
    path = tmp_path / "masked.xlsx"
    write_workbook(data, [Finding(
        se_code="OE-SY-21", level="N/A", scope="in_scope", rationale="unknown",
    )], path)
    book = load_workbook(path)
    for sheet_name in ("6. 수집 결과", "7. 수집결과 근거"):
        assert not any(
            "person@example.invalid" in str(cell.value) for row in book[sheet_name] for cell in row
        )
