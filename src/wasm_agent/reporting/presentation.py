from __future__ import annotations

import html
import json
import os
import re
from collections import Counter
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import quote, unquote

from wasm_agent.models import AgentEvidence, Collection, EvaluationRun, Finding
from wasm_agent.utils.evidence import redact

LABELS = {
    "permission_denied": "조회 권한 부족",
    "feature_unavailable": "현재 환경에서 조회 기능 제공 안 됨",
    "license_missing": "필요 라이선스 확인 또는 추가 필요",
    "not_found": "확인 자료 없음",
    "error": "조회 중 오류 발생",
    "in_scope": "진단 범위에 포함",
    "partial": "진단 범위 일부 - 조직 전체 판정 아님",
    "out_of_scope": "진단 범위 밖",
    "N/A": "판정 보류",
    "null": "확인 자료 없음",
    "foundry": "Microsoft Foundry",
    "langchain": "LangChain 탐지 후보",
    "manual": "수동 등록",
    "other": "기타 플랫폼",
    "tag": "태그를 근거로 탐지",
    "name_heuristic": "이름을 근거로 추정 - Agent 여부 추가 확인 필요",
}
SE_NAMES = {
    "DS-SY-06": "허용 모델 사용 관리",
    "BI-SY-08": "배포 전 Agent 품질 평가",
    "BI-SY-09": "AI 워크로드 보안 관리",
    "OE-SY-16": "Agent 활동 감사 로그 관리",
    "OT-SY-18": "장기 미사용 Agent 관리",
    "OT-SY-19": "Agent별 비용 식별 및 배분",
}
FIELD_NAMES = {
    "tenant_id": "테넌트", "subscription_id": "구독", "resource_group": "리소스 그룹",
    "agent_version": "Agent 버전", "resource_id": "리소스",
    "hosting_type": "호스팅 유형", "owner": "담당자", "sponsor": "업무 책임자",
    "model": "사용 모델", "model_version": "모델 버전", "model_resource_id": "모델 리소스",
    "tools": "연결 도구", "created_at": "생성 시각", "deployed_at": "배포 시각",
    "last_used_at": "마지막 사용 시각", "cost_30d": "최근 30일 비용", "currency": "통화",
    "usage_30d": "최근 30일 사용량", "usage_30d.calls": "최근 30일 호출 수",
    "usage_30d.tokens": "최근 30일 토큰 수", "calls_90d": "최근 90일 호출 수",
    "usage_coverage_start": "사용 관측 시작 시각",
    "evaluated_before_deploy": "배포 전 평가 여부", "guardrail_applied": "안전장치 적용 여부",
}
COLLECTORS = {
    "subscription": "구독 목록", "inventory": "리소스 목록",
    "foundry_projects": "Foundry 프로젝트", "foundry_agents": "Foundry Agent 목록",
    "foundry_evaluations": "품질 평가 이력", "model_deployments": "모델 배포 목록",
    "agent_usage": "Agent 사용 이력", "cost": "비용", "security": "보안 권고",
    "logs": "감사 로그", "langchain": "LangChain 탐지",
}
RATIOS = {"DS-SY-06", "BI-SY-08", "OT-SY-18", "OT-SY-19"}
EVALUATION_FIELDS = [
    "평가 실행 이력", "일치 실행 수", "완료 실행 수", "평가 실행 상태",
    "평가 목록 조회 상태", "평가 이력 근거", "배포 전 평가", "평가 문항 집계",
]
EVALUATION_ITEM_FIELDS = {
    "passed_items": "통과 문항",
    "failed_items": "실패 문항",
    "errored_items": "오류 문항",
    "total_items": "전체 문항",
}


def agent_evaluations(agent: AgentEvidence, data: Collection) -> list[EvaluationRun]:
    if not all((agent.agent_id, agent.agent_version, agent.resource_id, agent.subscription_id)):
        return []
    return [
        run for run in data.evaluations
        if run.agent_id == agent.agent_id
        and run.agent_version == agent.agent_version
        and run.project_id == agent.resource_id
        and run.subscription_id == agent.subscription_id
    ]


def evaluation_status(status: str | None) -> str:
    return {
        "completed": "완료", "succeeded": "완료", "failed": "실패",
        "running": "실행 중", "in_progress": "실행 중", "queued": "대기 중",
        "cancelled": "취소됨", "canceled": "취소됨",
    }.get((status or "").casefold(), "상태 확인 자료 없음" if not status else readable(status))


def evaluation_item_counts(run: EvaluationRun) -> dict[str, str]:
    result = {}
    for field, label in EVALUATION_ITEM_FIELDS.items():
        count = getattr(run, field, None)
        result[label] = "확인불가" if count is None else f"{count}문항"
    return result


def evaluation_item_summary(run: EvaluationRun) -> str:
    return ", ".join(f"{label} {count}" for label, count in evaluation_item_counts(run).items())


def evaluation_columns(agent: AgentEvidence, data: Collection) -> dict[str, str]:
    runs = agent_evaluations(agent, data)
    completed = sum((run.status or "").casefold() in ("completed", "succeeded") for run in runs)
    states = Counter(evaluation_status(run.status) for run in runs)
    complete = agent.resource_id in data.facts.get("evaluation_complete_projects", [])
    if any(item.collector == "foundry_evaluations"
           and item.subscription_id in (None, agent.subscription_id) for item in data.issues):
        complete = False
    inventory = ("해당 프로젝트 평가 목록 조회 완료 - 수집 범위와 시점에 한함" if complete else
                 "평가 목록 조회 완전성 부족 - 누락된 실행이 있을 수 있음")
    if not all((agent.agent_id, agent.agent_version, agent.resource_id, agent.subscription_id)):
        inventory += "; Agent 식별자, 버전, 프로젝트 또는 구독 연결 자료 부족"
    if agent.deployed_at is None:
        before_deploy = "판정 보류 - 배포 시각 확인 자료 없음"
    elif agent.evaluated_before_deploy is None:
        before_deploy = "판정 보류 - 평가 완료 시각과 배포 시각 연결 확인 필요"
    elif agent.evaluated_before_deploy:
        before_deploy = "배포 전 평가 이력 확인"
    else:
        before_deploy = "배포 전 평가 이력 미확인 - 미수행 확정 아님"
    details = "; ".join(
        f"실행 {run.run_id}, 상태 {evaluation_status(run.status)}, Agent {run.agent_id}, "
        f"버전 {run.agent_version}, 프로젝트 {run.project_id}, "
        f"{evaluation_item_summary(run)}, "
        f"완료 시각 {readable(run.completed_at)}, 증거 {', '.join(run.evidence_refs) or '확인 자료 없음'}"
        for run in runs
    ) or "Agent 식별자 + 버전 + 프로젝트 + 구독이 일치하는 수집 실행 없음 - 미수행 확정 아님"
    return dict(zip(EVALUATION_FIELDS, [
        "평가 완료 이력 확인" if completed else "평가 이력 미확인",
        f"{len(runs)}건", f"{completed}건",
        ", ".join(f"{state} {count}건" for state, count in sorted(states.items()))
        or "일치 실행 상태 확인 자료 없음",
        inventory, details, before_deploy,
        "; ".join(f"실행 {run.run_id}: {evaluation_item_summary(run)}" for run in runs)
        or "확인불가 - 일치하는 수집 실행 없음",
    ], strict=True))


def readable(value: Any) -> str:
    if value is None or value == "":
        return "확인 자료 없음"
    if isinstance(value, bool):
        return "확인됨" if value else "해당하지 않음"
    text = str(redact(value)).replace("\u2014", "-").replace("\u2013", "-")
    for key, label in LABELS.items():
        text = re.sub(r"(?<![\w/-])" + re.escape(key) + r"(?![\w/-])", label, text)
    return text


def metric(finding: Finding) -> str:
    if finding.metric_value is None:
        return "확인 자료 없음" + (" - 분모 확인 안됨" if finding.se_code in RATIOS else "")
    value = finding.metric_value
    if finding.se_code in RATIOS:
        return f"{value * 100:.2f}%"
    return f"{value:g}" + ("일" if finding.se_code == "OE-SY-16" else "건")


def issue_action(reason: str) -> str:
    return {
        "permission_denied": "관리자가 대상 범위의 조회 역할을 확인한 뒤 같은 범위를 다시 수집하세요.",
        "feature_unavailable": "지원되는 조회 기능과 서비스 구성을 확인하고 별도 증빙을 확보하세요.",
        "license_missing": "관리자가 라이선스와 기능 활성화 여부를 확인한 뒤 다시 수집하세요.",
        "not_found": "대상 존재 여부와 조회 기간을 확인하고 별도 증빙을 확보하세요.",
        "error": "오류 설명과 서비스 상태를 확인한 뒤 다시 수집하세요.",
    }[reason]


class Document:
    """Render the same escaped content as readable Markdown and semantic HTML."""

    def __init__(self) -> None:
        self.markdown: list[str] = []
        self.html: list[str] = []
        self.section_open = False

    def heading(self, title: str, level: int = 2) -> None:
        self.markdown.extend(["#" * level + " " + self.md(title), ""])
        if level == 2:
            if self.section_open:
                self.html.append("</section>")
            self.html.append("<section>")
            self.section_open = True
        self.html.append(f"<h{level}>{html.escape(title)}</h{level}>")

    def paragraph(self, text: str) -> None:
        self.markdown.extend(["- " + self.md(text), ""])
        self.html.append(f"<ul class='notes'><li>{html.escape(readable(text))}</li></ul>")

    @staticmethod
    def md(value: Any) -> str:
        return (html.escape(readable(value)).replace("|", "&#124;")
                .replace("\n", "<br>").replace("\\", "&#92;")
                .replace("[", "&#91;").replace("]", "&#93;")
                .replace("`", "&#96;"))

    def records(self, headers: list[str], rows: list[list[Any]]) -> None:
        if not rows:
            self.paragraph("표시할 수집 기록 없음")
            return
        for row in rows:
            if len(headers) == 2:
                self.paragraph(f"{headers[0]}: {readable(row[0])} - {headers[1]}: {readable(row[1])}")
                continue
            title = f"{headers[0]}: {readable(row[0])}"
            if headers[0] in ("구독", "Agent"):
                title += f" - {headers[1]}: {readable(row[1])}"
            self.begin_details(title)
            self.html.append("<ul class='record'>")
            for label, value in zip(headers, row, strict=True):
                self.markdown.append(f"- **{self.md(label)}**: {self.md(value)}")
                self.html.append(f"<li><strong>{html.escape(label)}</strong>: "
                                 f"{html.escape(readable(value))}</li>")
            self.html.append("</ul>")
            self.end_details()
        self.markdown.append("")

    def begin_details(self, title: str) -> None:
        opening = f"<details><summary>{html.escape(readable(title))}</summary>"
        self.markdown.extend([opening, ""])
        self.html.append(opening)

    def end_details(self) -> None:
        self.markdown.extend(["", "</details>", ""])
        self.html.append("</details>")

    def references(self, refs: list[str], links: EvidenceLinks) -> None:
        self.begin_details("증거 참조 " + str(len(refs)) + "개")
        if not refs:
            self.paragraph("연결된 증거 참조가 없습니다. 자료가 없다는 뜻이며 미실시를 확정하지 않습니다.")
        self.html.append("<ul>")
        for ref in refs:
            link = links.local(ref)
            label = readable(ref)
            if link:
                self.markdown.append(
                    f"- 증거: <code>{html.escape(label)}</code> - [마스킹된 파일 열기]({link})"
                )
                self.html.append(f"<li><code>{html.escape(label)}</code> - "
                                 f"<a href='{link}'>마스킹된 파일 열기</a></li>")
            else:
                self.markdown.append(
                    f"- 증거: <code>{html.escape(label)}</code> - 파일 확인불가 - 안전한 로컬 파일 연결 불가"
                )
                self.html.append(f"<li><code>{html.escape(label)}</code>"
                                 " - 파일 확인불가 - 안전한 로컬 파일 연결 불가</li>")
        self.markdown.append("")
        self.html.append("</ul>")
        self.end_details()


class EvidenceLinks:
    def __init__(
        self, data: Collection, output: Path, evidence: dict[str, Any] | None = None,
    ) -> None:
        self.output = output.resolve()
        directory = data.facts.get("evidence_directory")
        self.root = Path(directory).absolute() if directory and self.safe(str(directory)) else None
        self.evidence = evidence or {}
        self.cache: dict[str, str | None] = {}

    @staticmethod
    def safe(value: str) -> bool:
        decoded = unquote(value).replace("\\", "/")
        return (
            not decoded.startswith("//")
            and ".." not in decoded.split("/")
            and not any(ord(char) < 32 for char in decoded)
            and "://" not in decoded
            and not re.search(r"(^|/)[^/]*:", decoded[2:] if re.match(r"^[A-Za-z]:/", decoded) else decoded)
        )

    def local(self, reference: str) -> str | None:
        if reference.startswith("evidence:"):
            identifier = reference.removeprefix("evidence:")
            return "#evidence-" + identifier if identifier in self.evidence else None
        if reference in self.cache:
            return self.cache[reference]
        source = self.source(reference)
        relative = quote(Path(os.path.relpath(source, self.output)).as_posix(), safe="/") if source else None
        self.cache[reference] = relative
        return relative

    def source(self, reference: str) -> Path | None:
        if self.root is None or not self.root.is_dir() or not self.safe(reference):
            return None
        path = Path(reference)
        # Reject Windows drive-relative paths, including on non-Windows test hosts.
        windows = PureWindowsPath(reference)
        if windows.drive and not windows.is_absolute():
            return None
        candidates = [path] if path.is_absolute() else [
            self.output / path, self.root / path,
            Path.cwd() / path,
        ]
        for candidate in candidates:
            try:
                if any(part.is_symlink() for part in (candidate, *candidate.parents)):
                    continue
                resolved = candidate.resolve()
                if not resolved.is_relative_to(self.root):
                    continue
                if resolved.suffix.lower() != ".json" or not resolved.is_file():
                    continue
            except (OSError, ValueError):
                continue
            return resolved
        return None


def customer_document(
    data: Collection, findings: list[Finding], output: Path, mode: str,
    evidence: dict[str, Any] | None = None,
) -> Document:
    doc = Document()
    links = EvidenceLinks(data, output, evidence)
    doc.heading("EASM 거버넌스 진단 보고서", 1)
    doc.paragraph("제품: EASM (Enterprise Agent Service Management) 거버넌스 진단/수집 툴")
    doc.paragraph("CLI: wasm-agent")
    doc.paragraph("수집 대상: Azure 구독 리소스, Microsoft Foundry Agent·평가·모델 배포, "
                  "Azure 자체 호스팅 Agent 탐지 후보(LangChain), 수동 등록 Agent")
    doc.paragraph(f"실행 시각(UTC): {data.collected_at.isoformat()}")
    doc.paragraph("수집 방식: " + {
        "fixture": "저장된 수집 자료",
        "live": "실시간 조회",
    }.get(mode, readable(mode)))
    doc.paragraph("레벨은 판정 초안입니다. 조회 실패는 낮은 단계나 0건으로 바꾸지 않습니다. "
                  "L4/L5는 비율뿐 아니라 해당 정책과 자동화 운영 증거가 필요합니다.")
    doc.heading("Agent 인벤토리 요약")
    doc.records(["항목", "수집 결과"], [
        ["조회 대상 구독", f"{len(data.subscriptions)}개"],
        ["목록 수집 완료 구독", f"{len(data.completed_subscriptions)}개"],
        ["등록 Agent 및 탐지 후보", f"{len(data.agents)}개"],
        ["보조 모델 배포", f"{len(data.deployments)}개 - Agent 수에 포함하지 않음"],
        ["수집 실패 또는 확인 필요 항목", f"{len(data.issues)}개"],
    ])
    counts = Counter((a.subscription_id or "구독 미확인 또는 외부 등록", a.platform) for a in data.agents)
    count_rows = [[sid, LABELS.get(platform, platform), f"{count}개",
                   "목록 수집 완료" if sid in data.completed_subscriptions else "목록 완전성 확인 안됨"]
                  for (sid, platform), count in sorted(counts.items())]
    for sid in data.subscriptions:
        if not any(a.subscription_id == sid for a in data.agents):
            count_rows.append([sid, "발견된 항목 없음",
                               "0개" if sid in data.completed_subscriptions else "확인 자료 없음",
                               "목록 수집 완료" if sid in data.completed_subscriptions
                               else "목록 수집 실패 - 0개로 단정할 수 없음"])
    doc.heading("구독별 및 플랫폼별 개수")
    doc.records(["구독", "플랫폼", "Agent 및 후보 수", "목록 확인 상태"], count_rows)
    doc.heading("실제로 수집한 항목")
    doc.records(["수집 항목", "이번 결과 수", "해석"], [
        [name, f"{len(getattr(data, field))}개", explanation]
        for field, name, explanation in [
            ("agents", "Agent 및 탐지 후보", "수동 등록과 이름 추정 후보가 포함될 수 있음"),
            ("resources", "Azure 리소스 목록", "Agent 수와 같지 않음"),
            ("deployments", "보조 모델 배포 목록", "허용 모델 비교 자료이며 Agent가 아님"),
            ("evaluations", "품질 평가 실행 이력", "Agent 버전 및 배포 시각 연결이 필요"),
            ("costs", "비용 명세", "공유 리소스 비용은 Agent별 중복 귀속하지 않음"),
            ("security", "보안 권고", "수집된 권고의 위험도와 조치 상태 확인"),
            ("logs", "로그 설정", "활동 로그의 실제 관측 여부와 별도"),
        ]
    ])
    doc.paragraph("0개는 반환된 자료 수입니다. 수집 실패나 권한 부족이 있으면 실제 대상이 없다는 뜻이 아닙니다.")
    doc.heading("Agent 및 탐지 후보 상세")
    evaluations = [evaluation_columns(agent, data) for agent in data.agents]
    doc.records(["이름", "구독", "플랫폼", "탐지 근거", "사용 모델", "담당자", "최근 30일 비용",
               "평가 실행 이력", "일치 실행 수", "완료 실행 수", "배포 전 평가"],
              [[a.agent_name, a.subscription_id, a.platform, a.detection_confidence, a.model,
                redact(a.owner, "owner"),
                f"{a.cost_30d:g} {a.currency or '통화 확인 안됨'}"
                if a.cost_30d is not None else None,
                *[summary[field] for field in
                  ("평가 실행 이력", "일치 실행 수", "완료 실행 수", "배포 전 평가")]]
               for a, summary in zip(data.agents, evaluations, strict=True)])
    doc.paragraph("태그 및 이름 기반 탐지는 Agent임을 확정하지 않습니다. "
                  "수동 등록한 이기종 항목은 Azure 판정의 분모에서 제외합니다.")
    doc.heading("Agent별 평가 실행 이력 상세")
    doc.paragraph("평가 실행 이력과 배포 전 평가 여부는 별개입니다. "
                  "Agent 식별자, 버전, 프로젝트와 구독이 모두 일치하는 실행만 연결합니다. "
                  "완료 상태의 실행이 있으면 평가 완료 이력을 확인한 것이며, "
                  "평가 이력 미확인은 평가 미수행 확정이 아닙니다. "
                  "배포일이 없으면 평가가 완료되어도 배포 전 평가는 판정 보류합니다.")
    doc.paragraph("평가 완료, 모든 문항 통과, 배포 전 평가는 서로 다른 의미입니다. "
                  "평가가 완료되어도 실패 또는 오류 문항이 있을 수 있습니다. "
                  "문항 집계는 서비스가 제공한 값만 표시하며 누락된 값은 확인불가로 남깁니다. "
                  "다른 집계값으로 누락된 값을 추정하거나 0으로 바꾸지 않습니다. "
                  "질문/답변 본문은 수집하거나 표시하지 않습니다.")
    for agent, summary in zip(data.agents, evaluations, strict=True):
        doc.begin_details("평가 실행 - " + readable(agent.agent_name))
        doc.paragraph(summary["평가 실행 이력"] + " - " + summary["평가 목록 조회 상태"])
        doc.paragraph("실행 상태: " + summary["평가 실행 상태"])
        runs = agent_evaluations(agent, data)
        doc.records(["실행 식별자", "Agent 식별자", "버전", "프로젝트", "실행 상태", "완료 시각",
                   *EVALUATION_ITEM_FIELDS.values()],
                  [[run.run_id, run.agent_id, run.agent_version, run.project_id,
                    evaluation_status(run.status), run.completed_at,
                    *evaluation_item_counts(run).values()] for run in runs])
        if not runs:
            doc.paragraph(summary["평가 이력 근거"])
        for run in runs:
            doc.paragraph("평가 실행 근거: " + readable(run.run_id))
            doc.references(run.evidence_refs, links)
        doc.end_details()
    doc.heading("필드 누락과 조회 상태")
    doc.paragraph("확인 자료 없음은 값이 0이거나 기능을 사용하지 않는다는 뜻이 아닙니다. "
                  "빈 도구 목록은 반환된 목록이 비어 있다는 뜻이고, 도구 값 누락은 확인하지 못했다는 뜻입니다. "
                  "담당자와 업무 책임자 등 개인 식별 정보는 마스킹된 값으로 표시합니다.")
    missing_rows = []
    for agent in data.agents:
        fields = {key for key, value in agent.model_dump().items() if value is None}
        if agent.usage_30d is not None:
            fields.update(
                "usage_30d." + key for key in ("calls", "tokens")
                if getattr(agent.usage_30d, key) is None
            )
        fields.update(agent.field_status)
        for field in sorted(fields):
            status = agent.field_status.get(field)
            missing_rows.append([
                agent.agent_name, FIELD_NAMES.get(field, "추가 속성 (" + field + ")"),
                status.reason if status else "not_found",
                status.detail if status else "응답에서 확인하지 못함 - 미설정으로 단정할 수 없음",
            ])
    doc.records(["Agent", "확인하지 못한 항목", "원인", "설명"], missing_rows)
    doc.heading("SE 항목별 실측 및 판정 초안")
    doc.records(["SE 항목", "진단 범위", "실측값", "판정", "보류 또는 조회 사유", "인터뷰 단계", "차이 확인"],
              [[f.se_code + " - " + SE_NAMES.get(f.se_code, "관리 항목"), f.scope,
                metric(f), f.level, f.reason or "해당 없음", f.interview_level,
                "인터뷰와 실측 차이 검토 필요" if f.gap_flag else "차이 경고 없음"]
               for f in findings])
    doc.paragraph("비율은 퍼센트로 표시합니다. 분모와 귀속 또는 관측 기간을 확정하지 못하면 비율을 만들지 않습니다. "
                  "보안 권고는 건수, 로그 보관은 일수입니다. 인터뷰 단계가 없으면 비교하지 않습니다.")
    doc.records(["SE 항목", "비율의 분모 또는 관측 대상"], [
        ["DS-SY-06", "전체 모델 배포 중 허용 목록에 일치하는 배포 비율"],
        ["BI-SY-08", "운영 Azure Agent 중 배포 전 평가를 확인한 비율"],
        ["BI-SY-09", "조회된 보안 권고 중 미조치 고위험 권고 건수"],
        ["OE-SY-16", "조회된 로그 설정에서 확인한 최소 보관 일수"],
        ["OT-SY-18", "Azure Agent 중 90일 미사용으로 확인한 비율 - 관측 기간 확보 필요"],
        ["OT-SY-19", "조회 범위 전체 비용 중 개별 Agent에 단독 귀속 가능한 비용 비율"],
    ])
    doc.paragraph("실측값은 판정 결과를 표시한 것으로, 탐지 후보 수만으로 분모를 다시 만들지 않습니다.")
    for finding in findings:
        doc.begin_details(finding.se_code + " - " + SE_NAMES.get(finding.se_code, "관리 항목") + " - 판정 근거")
        doc.paragraph("판정 근거: " + readable(finding.rationale))
        doc.paragraph("다음 조치: " + readable(finding.next_step))
        doc.references(finding.evidence_refs, links)
        doc.end_details()
    doc.heading("수집 실패 항목별 원인과 다음 조치")
    doc.records(["구독", "수집 항목", "조회 대상", "원인", "상세 설명", "필요 조회 역할", "다음 조치"], [
        [item.subscription_id, COLLECTORS.get(item.collector, "추가 수집 항목 (" + item.collector + ")"),
         item.target, item.reason, item.detail,
         ", ".join(item.required_roles) or "수집 결과에 역할 안내 없음 - 관리자가 조회 범위 확인",
         issue_action(item.reason)] for item in data.issues
    ])
    if not data.issues:
        doc.paragraph("기록된 수집 실패 항목이 없습니다. 모든 필드가 확인되었다는 뜻은 아닙니다.")
    for index, item in enumerate(data.issues, 1):
        if item.evidence_refs:
            doc.heading(f"수집 실패 {index} - 증거 참조", 3)
            doc.references(item.evidence_refs, links)
    doc.heading("관측 한계와 증거 파일 안내")
    for text in [
        "진단 범위 일부로 표시한 항목은 Azure에서 확인한 범위에 한정해 해석합니다.",
        "30일 비용 및 90일 사용 현황은 해당 기간의 관측 자료가 확보된 범위에서 확인합니다.",
        "배포 시각, 평가 완료 시각, Agent 버전 연결이 없으면 배포 전 평가 여부를 확정할 수 없습니다.",
        "공유 모델 사용량과 공유 리소스 비용은 개별 Agent의 실측으로 중복 귀속하지 않습니다.",
        "증거 원본은 마스킹된 참조입니다. 지정된 증거 폴더 안에서 존재가 확인된 JSON 파일만 "
        "보고서 안에 원본 JSON으로 내장합니다. evidence:<id>는 ZIP data.json의 evidence 키와 연결됩니다. "
        "외부 URL, 입력 경로의 상위 폴더 이동, 심볼릭 링크, "
        "허용 폴더 밖 파일은 링크하지 않습니다.",
        "필요 역할은 수집기가 기록한 조회 역할 안내입니다.",
    ]:
        doc.paragraph(text)
    doc.heading("용어 풀이")
    doc.records(["용어", "쉬운 설명"], [
        ["Agent", "모델과 도구를 이용해 업무를 수행하는 프로그램. 탐지 후보는 추가 확인 필요"],
        ["SE", "시스템에서 수집한 자료를 근거로 확인하는 관리 항목"],
        ["분모", "비율 계산에 포함할 전체 대상. 일부 목록이 누락되면 전체 비율을 확정할 수 없음"],
        ["판정 보류", "자료, 조회 권한 또는 조건이 부족해 단계를 정하지 않음. 낮은 단계와 다름"],
        ["L1-L5", "관리 성숙도 단계의 초안. 정책 및 운영 증거와 함께 해석해야 함"],
        ["증거 참조", "판정에 사용한 마스킹된 수집 자료의 위치. 참조만으로 적용 여부를 보장하지 않음"],
    ])
    for identifier, payload in sorted((evidence or {}).items()):
        doc.html.append(
            f'<details id="evidence-{html.escape(identifier, quote=True)}">'
            f"<summary>마스킹된 원본 JSON - evidence:{html.escape(identifier)}</summary>"
            "<pre>" + html.escape(json.dumps(payload, ensure_ascii=False, indent=2))
            + "</pre></details>"
        )
    return doc


def html_document(doc: Document) -> str:
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>EASM 거버넌스 진단 보고서</title><style>"
        "body{font:16px/1.6 system-ui;margin:32px auto;padding:0 20px;max-width:1400px;color:#182230}"
        "h2{border-bottom:2px solid #ccd3de;margin-top:36px}"
        "li{margin:8px 0;overflow-wrap:anywhere}.notes{padding-left:24px}"
        ".record{padding-left:24px}summary{cursor:pointer;font-weight:600;overflow-wrap:anywhere}"
        "details{background:#f7f9fc;padding:16px;margin:12px 0}code{overflow-wrap:anywhere}"
        "a{color:#064faa}</style></head><body><main>"
        "<nav aria-label='결과 파일'><a href='report.xlsx'>Excel 체크리스트·원시 데이터</a></nav>"
        + "\n".join(doc.html) + ("</section>" if doc.section_open else "")
        + "</main></body></html>"
    )
