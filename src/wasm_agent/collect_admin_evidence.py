from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from wasm_agent.azure import EvidenceStore
from wasm_agent.models import AdminEvidenceExport, Collection, ProposalFinding

ENVIRONMENTS_URL = "https://api.powerplatform.com/environmentmanagement/environments?api-version=2024-10-01"
COMMANDS = {
    "powerplatform.environments": ENVIRONMENTS_URL,
    "powerplatform.environment_roles": "Get-AdminPowerAppEnvironmentRoleAssignment",
    "powerplatform.dlp_policies": "Get-AdminDlpPolicy",
    "purview.activity_explorer": "Export-ActivityExplorerData",
}
TITLES = {
    "DM-SY-02": "Power Platform 환경·역할 할당 관측",
    "DS-SY-04": "Power Platform DLP 정책 관측",
    "BI-SY-10": "Power Platform 환경 유형·보호 수준 관측",
    "OT-SY-30": "Purview AI·DLP 활동 증적 관측",
}
SOURCES = {
    "DM-SY-02": ("powerplatform.environments", "powerplatform.environment_roles"),
    "DS-SY-04": ("powerplatform.dlp_policies",),
    "BI-SY-10": ("powerplatform.environments",),
    "OT-SY-30": ("purview.activity_explorer",),
}
LIMITS = {
    "DM-SY-02": "역할 할당 수는 고유 Maker 사용자 수가 아니며, 공식 역할 cmdlet은 비 Dataverse 환경의 관리자 접근 범위",
    "DS-SY-04": "정책 개수만으로 커넥터 분류·차단·환경 적용 또는 정책 실효성을 입증하지 않음",
    "BI-SY-10": "관리자에게 보이는 환경 목록·원본 type/protectionLevel이며 개발·운영 분리와 관리형 운영 기준 충족을 입증하지 않음",
    "OT-SY-30": "민감 데이터 접근·분류·DLP 이벤트는 유출 확정이 아님. Agent별 귀속·전체 잠재 노출·조치 완료는 별도 증거 필요",
}


def read_admin_evidence(
    path: Path, tenant: str, now: datetime, store: EvidenceStore,
) -> Collection:
    raw = path.read_bytes()
    export = AdminEvidenceExport.model_validate_json(raw)
    if str(uuid.UUID(export.tenant_id)) != str(uuid.UUID(tenant)):
        raise ValueError("관리자 내보내기의 테넌트가 수집 대상과 다릅니다.")
    if export.exported_at > now + timedelta(minutes=5):
        raise ValueError("관리자 내보내기 시각이 현재 시각보다 미래입니다.")
    if not export.tenant_verified and any(read.completed for read in export.reads):
        raise ValueError("테넌트 미검증 관리자 내보내기를 성공 자료로 사용할 수 없습니다.")
    if len({read.source for read in export.reads}) != len(export.reads):
        raise ValueError("관리자 내보내기에 같은 조회 원천이 중복되었습니다.")
    for read in export.reads:
        if read.command != COMMANDS[read.source]:
            raise ValueError("허용된 공식 읽기 명령과 내보내기 원천이 다릅니다.")
        if read.observed_at > export.exported_at:
            raise ValueError("내보내기 시각보다 미래의 관측 자료입니다.")
        if read.environments and read.source != "powerplatform.environments":
            raise ValueError("환경 목록을 다른 명령 결과로 사용할 수 없습니다.")
        if read.source == "powerplatform.environments" and read.completed and read.object_count != len(read.environments):
            raise ValueError("환경 목록과 확인된 건수가 일치하지 않습니다.")
    ref = store.save("administrator-export:" + hashlib.sha256(raw).hexdigest(), {
        "source_type": export.source_type, "tenant_verified": export.tenant_verified,
        "export": export.model_dump(mode="json"), "input_sha256": hashlib.sha256(raw).hexdigest(),
        "verification_limit": "승인된 별도 관리자 내보내기. 진단 SP의 직접 API 조회가 아니며 파일 해시는 원천 인증 서명이 아님",
    })
    for read in export.reads:
        read.evidence_refs = [ref]
    return Collection(collected_at=now, admin_evidence=export.reads)


def admin_observations(data: Collection) -> list[ProposalFinding]:
    if not data.admin_evidence and not data.facts.get("admin_evidence_requested"):
        return []
    reads = {read.source: read for read in data.admin_evidence}
    results = []
    for code, sources in SOURCES.items():
        relevant = [reads[source] for source in sources if source in reads]
        completed = [read for read in relevant if read.completed]
        failures = [read for read in relevant if not read.completed]
        summary = "; ".join(
            f"{read.command}: {read.object_count}건 ({read.observed_at.isoformat()})"
            for read in completed
        ) or "별도 관리자 읽기 증적 미제공 또는 조회 실패"
        detail = "; ".join(f"{read.command}: {read.detail}" for read in failures)
        results.append(ProposalFinding(
            code=code, title=TITLES[code], area=(
                "1. Demand" if code.startswith("DM") else "2. Design" if code.startswith("DS")
                else "3. Build" if code.startswith("BI") else "6. Optimize"
            ),
            status="일부 수집" if completed else "수집 불가",
            observation=summary + ("; " + detail if detail else ""),
            metrics={
                source: {
                    "object_count": reads[source].object_count, "completed": reads[source].completed,
                    "counts": reads[source].counts, "scope": reads[source].scope,
                    "environment_types": dict(Counter(
                        environment.environment_type or "미확인" for environment in reads[source].environments
                    )) if reads[source].completed and source == "powerplatform.environments" else None,
                    "protection_levels": dict(Counter(
                        environment.protection_level or "미확인" for environment in reads[source].environments
                    )) if reads[source].completed and source == "powerplatform.environments" else None,
                } if source in reads else None for source in sources
            },
            reason=failures[0].reason if failures else None if completed else "not_found",
            limit=LIMITS[code] + ". 기존 평가 기준 유지·점수 보류. 진단 SP가 아닌 별도 관리자 읽기 증적",
            evidence_refs=sorted({ref for read in relevant for ref in read.evidence_refs}),
            evidence_only=True,
        ))
    return results
