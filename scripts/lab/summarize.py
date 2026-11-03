from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

from scripts.lab.certificates import GraphCertificates
from scripts.setup.setup_account import AzureCLI
from wasm_agent.report_bundle import load_result

ROOT = Path(__file__).resolve().parents[2]


def ready_health(url: str) -> dict:
    for attempt in range(18):
        try:
            response = requests.get(url, timeout=30, allow_redirects=False)
        except (requests.Timeout, requests.ConnectionError):
            print("최종 앱 상태 확인: 재시작 연결 대기", flush=True)
        else:
            try:
                if response.status_code in (301, 302, 401, 403, 404):
                    raise RuntimeError(f"샘플 health 경로 확인 필요: HTTP {response.status_code}")
                if response.status_code == 200 and response.headers.get("Content-Type", "").startswith(
                    "application/json",
                ):
                    value = response.json()
                    if value.get("smoke_status") == "failed":
                        raise RuntimeError("샘플 모델 실행이 실패했습니다.")
                    if value.get("status") == "ready" and value.get("sample_revision") == "chatbot-v2":
                        return value
                print(f"최종 앱 상태 확인: 준비 대기, HTTP {response.status_code}", flush=True)
            finally:
                response.close()
        if attempt < 17:
            time.sleep(10)
    raise RuntimeError("실제 샘플 앱의 최신 코드 준비 상태를 확인하지 못했습니다.")


def main() -> int:
    state = ROOT / ".wasm-agent"
    setup = json.loads((state / "setup.json").read_text(encoding="utf-8"))
    lab = json.loads((state / "demo" / "lab.json").read_text(encoding="utf-8"))
    run = json.loads((state / "demo" / "runthrough.json").read_text(encoding="utf-8"))
    data = load_result(ROOT / "output")["collection"]
    if not lab.get("functional_smoke_complete") or lab["foundry_smoke"]["status"] != "completed":
        raise RuntimeError("샘플 실제 모델 smoke가 완료되지 않았습니다.")
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", check=False)
    count = re.search(r"(\d+) passed", tests.stdout)
    if tests.returncode or not count:
        raise RuntimeError("최종 테스트 결과를 확인하지 못했습니다.")
    lint = subprocess.run([sys.executable, "-m", "ruff", "check", "src", "scripts", "samples", "tests"],
                          cwd=ROOT, capture_output=True, text=True, check=False)
    if lint.returncode:
        raise RuntimeError("최종 린트 실패")
    registry = GraphCertificates(setup["client_id"])
    try:
        if registry.certificates():
            raise RuntimeError("진단 앱에 인증서가 남아 있습니다.")
    finally:
        registry.close()
    health = []
    for host in lab["hosts"]:
        value = ready_health(host["health_url"])
        if host["smoke"]["smoke_status"] != "completed":
            raise RuntimeError("샘플 실제 모델 실행 완료 증거가 없습니다.")
        if host.get("chat_url"):
            with requests.post(host["chat_url"] + "/api/chat", json={"messages": []},
                               timeout=30, allow_redirects=False) as denied:
                if denied.status_code not in (302, 401, 403):
                    raise RuntimeError("비인증 챗봇 모델 호출이 차단되지 않았습니다.")
        health.append({"name": host["name"], "current": value})
    if not run["temporary_certificate_cleaned"]:
        raise RuntimeError("인증서 정리 완료 증거가 없습니다.")
    roles = []
    cli = AzureCLI()
    for sid in setup["subscription_ids"]:
        rows = cli.run("role", "assignment", "list", "--subscription", sid,
                       "--all", "--fill-principal-name", "false")
        roles.extend({"role": row["roleDefinitionName"], "scope": row["scope"]} for row in rows
                     if row.get("principalId", "").lower() == setup["principal_id"])
    if any(row["role"] in {"Owner", "Contributor", "User Access Administrator"} for row in roles):
        raise RuntimeError("진단 SP에 금지된 관리자 역할이 발견됐습니다.")
    if len(data["agents"]) < lab.get("expected_agent_count", 3):
        raise RuntimeError("계획한 Agent 수만큼 실제 인벤토리에서 발견되지 않았습니다.")
    verification = {
        "verified_at": datetime.now(UTC).isoformat(), "tests_passed": int(count[1]),
        "ruff": "passed", "remaining_certificates": 0, "diagnostic_roles": roles, "health": health,
        "diagnostic_agents": len(data["agents"]), "evidence_issues": len(data["issues"]),
        "administrator_collection_fallback": run["administrator_collection_fallback"],
    }
    (state / "demo" / "verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print({"tests_passed": int(count[1]), "agents": len(data["agents"]), "remaining_certificates": 0})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
