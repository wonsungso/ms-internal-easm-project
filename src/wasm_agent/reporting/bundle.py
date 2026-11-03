from __future__ import annotations

import hashlib
import json
import os
import uuid
import zipfile
from pathlib import Path
from typing import Any

from wasm_agent.models import Collection
from wasm_agent.reporting.compact import atomic_write, json_bytes, load_result, snapshot_path

RESULT_FILES = ("report.html", "report.xlsx", "data.json")


def create_bundle(data: Collection, output: Path, mode: str = "live") -> Path:
    """Package the pending write_reports snapshot instead of an earlier ZIP."""
    snapshot = snapshot_path(output)
    result = (
        json.loads(snapshot.read_text(encoding="utf-8")) if snapshot.is_file()
        else load_result(output)
    )
    if result["mode"] != mode:
        raise ValueError("수집한 데이터 구분과 지정한 mode가 다릅니다.")
    payloads: dict[str, bytes] = {}
    files: list[dict[str, Any]] = []
    for name in RESULT_FILES[:2]:
        source = output / name
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"필수 결과 파일을 확인할 수 없습니다: {name}")
        payloads[name] = source.read_bytes()
        files.append({
            "path": name, "bytes": len(payloads[name]),
            "sha256": hashlib.sha256(payloads[name]).hexdigest(),
        })
    result["manifest"] = {
        "product": "EASM", "mode": mode, "collected_at": data.collected_at.isoformat(),
        "files": files, "credentials_included": False,
        "data_hash_scope": "UTF-8 JSON with indent=2, excluding manifest",
        "data_sha256": hashlib.sha256(json_bytes({
            key: value for key, value in result.items() if key != "manifest"
        })).hexdigest(),
    }
    payloads["data.json"] = json_bytes(result)
    archive = output / "results.zip"
    staging = output / f".results.{uuid.uuid4().hex}.pending"
    try:
        with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as bundle:
            for name, payload in payloads.items():
                bundle.writestr(name, payload)
        with zipfile.ZipFile(staging) as check:
            if check.testzip() is not None or set(check.namelist()) != set(RESULT_FILES):
                raise ValueError("압축 파일 무결성 검사 실패")
        atomic_write(snapshot_path(output), payloads["data.json"])
        os.replace(staging, archive)
    finally:
        staging.unlink(missing_ok=True)
    print(f"다운로드용 결과 ZIP: {archive}")
    return archive
