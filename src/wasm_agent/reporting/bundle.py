from __future__ import annotations

import hashlib
import html
import json
import os
import uuid
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from wasm_agent.evaluators.engine import evidence_refs
from wasm_agent.models import Collection
from wasm_agent.reporting.workbook import portable_workbook
from wasm_agent.utils.evidence import redact

RESULT_FILES = (
    "report.html", "report.md", "report.xlsx", "customer_summary.csv", "customer_inventory.csv",
    "inventory.json", "inventory.csv", "collection.json", "findings.json", "summary.csv", "cost_monthly.csv",
)


def create_bundle(data: Collection, output: Path, mode: str = "live") -> Path:
    output = output.resolve()
    root_value = data.facts.get("evidence_directory")
    root = Path(root_value).resolve() if isinstance(root_value, str) else None
    sources: dict[Path, str] = {}
    omitted: list[dict[str, str]] = []
    for ref in evidence_refs(data):
        source = Path(ref)
        if (
            root is not None and source.is_absolute() and not source.is_symlink()
            and source.resolve().is_relative_to(root) and source.is_file() and source.suffix == ".json"
        ):
            sources[source.resolve()] = "evidence/" + root.name + "/" + source.name
        else:
            omitted.append({"reference": source.name, "reason": "이번 실행의 마스킹된 API 증적 파일이 아니므로 제외"})
    replacements: dict[str, str] = {}
    for source, target in sources.items():
        replacements[str(source)] = target
        relative = os.path.relpath(source, output).replace("\\", "/")
        replacements[relative] = target
        replacements[quote(relative, safe="/")] = target
    if root is not None:
        replacements[str(root)] = "evidence/" + root.name

    def portable(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: portable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [portable(item) for item in value]
        if isinstance(value, str):
            return replacements.get(value, value)
        return value

    stamp = data.collected_at.strftime("%Y%m%dT%H%M%SZ")
    kind = "results" if mode == "live" else "example"
    archive = output / f"wasm-agent-{kind}-{stamp}-{uuid.uuid4().hex[:6]}.zip"
    manifest: dict[str, Any] = {
        "product": "EASM", "collected_at": data.collected_at.isoformat(),
        "mode": mode, "files": [], "unattached_evidence": omitted,
        "credentials_included": False,
    }
    created = False
    try:
        with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as bundle:
            created = True
            def put(name: str, payload: bytes) -> None:
                bundle.writestr(name, payload)
                manifest["files"].append({
                    "path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                })

            for name in RESULT_FILES:
                source = output / name
                if source.is_symlink() or not source.is_file():
                    raise ValueError(f"필수 결과 파일을 확인할 수 없습니다: {name}")
                if source.suffix == ".xlsx":
                    payload = portable_workbook(source.read_bytes(), replacements)
                elif source.suffix == ".json":
                    payload = json.dumps(
                        portable(redact(json.loads(source.read_text(encoding="utf-8")))),
                        ensure_ascii=False, indent=2,
                    ).encode("utf-8")
                else:
                    text = source.read_text(encoding="utf-8-sig")
                    for before, after in sorted(replacements.items(), key=lambda pair: -len(pair[0])):
                        text = text.replace(html.escape(before, quote=True), after)
                        text = text.replace(json.dumps(before, ensure_ascii=False)[1:-1], after)
                        text = text.replace(before, after)
                    payload = (("\ufeff" if source.suffix == ".csv" else "") + text).encode("utf-8")
                put(name, payload)
            for source, target in sorted(sources.items()):
                payload = json.dumps(
                    redact(json.loads(source.read_text(encoding="utf-8"))),
                    ensure_ascii=False, indent=2,
                ).encode("utf-8")
                put(target, payload)
            notice = (
                "# EASM 진단 결과\n\n"
                "- 압축을 푼 뒤 report.html을 여세요.\n"
                "- customer_summary.csv와 customer_inventory.csv는 Excel에서 열 수 있습니다.\n"
                "- report.xlsx는 체크리스트와 원시 데이터의 Excel 테이블입니다.\n"
                "- evidence 폴더의 API 응답은 마스킹된 증적입니다.\n"
                "- manifest.json에서 파일 해시와 첨부하지 않은 증거를 확인하세요.\n"
                "- 인증서·개인키·로그인 캐시·환경 설정·이전 실행 결과는 포함하지 않습니다.\n"
                f"- 데이터 구분: {'실제 환경 수집' if mode == 'live' else '개발용 가짜 응답'}.\n"
                f"- 첨부하지 않은 증거 참조: {len(omitted)}건. 부족한 자료를 확보했다는 뜻이 아닙니다.\n"
            )
            put("DOWNLOAD-README.md", notice.encode("utf-8"))
            bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(archive) as check:
            if check.testzip() is not None:
                raise ValueError("압축 파일 무결성 검사 실패")
    except (OSError, ValueError, zipfile.BadZipFile):
        if created:
            archive.unlink(missing_ok=True)
        raise
    print(f"다운로드용 결과 ZIP: {archive}")
    if omitted:
        print(f"주의: 첨부하지 않은 증거 참조 {len(omitted)}건 - ZIP의 manifest.json을 확인하세요.")
    return archive
