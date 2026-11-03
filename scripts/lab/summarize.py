from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import requests

from scripts.lab.certificates import GraphCertificates
from scripts.setup.setup_account import AzureCLI

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    output = ROOT / "output"
    setup = json.loads((output / "setup.json").read_text(encoding="utf-8"))
    lab = json.loads((output / "lab.json").read_text(encoding="utf-8"))
    run = json.loads((output / "runthrough.json").read_text(encoding="utf-8"))
    data = json.loads((output / "collection.json").read_text(encoding="utf-8"))
    if not lab.get("functional_smoke_complete") or lab["foundry_smoke"]["status"] != "completed":
        raise RuntimeError("샘플 실제 모델 smoke가 완료되지 않았습니다.")
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", check=False)
    if tests.returncode:
        raise RuntimeError("최종 테스트 실패. 성공 대시보드를 생성하지 않습니다.")
    count = re.search(r"(\d+) passed", tests.stdout)
    if not count:
        raise RuntimeError("실제 테스트 성공 개수를 확인하지 못했습니다.")
    lint = subprocess.run([sys.executable, "-m", "ruff", "check", "src", "scripts", "samples", "tests"],
                          cwd=ROOT, capture_output=True, text=True, check=False)
    if lint.returncode:
        raise RuntimeError("최종 린트 실패")
    registry = GraphCertificates(setup["client_id"])
    try:
        remaining = len(registry.certificates())
    finally:
        registry.close()
    if remaining:
        raise RuntimeError("진단 앱에 인증서가 남아 있어 정리 완료로 표시하지 않습니다.")
    health = []
    for host in lab["hosts"]:
        response = requests.get(host["health_url"], timeout=30, allow_redirects=False)
        value = response.json()
        if response.status_code != 200 or value.get("status") != "ready":
            raise RuntimeError("실제 샘플 endpoint 상태가 ready가 아닙니다.")
        health.append({"name": host["name"], "url": host["health_url"], "http": response.status_code,
                       "current": value, "model_smoke_verified": host["smoke"]["smoke_status"] == "completed"})
        if host.get("chat_url"):
            denied = requests.post(
                host["chat_url"] + "/api/chat", json={"messages": []}, timeout=30, allow_redirects=False,
            )
            if denied.status_code not in (302, 401, 403):
                raise RuntimeError("비인증 챗봇 모델 호출이 차단되지 않았습니다.")
            health[-1]["anonymous_chat_status"] = denied.status_code
    if not all(item["model_smoke_verified"] for item in health) or not run["temporary_certificate_cleaned"]:
        raise RuntimeError("실제 smoke 또는 인증서 정리 완료 증거가 없습니다.")
    cli = AzureCLI()
    roles = []
    for sid in setup["subscription_ids"]:
        rows = cli.run("role", "assignment", "list", "--subscription", sid,
                       "--all", "--fill-principal-name", "false")
        for row in rows:
            if row.get("principalId", "").lower() == setup["principal_id"]:
                roles.append({"role": row["roleDefinitionName"], "scope": row["scope"]})
    forbidden = {"Owner", "Contributor", "User Access Administrator"}
    if any(row["role"] in forbidden for row in roles):
        raise RuntimeError("진단 SP에 금지된 관리자 역할이 발견됐습니다.")
    if len(data["agents"]) < lab.get("expected_agent_count", 3):
        raise RuntimeError("계획한 Agent 수만큼 실제 인벤토리에서 발견되지 않았습니다.")
    verification = {
        "verified_at": datetime.now(UTC).isoformat(), "python": sys.version.split()[0],
        "tests_passed": int(count[1]), "ruff": "passed", "remaining_certificates": remaining,
        "functional_smoke_complete": lab.get("functional_smoke_complete") is True,
        "diagnostic_subscriptions": len(data["completed_subscriptions"]),
        "diagnostic_agents": len(data["agents"]), "evidence_issues": len(data["issues"]),
        "collection_exit_code": run["collection_exit_code"], "diagnostic_roles": roles, "health": health,
        "administrator_collection_fallback": run["administrator_collection_fallback"],
        "evaluation_runs": len(data["evaluations"]),
        "completed_evaluation_runs": sum(row["status"] == "completed" for row in data["evaluations"]),
    }
    (output / "verification.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
    e = html.escape
    counts = Counter(agent["platform"] for agent in data["agents"])
    reasons = Counter((item["collector"], item["reason"]) for item in data["issues"])
    usage_rows = "".join(
        "<tr>" + "".join("<td>" + e(str(value) if value is not None else "확인 자료 없음") + "</td>" for value in [
            agent["platform"], agent["agent_name"], agent["model"],
            (agent["usage_30d"] or {}).get("calls"), (agent["usage_30d"] or {}).get("tokens"),
        ]) + "</tr>" for agent in data["agents"]
    )
    (output / "runthrough.html").write_text(
        "<!doctype html><html lang='ko'><meta charset='utf-8'><title>실제 Azure 실행 검증</title>"
        "<style>body{font:16px system-ui;color:#17233a;max-width:1250px;margin:32px}"
        "table{border-collapse:collapse;width:100%;margin:16px 0}td,th{border:1px solid #cbd4e3;padding:10px}"
        "th{background:#edf3fb}.cards{display:flex;gap:12px}.card{background:#eef6ef;padding:18px;border:1px solid #9db8a2}"
        ".notice{padding:14px;background:#fff3d7}a{color:#0751a3}nav{margin:20px 0}</style>"
        "<h1>실제 Azure 자동 실행 결과</h1>"
        f"<p>실측 UTC {e(data['collected_at'])} | Python {e(verification['python'])} | 실제 환경 수집</p>"
        "<div class='cards'>"
        f"<div class='card'>pytest <strong>{verification['tests_passed']} 통과</strong></div>"
        f"<div class='card'>구독 <strong>{len(data['completed_subscriptions'])}</strong> / "
        f"Agent <strong>{len(data['agents'])}</strong></div>"
        f"<div class='card'>Foundry {counts['foundry']} + LangChain {counts['langchain']}<br>실제 모델 응답 확인</div>"
        "<div class='card'>남은 인증서 <strong>0</strong><br>관리자 수집 대체 없음</div></div>"
        "<nav><a href='report.html'>진단 보고서와 상세 근거</a> | <a href='customer_inventory.csv'>한글 Agent 목록</a> | "
        "<a href='verification.json'>개발자용 검증 기록</a> | <a href='customer_summary.csv'>한글 진단 요약</a></nav>"
        "<p class='notice'>일부 자료는 아직 확인하지 못했습니다. "
        f"비용 미반영 {reasons[('cost','not_found')]}건, 로그 접근 제한 {reasons[('logs','permission_denied')]}건, "
        f"Defender AI 권고 미확인 {reasons[('security','feature_unavailable')]}건을 숨기거나 0으로 바꾸지 않았습니다.</p>"
        "<h2>진단 SP로 수집한 실제 인벤토리·사용량</h2>"
        "<table id='inventory'><thead><tr><th>플랫폼</th><th>Agent</th><th>모델</th>"
        "<th>로그의 성공 완료 이벤트</th><th>토큰 합계</th></tr></thead><tbody>" + usage_rows + "</tbody></table>"
        "<p>공유 모델의 사용량은 Foundry Agent 한 개에 임의 귀속하지 않습니다. 확인되지 않은 값은 0이 아닙니다.</p>"
        f"<p>평가 실행 {len(data['evaluations'])}건을 조회했습니다. 평가 완료와 배포 전 평가는 다릅니다. "
        "항목별 판정·원본 증거는 진단 보고서를 확인하세요.</p>"
        "<h2>로그인 보호 챗봇</h2><ul>"
        + "".join(
            f"<li><a href='{e(host.get('chat_url',host['health_url']), quote=True)}'>"
            f"{e(host['name'])} 챗봇 열기</a></li>" for host in lab["hosts"]
        )
        + "</ul><p>샘플 유지: B1 2개 USD 0.864/일 + 모델·로그 별도. 검증 USD 100은 하드 청구 상한이 아닙니다.</p></html>",
        encoding="utf-8",
    )
    print({"tests_passed": verification["tests_passed"], "agents": verification["diagnostic_agents"],
           "remaining_certificates": remaining, "result": str(output / "runthrough.html")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
