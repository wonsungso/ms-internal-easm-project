from __future__ import annotations

import os
import uuid
from pathlib import Path

from wasm_agent.models import Collection, Finding
from wasm_agent.reporting.compact import (
    atomic_write,
    json_bytes,
    load_result,
    normalize_result,
    snapshot_path,
)
from wasm_agent.reporting.presentation import customer_document, html_document
from wasm_agent.reporting.workbook import write_workbook

__all__ = ["load_result", "write_reports"]


def write_reports(data: Collection, findings: list[Finding], output: Path, mode: str = "live") -> None:
    output.mkdir(parents=True, exist_ok=True)
    result = normalize_result(data, findings, output, mode)
    normalized = Collection.model_validate(result["collection"])
    rows = [Finding.model_validate(row) for row in result["findings"]]
    document = customer_document(normalized, rows, output, mode, evidence=result["evidence"])
    missing = result["provenance"]["unattached_evidence"]
    if missing:
        document.heading("첨부하지 못한 증거")
        document.records(["증거 참조", "확인 상태"], [
            ["evidence:" + item["id"], item["detail"]] for item in missing
        ])
    workbook = output / f".report.{uuid.uuid4().hex}.pending.xlsx"
    try:
        write_workbook(normalized, rows, workbook, mode)
        atomic_write(snapshot_path(output), json_bytes(result))
        atomic_write(output / "report.html", html_document(document).encode("utf-8"))
        os.replace(workbook, output / "report.xlsx")
    finally:
        workbook.unlink(missing_ok=True)
