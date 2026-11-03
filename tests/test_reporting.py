from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import load_workbook

from wasm_agent.cli import main
from wasm_agent.evaluators.engine import evaluate
from wasm_agent.models import Collection, EvaluationRun, Finding, Issue
from wasm_agent.reporting.presentation import evaluation_columns
from wasm_agent.reporting.reports import load_result, write_reports
from wasm_agent.utils.evidence import redact
from wasm_agent.utils.settings import load_yaml

ROOT = Path(__file__).parents[1]


@pytest.fixture(autouse=True)
def isolated_result_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "wasm_agent.reporting.compact.STATE_ROOT",
        tmp_path.parent / (tmp_path.name + "-runtime"),
    )


def evaluation_rows(output: Path) -> list[dict[str, str]]:
    data = Collection.model_validate(load_result(output)["collection"])
    return [evaluation_columns(agent, data) for agent in data.agents]


def workbook_rows(output: Path, sheet: str) -> list[dict]:
    book = load_workbook(output / "report.xlsx")
    try:
        rows = list(book[sheet].values)
        return [dict(zip(rows[0], row, strict=True)) for row in rows[1:]]
    finally:
        book.close()


def test_fixture_cli_is_offline_and_outputs_common_schema(tmp_path: Path) -> None:
    with patch("wasm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("no Azure calls")):
        assert main([
            "collect", "--config", str(ROOT / "config" / "config.yaml"),
            "--fixture", str(ROOT / "tests" / "fixtures" / "three_subscriptions.json"),
            "--output-dir", str(tmp_path),
        ]) == 0
    result = load_result(tmp_path)
    inventory = result["collection"]["agents"]
    assert len(inventory) == 3
    assert isinstance(inventory, list)
    required = {
        "collected_at", "tenant_id", "subscription_id", "resource_group", "platform",
        "agent_id", "agent_name", "resource_id", "hosting_type", "owner", "sponsor",
        "tags", "model", "tools", "created_at", "last_used_at", "cost_30d", "usage_30d",
        "evaluated_before_deploy", "guardrail_applied", "detection_confidence", "evidence_refs",
        "se_codes", "field_status",
    }
    assert required <= set(inventory[0])
    summary = result["findings"]
    assert len(summary) == 6
    assert "EASM 거버넌스 진단 보고서" in (tmp_path / "report.html").read_text(encoding="utf-8")
    assert {path.name for path in tmp_path.iterdir()} == {"report.html", "report.xlsx", "results.zip"}
    assert "단계 조건" in (tmp_path / "report.html").read_text(encoding="utf-8")


def test_workbook_formula_injection_and_html_are_escaped(tmp_path: Path) -> None:
    data = Collection.model_validate_json((ROOT / "tests" / "fixtures" / "three_subscriptions.json").read_text())
    data.agents[0].agent_name = '=HYPERLINK("https://example.invalid")'
    config = load_yaml(ROOT / "config" / "criteria.yaml")
    rows = evaluate(data, config, load_yaml(ROOT / "config" / "allowed_models.yaml"),
                    load_yaml(ROOT / "config" / "tag_conventions.yaml"))
    rows[0].rationale = "<script>alert(1)</script>"
    write_reports(data, rows, tmp_path, "fixture")
    assert workbook_rows(tmp_path, "Agent 원시데이터")[0]["agent_name"] == data.agents[0].agent_name
    book = load_workbook(tmp_path / "report.xlsx")
    assert all(cell.data_type != "f" and cell.hyperlink is None
               for sheet in book for row in sheet for cell in row)
    book.close()
    content = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "<script>" not in content
    assert "&lt;script&gt;" in content


def report_data() -> Collection:
    return Collection.model_validate_json(
        (ROOT / "tests" / "fixtures" / "three_subscriptions.json").read_text()
    )


def test_customer_reports_explain_states_metrics_and_observation_limits(tmp_path: Path) -> None:
    data = report_data()
    data.agents[0].mark_unknowns()
    data.agents[0].unavailable("owner", "permission_denied", "담당자 조회 권한이 없습니다.")
    data.issues = [Issue(
        subscription_id=data.subscriptions[0], collector="agent_usage",
        target="최근 사용 기록", reason="permission_denied",
        detail="사용 기록을 읽을 수 없습니다.", required_roles=["Monitoring Reader"],
    )]
    findings = [
        Finding(se_code="DS-SY-06", scope="in_scope", metric_value=0.9, level="L3",
                rationale="허용 모델 비율과 정책을 확인했습니다.", next_step="다음 단계 조건: 정책 자동 적용"),
        Finding(se_code="OT-SY-18", scope="partial", level="N/A", reason="permission_denied",
                rationale="관측 기간이 부족합니다.", next_step="조회 권한과 90일 관측 기간을 확인하세요."),
        Finding(se_code="OE-SY-16", scope="partial", metric_value=90, level="L2",
                rationale="보관 기간을 확인했습니다."),
        Finding(se_code="BI-SY-09", scope="partial", metric_value=0, level="N/A",
                rationale="내부 기준 확인이 필요합니다."),
    ]
    write_reports(data, findings, tmp_path, "fixture")
    for filename in ("report.html",):
        text = (tmp_path / filename).read_text(encoding="utf-8")
        for expected in (
            "허용 모델 사용 관리", "90.00%", "90일", "0건", "분모 확인 안됨", "판정 보류",
            "조회 권한 부족", "진단 범위 일부", "Agent 인벤토리 요약", "실제로 수집한 항목",
            "보조 모델 배포", "필드 누락과 조회 상태", "관측 한계", "용어 풀이",
            "Monitoring Reader", "사용 기록을 읽을 수 없습니다.", "같은 범위를 다시 수집",
            "원본은 마스킹된 참조", findings[0].rationale, findings[0].next_step,
            findings[1].rationale, findings[1].next_step,
        ):
            assert expected in text
        for machine_word in ("N/A", "null", "permission_denied", "in_scope", "partial"):
            assert machine_word not in text
    content = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "<pre>" not in content
    assert "<details>" in content
    assert "<ul" in content
    assert "<table" not in content
    assert "<main>" in content


def test_machine_contracts_are_unchanged_in_combined_data(tmp_path: Path) -> None:
    data = report_data()
    findings = [Finding(se_code="DS-SY-06", scope="partial", level="N/A",
                        reason="permission_denied", rationale="근거 <script>",
                        evidence_refs=["fixture://model"])]
    before_data = data.model_dump(mode="json")
    before_findings = [f.model_dump(mode="json") for f in findings]
    write_reports(data, findings, tmp_path)
    result = load_result(tmp_path)
    expected_data = redact(before_data)
    expected_data["facts"]["data_mode"] = "live"
    replacements = {
        item["reference"]: "evidence:" + item["id"]
        for item in result["provenance"]["references"]
    }

    def normalized(value):
        if isinstance(value, dict):
            return {key: normalized(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalized(item) for item in value]
        return replacements.get(value, value) if isinstance(value, str) else value

    assert result["collection"] == normalized(expected_data)
    assert result["findings"] == normalized(redact(before_findings))
    row = result["findings"][0]
    assert {k: v for k, v in row.items() if k != "evidence_refs"} == {
        k: v for k, v in redact(before_findings)[0].items() if k != "evidence_refs"
    }
    assert row["level"] == "N/A"
    assert row["reason"] == "permission_denied"
    assert row["metric_value"] is None
    customer = workbook_rows(tmp_path, "진단 체크리스트")[0]
    assert customer["판정"] == "판정 보류"
    assert customer["지표"] == "확인 자료 없음 - 분모 확인 안됨"
    assert data.model_dump(mode="json") == before_data
    assert [f.model_dump(mode="json") for f in findings] == before_findings


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.links.extend(value for key, value in attrs if key == "href" and value)


def test_all_se_references_link_existing_timestamped_files_without_aliases(tmp_path: Path) -> None:
    timestamp = "20261103T063200Z-abcdef"
    source = tmp_path / "evidence" / timestamp
    source.mkdir(parents=True)
    evidence = source / "0123456789abcdef-12345678.json"
    masked = {"api_key": "[REDACTED]", "response": {"count": 3}}
    evidence.write_text(json.dumps(masked))
    original_bytes = evidence.read_bytes()
    data = report_data()
    data.facts["evidence_directory"] = str(source)
    references = [
        str(evidence), evidence.name, "https://example.invalid/remote.json",
        "../original.json", r"..\original.json", "%2e%2e/original.json",
        "javascript:alert(1)", "//server/share/evidence.json",
        "file:///C:/sensitive.json", "missing.json", "'><script>alert(1)</script>",
    ]
    findings = [Finding(se_code=code, scope="partial", level="N/A", rationale="추가 확인 필요",
                        evidence_refs=references) for code in ("DS-SY-06", "BI-SY-08")]
    output = tmp_path / "reports"
    write_reports(data, findings, output)
    content = (output / "report.html").read_text(encoding="utf-8")
    assert content.count("증거 참조 11개") == 2
    result = load_result(output)
    assert any(item["reference"] == "https://example.invalid/remote.json"
               for item in result["provenance"]["unattached_evidence"])
    assert "<script>" not in content
    parser = LinkParser()
    parser.feed(content)
    evidence_links = [link for link in parser.links if link.startswith("#evidence-")]
    assert len(evidence_links) == 4
    assert len(set(evidence_links)) == 1
    identifier = next(iter(result["evidence"]))
    assert set(evidence_links) == {f"#evidence-{identifier}"}
    assert result["evidence"][identifier] == masked
    assert f'<details id="evidence-{identifier}">' in content
    for link in parser.links:
        assert "://" not in link
        assert not re.search(r"evidence/[a-f0-9]{24}\.json", link)
    assert evidence.read_bytes() == original_bytes
    assert not (output / "evidence").exists()
    missing = {item["reference"] for item in result["provenance"]["unattached_evidence"]}
    assert set(references[2:]) <= missing


@pytest.mark.parametrize("reason, expected", [
    ("permission_denied", "조회 권한 부족"),
    ("feature_unavailable", "현재 환경에서 조회 기능 제공 안 됨"),
    ("license_missing", "필요 라이선스 확인 또는 추가 필요"),
    ("not_found", "확인 자료 없음"),
    ("error", "조회 중 오류 발생"),
])
def test_each_failure_explains_reason_roles_and_action(
    tmp_path: Path, reason: str, expected: str,
) -> None:
    data = Collection.model_validate({
        "collected_at": "2026-11-03T01:00:00Z",
        "subscriptions": ["unfinished"],
        "issues": [{"collector": "cost", "target": "조회 대상", "reason": reason,
                    "detail": "비용 확인 실패", "required_roles": ["Cost Management Reader"]}],
    })
    write_reports(data, [], tmp_path)
    for filename in ("report.html",):
        text = (tmp_path / filename).read_text(encoding="utf-8")
        assert expected in text
        assert reason not in text
        assert "Cost Management Reader" in text
        assert "다음 조치" in text
        assert "목록 수집 실패 - 0개로 단정할 수 없음" in text


def test_untrusted_files_are_not_linked_outside_evidence_root(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "private.json"
    outside.write_text('{"private": true}')
    data = report_data()
    data.facts["evidence_directory"] = str(root)
    findings = [Finding(se_code="DS-SY-06", scope="partial", level="N/A", rationale="자료 없음",
                        evidence_refs=[str(outside)])]
    output = tmp_path / "report"
    write_reports(data, findings, output)
    assert not (output / "evidence").exists()
    assert "안전한 로컬 파일 연결 불가" in (output / "report.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("filename", [
    "0123456789abcdef-12345678.json", "실제 증거(1)'#.json",
])
def test_evidence_links_preserve_existing_names_and_encode_url_characters(
    tmp_path: Path, filename: str,
) -> None:
    output = tmp_path / "report"
    source = output / "evidence" / "20261103T063200Z-abcdef"
    source.mkdir(parents=True)
    evidence = source / filename
    evidence.write_text('{"masked": true}')
    data = report_data()
    data.facts["evidence_directory"] = str(source)
    finding = Finding(se_code="DS-SY-06", scope="partial", level="N/A", rationale="확인 필요",
                      evidence_refs=[str(evidence)])
    write_reports(data, [finding], output)
    parser = LinkParser()
    parser.feed((output / "report.html").read_text(encoding="utf-8"))
    links = [link for link in parser.links if link.startswith("#evidence-")]
    assert len(links) == 1
    assert links[0].removeprefix("#evidence-") in load_result(output)["evidence"]
    assert "'" not in links[0] and " " not in links[0]
    assert list(source.iterdir()) == [evidence]
    assert list((output / "evidence").iterdir()) == [source]
    assert len(load_result(output)["evidence"]) == 1


@pytest.mark.parametrize("configured_root", [True, False])
def test_missing_evidence_and_fixture_refs_never_create_links(
    tmp_path: Path, configured_root: bool,
) -> None:
    output = tmp_path / "report"
    root = tmp_path / "evidence" / "20261103T063200Z-abcdef"
    root.mkdir(parents=True)
    data = report_data()
    data.evaluations = []
    if configured_root:
        data.facts["evidence_directory"] = str(root)
    refs = [
        "fixture://foundry", str(root / "0123456789abcdef-12345678.json"),
        str(output / "inventory.json"),
    ]
    finding = Finding(se_code="DS-SY-06", scope="partial", level="N/A", rationale="확인 필요",
                      evidence_refs=refs)
    write_reports(data, [finding], output)
    for filename in ("report.html",):
        content = (output / filename).read_text(encoding="utf-8")
        assert content.count("파일 확인불가") >= len(refs)
        assert "마스킹된 파일 열기" not in content
    missing = {item["reference"] for item in load_result(output)["provenance"]["unattached_evidence"]}
    assert set(refs) <= missing
    assert not list(root.iterdir())
    assert not (output / "evidence").exists()


def test_agent_evaluation_history_matches_identity_version_project_and_subscription(
    tmp_path: Path,
) -> None:
    data = report_data()
    agent = data.agents[0]
    agent.agent_name = "<script>Agent</script>"
    agent.deployed_at = None
    # Even a stale pre-deploy flag must not imply a known deployment timestamp.
    agent.evaluated_before_deploy = True
    original = data.evaluations[0]
    evidence_directory = tmp_path / "evidence" / "20261103T063200Z-abcdef"
    evidence_directory.mkdir(parents=True)
    data.facts["evidence_directory"] = str(evidence_directory)
    evidence = evidence_directory / "0123456789abcdef-12345678.json"
    evidence.write_text('{"status": "completed"}')
    original.evidence_refs = [str(evidence)]
    data.evaluations.extend([
        original.model_copy(update={"run_id": "running-matched", "status": "running"}),
        original.model_copy(update={"run_id": "failed-matched", "status": "failed"}),
        original.model_copy(update={"run_id": "wrong-version", "agent_version": "999"}),
        original.model_copy(update={"run_id": "wrong-agent", "agent_id": "different"}),
        original.model_copy(update={"run_id": "wrong-project", "project_id": "different"}),
        original.model_copy(update={"run_id": "wrong-subscription", "subscription_id": "different"}),
    ])
    before = data.model_dump(mode="json")
    write_reports(data, [], tmp_path)
    rows = evaluation_rows(tmp_path)
    assert rows[0]["평가 실행 이력"] == "평가 완료 이력 확인"
    assert rows[0]["일치 실행 수"] == "3건"
    assert rows[0]["완료 실행 수"] == "1건"
    assert rows[0]["평가 실행 상태"] == "실패 1건, 실행 중 1건, 완료 1건"
    assert rows[0]["배포 전 평가"] == "판정 보류 - 배포 시각 확인 자료 없음"
    assert "조회 완료" in rows[0]["평가 목록 조회 상태"]
    assert original.run_id in rows[0]["평가 이력 근거"]
    for rejected in ("wrong-version", "wrong-agent", "wrong-project", "wrong-subscription"):
        assert rejected not in rows[0]["평가 이력 근거"]
    assert rows[1]["평가 실행 이력"] == "평가 이력 미확인"
    assert rows[1]["일치 실행 수"] == "0건"
    assert "미수행 확정 아님" in rows[1]["평가 이력 근거"]
    for filename in ("report.html",):
        content = (tmp_path / filename).read_text(encoding="utf-8")
        assert "<script>" not in content
        assert "&lt;script&gt;Agent&lt;/script&gt;" in content
        for expected in ("평가 완료 이력 확인", "평가 이력 미확인", "평가 실행 이력 상세",
                         "배포 전 평가 여부는 별개", "판정 보류 - 배포 시각 확인 자료 없음",
                         original.run_id, "running-matched", "failed-matched",
                         "평가 목록 조회 완전성 부족", "평가 미수행 확정이 아닙니다"):
            assert expected in content
        assert "#evidence-" in content
    assert data.model_dump(mode="json") == before


@pytest.mark.parametrize("status, confirmed", [
    ("completed", True), ("succeeded", True), ("Succeeded", True),
    ("running", False), ("failed", False), (None, False),
])
def test_evaluation_run_status_and_missing_identity_do_not_claim_completion(
    tmp_path: Path, status: str | None, confirmed: bool,
) -> None:
    data = report_data()
    run = data.evaluations[0]
    run.status = status
    data.agents[1].agent_version = None
    data.evaluations.append(EvaluationRun(
        subscription_id=data.agents[1].subscription_id,
        project_id=data.agents[1].resource_id,
        agent_id=data.agents[1].agent_id,
        agent_version=None, run_id="unversioned", status="completed",
    ))
    data.issues = [Issue(
        subscription_id=data.agents[0].subscription_id, collector="foundry_evaluations",
        target=run.project_id, reason="permission_denied", detail="일부 페이지 확인 불가",
    )]
    write_reports(data, [], tmp_path)
    rows = evaluation_rows(tmp_path)
    assert rows[0]["평가 실행 이력"] == (
        "평가 완료 이력 확인" if confirmed else "평가 이력 미확인"
    )
    assert "평가 목록 조회 완전성 부족" in rows[0]["평가 목록 조회 상태"]
    assert rows[1]["평가 실행 이력"] == "평가 이력 미확인"
    assert rows[1]["완료 실행 수"] == "0건"
    assert "연결 자료 부족" in rows[1]["평가 목록 조회 상태"]


class CountedEvaluationRun(EvaluationRun):
    passed_items: int | None = None
    failed_items: int | None = None
    errored_items: int | None = None
    total_items: int | None = None


def test_completed_runs_preserve_passed_failed_and_error_item_counts(tmp_path: Path) -> None:
    data = report_data()
    agent = data.agents[0]
    agent.deployed_at = None
    template = data.evaluations[0].model_dump()
    data.evaluations = [
        CountedEvaluationRun.model_validate({
            **template, "run_id": name, "passed_items": passed,
            "failed_items": failed, "errored_items": 0, "total_items": 3,
        })
        for name, passed, failed in [
            ("정책", 3, 0), ("비용", 2, 1), ("장애", 2, 1), ("출시", 3, 0),
        ]
    ]
    write_reports(data, [], tmp_path)
    row = evaluation_rows(tmp_path)[0]
    assert row["평가 실행 이력"] == "평가 완료 이력 확인"
    assert row["완료 실행 수"] == "4건"
    assert row["배포 전 평가"] == "판정 보류 - 배포 시각 확인 자료 없음"
    for column in ("평가 문항 집계", "평가 이력 근거"):
        assert row[column].count("실패 문항 1문항") == 2
        assert row[column].count("통과 문항 3문항") == 2
        assert row[column].count("오류 문항 0문항") == 4
        assert row[column].count("전체 문항 3문항") == 4
    for filename in ("report.html",):
        content = (tmp_path / filename).read_text(encoding="utf-8")
        for expected in ("통과 문항", "실패 문항", "오류 문항", "전체 문항",
                         "평가 완료, 모든 문항 통과, 배포 전 평가는 서로 다른 의미",
                         "질문/답변 본문은 수집하거나 표시하지 않습니다"):
            assert expected in content
    raw = workbook_rows(tmp_path, "평가 원시데이터")
    assert [item["passed_items"] for item in raw] == [3, 2, 2, 3]
    assert [item["failed_items"] for item in raw] == [0, 1, 1, 0]
    assert [item["errored_items"] for item in raw] == [0, 0, 0, 0]
    assert [item["total_items"] for item in raw] == [3, 3, 3, 3]


@pytest.mark.parametrize("counts, expected", [
    ({}, ("확인불가", "확인불가", "확인불가", "확인불가")),
    ({"passed_items": 2, "total_items": 3}, ("2문항", "확인불가", "확인불가", "3문항")),
    ({"failed_items": 0, "errored_items": 1}, ("확인불가", "0문항", "1문항", "확인불가")),
])
def test_missing_item_counts_are_not_zero_or_inferred(
    tmp_path: Path, counts: dict[str, int], expected: tuple[str, str, str, str],
) -> None:
    data = report_data()
    data.evaluations = [CountedEvaluationRun.model_validate({
        **data.evaluations[0].model_dump(), **counts,
    })]
    write_reports(data, [], tmp_path)
    row = evaluation_rows(tmp_path)[0]
    for label, value in zip(("통과 문항", "실패 문항", "오류 문항", "전체 문항"), expected, strict=True):
        assert f"{label} {value}" in row["평가 이력 근거"]
        assert f"{label} {value}" in row["평가 문항 집계"]
    raw = workbook_rows(tmp_path, "평가 원시데이터")[0]
    for field in ("passed_items", "failed_items", "errored_items", "total_items"):
        assert raw[field] == counts.get(field)
    assert "평가 완료 이력 확인" in row["평가 실행 이력"]


@pytest.mark.parametrize("subscription_count", [0, 1, 7])
def test_easm_brand_scope_dynamic_counts_and_bullet_reports(
    tmp_path: Path, subscription_count: int,
) -> None:
    data = Collection.model_validate({
        "collected_at": "2026-11-03T01:00:00Z",
        "subscriptions": [f"subscription-{index}" for index in range(subscription_count)],
    })
    write_reports(data, [], tmp_path, "fixture")
    for filename in ("report.html",):
        content = (tmp_path / filename).read_text(encoding="utf-8")
        for expected in (
            "EASM 거버넌스 진단 보고서",
            "EASM (Enterprise Agent Service Management)",
            "CLI: wasm-agent",
            "수집 대상: Azure 구독 리소스",
            "Microsoft Foundry Agent", "자체 호스팅 Agent 탐지 후보(LangChain)",
            f"수집 결과: {subscription_count}개",
        ):
            assert expected in content
        assert content.index("수집 대상:") < content.index("Agent 인벤토리 요약")
        assert "<table" not in content
        assert "| ---" not in content
        for removed in ("오프라인 예제", "실제 Azure 실측이 아닙니다", "신규 샘플",
                        "테스트베드", "데모", "원 제품 진단은 범위 밖", "M365/Power Platform"):
            assert removed not in content
        assert content.count("<details>") == content.count("</details>")
    content = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "항목: 조회 대상 구독 - 수집 결과: " + str(subscription_count) + "개" in content
    if subscription_count:
        assert "<details><summary>구독: subscription-0" in content
        assert "목록 확인 상태" in content
        assert "목록 수집 실패" in content
    assert "<li>" in (tmp_path / "report.html").read_text(encoding="utf-8")
