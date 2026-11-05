from __future__ import annotations

import argparse
import base64
import json
import re
import shlex
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath

import requests
import yaml

from demo.auth import GraphCertificates, TemporaryCertificate
from demo.manage import ROOT, save
from scripts.setup_account import AzureCLI
from wasm_agent.report import RUN_PATTERN, load_result

WORKSPACE = "/workspaces/ms-internal-wasm-project"


def gh(*arguments: str, allowed: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["gh", *arguments], capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode not in allowed:
        raise RuntimeError(f"Codespaces 작업 실패: {arguments[0:2]}, exit={result.returncode}; 원문 비출력")
    return result


def run(codespace: str) -> None:
    if not re.fullmatch(r"[a-z0-9-]+", codespace):
        raise ValueError("유효한 Codespace 이름이 필요합니다.")
    setup = json.loads((ROOT / ".wasm-agent" / "setup.json").read_text(encoding="utf-8"))
    lab = json.loads((ROOT / ".wasm-agent" / "demo" / "lab.json").read_text(encoding="utf-8"))
    settings = {
        "tenant_id": setup["tenant_id"], "expected_principal_id": setup["principal_id"],
        "subscriptions": [],
        "evidence_dir": WORKSPACE + "/.wasm-agent/evidence",
        "projects": [{"subscription_id": setup["subscription_ids"][0],
                      "resource_id": lab["project_id"], "endpoint": lab["project_endpoint"]}],
        "allowed_models": [{"name": lab["model"], "version": lab["model_version"]}],
    }
    directory = gh("codespace", "ssh", "-c", codespace, "--",
                   "umask 077; mktemp -d /home/vscode/wasm-agent-auth-XXXXXXXX").stdout.strip()
    if not re.fullmatch(r"/home/vscode/wasm-agent-auth-[A-Za-z0-9]{8}", directory):
        raise RuntimeError("Codespace의 보호된 임시 경로를 확인할 수 없습니다.")
    remote_cleanup = False
    code = None
    try:
        with tempfile.TemporaryDirectory(prefix="wasm-agent-config-") as local:
            config = Path(local) / "collection.yaml"
            config.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")
            with TemporaryCertificate(setup) as environment:
                try:
                    for source, name in [(Path(environment["AZURE_CLIENT_CERTIFICATE_PATH"]), "credential.pem"),
                                         (config, "collection.yaml")]:
                        gh("codespace", "cp", "-c", codespace, "--", "-O", str(source),
                           "remote:" + directory + "/" + name)
                    command = (
                        f"set -eu; chmod 600 {directory}/credential.pem {directory}/collection.yaml; "
                        f"cd {WORKSPACE}; set +e; env -u AZURE_CLIENT_SECRET -u AZURE_FEDERATED_TOKEN_FILE "
                        f"-u AZURE_CLIENT_CERTIFICATE_PASSWORD "
                        f"AZURE_TENANT_ID={shlex.quote(setup['tenant_id'])} "
                        f"AZURE_CLIENT_ID={shlex.quote(setup['client_id'])} "
                        f"AZURE_CLIENT_CERTIFICATE_PATH={directory}/credential.pem "
                        f".venv/bin/wasm-agent collect --config {directory}/collection.yaml "
                        "--all-subscriptions --output-dir output; "
                        'code=$?; printf "\\nWASM_COLLECTION_EXIT=%s\\n" "$code"; '
                        'test "$code" -eq 0 || test "$code" -eq 2'
                    )
                    result = gh("codespace", "ssh", "-c", codespace, "--", command)
                    marker = re.search(r"^WASM_COLLECTION_EXIT=([02])$", result.stdout, re.MULTILINE)
                    if marker is None:
                        raise RuntimeError("Codespaces 수집 종료 상태를 확인하지 못했습니다.")
                    code = int(marker[1])
                    print(result.stdout, end="")
                finally:
                    gh("codespace", "ssh", "-c", codespace, "--",
                       f"rm -f {directory}/credential.pem {directory}/collection.yaml; rmdir {directory}")
                    remote_cleanup = True
        script = (
            "from pathlib import Path; import json; from wasm_agent.report import latest_raw; "
            "p=latest_raw(Path('output')); "
            "assert p is not None, 'No collection result'; "
            "print(json.dumps([str(p.with_name(p.name.replace('raw-data-', 'report-').replace('.json', '.xlsx'))), str(p)]))"
        )
        listing = gh("codespace", "ssh", "-c", codespace, "--",
                     f"cd {WORKSPACE}; .venv/bin/python -c {shlex.quote(script)}")
        paths = json.loads(listing.stdout)
        if not isinstance(paths, list) or len(paths) != 2 or not all(isinstance(p, str) for p in paths):
            raise RuntimeError("Codespaces 결과 경로 형식 오류")
        sources = [PurePosixPath(path) for path in paths]
        if any(
            source.is_absolute() or ".." in source.parts or len(source.parts) not in (2, 3)
            or source.parts[0] != "output"
            or (len(source.parts) == 3 and not RUN_PATTERN.fullmatch(source.parts[1]))
            for source in sources
        ) or sources[0].parent != sources[1].parent:
            raise RuntimeError("Codespaces 결과 경로를 확인하지 못했습니다.")
        names = [source.name for source in sources]
        if not re.fullmatch(r"report-\d{8}T\d{6}Z\.xlsx", names[0]) or names[1] != names[0].replace(
            "report-", "raw-data-",
        ).replace(".xlsx", ".json"):
            raise RuntimeError("Codespaces 결과 파일명을 확인하지 못했습니다.")
        destination = ROOT.joinpath(*sources[0].parent.parts)
        destination.mkdir(parents=True, exist_ok=True)
        for source, name in zip(sources, names, strict=True):
            result = gh(
                "codespace", "ssh", "-c", codespace, "--",
                f"base64 {shlex.quote(WORKSPACE + '/' + str(source))}",
            )
            payload = base64.b64decode("".join(result.stdout.split()), validate=True)
            if name.endswith(".xlsx"):
                with zipfile.ZipFile(BytesIO(payload)) as archive:
                    if archive.testzip() is not None or "[Content_Types].xml" not in archive.namelist():
                        raise RuntimeError("Codespaces에서 받은 Excel 파일의 무결성 검사 실패")
            elif json.loads(payload).get("schema_version") != 1:
                raise RuntimeError("Codespaces에서 받은 raw-data JSON 구성 검사 실패")
            (destination / name).write_bytes(payload)
        save(ROOT / ".wasm-agent" / "demo" / "codespace-e2e-verification.json", {
            "codespace": codespace, "collection_exit_code": code, "all_subscriptions": True,
            "remote_private_key_cleaned": remote_cleanup, "temporary_certificate_cleaned": True,
            "files": [str(source) for source in sources], "administrator_collection_fallback": False,
        })
    finally:
        if not remote_cleanup:
            gh("codespace", "ssh", "-c", codespace, "--",
               f"rm -f {directory}/credential.pem {directory}/collection.yaml; rmdir {directory}")


def codespace_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="승인된 단기 인증서로 Codespaces 실제 진단 및 인증 재료 정리")
    parser.add_argument("--codespace", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if not args.apply:
        parser.error("인증서 전달에는 승인 확인 --apply가 필요합니다.")
    run(args.codespace)
    return 0


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


def summary_main() -> int:
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
    lint = subprocess.run([sys.executable, "-m", "ruff", "check", "src", "scripts", "demo", "tests"],
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="데모 진단 수집과 읽기 검증 - 고객 수집과 분리")
    parser.add_argument("command", choices=["codespace", "verify"])
    args, remaining = parser.parse_known_args(argv)
    if args.command == "codespace":
        return codespace_main(remaining)
    if remaining:
        parser.error("verify 명령에는 추가 인자가 없습니다.")
    return summary_main()


if __name__ == "__main__":
    raise SystemExit(main())
