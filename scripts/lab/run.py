from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml
from azure.core.exceptions import AzureError
from openai import OpenAIError

from scripts.lab.auth import TemporaryCertificate
from scripts.lab.bootstrap import deploy, plan
from scripts.setup.setup_account import ROLES, AzureCLI, ensure_assignment
from wasm_agent.utils.evidence import redact
from wasm_agent.utils.settings import load_yaml

ROOT = Path(__file__).resolve().parents[2]


def save(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def child(command: list[str], environment: dict[str, str] | None = None) -> int:
    return subprocess.run([sys.executable, *command], cwd=ROOT, env=environment, check=False).returncode


def offline() -> None:
    if child(["-m", "pytest", "-q"]):
        raise RuntimeError("오프라인 테스트 실패; Azure 샘플 배포를 시작하지 않습니다.")
    if child(["-m", "wasm_agent.cli", "collect", "--fixture", "tests/fixtures/three_subscriptions.json",
              "--output-dir", "output/mock"]):
        raise RuntimeError("오프라인 fixture Run-through 실패")


def collect_live(setup: dict, lab: dict, cli: AzureCLI, options: dict) -> int:
    settings = load_yaml(ROOT / "config" / "config.yaml")
    settings.update({
        "tenant_id": setup["tenant_id"], "expected_principal_id": setup["principal_id"],
        "subscriptions": setup["subscription_ids"],
        "evidence_dir": str(ROOT / "evidence"),
        "projects": [{"subscription_id": setup["subscription_ids"][0],
                      "resource_id": lab["project_id"], "endpoint": lab["project_endpoint"]}],
    })
    for field in ("allowed_models_file", "criteria_file", "tag_conventions_file"):
        settings[field] = str(ROOT / "config" / settings[field])
    config_path = ROOT / "output" / "lab-collection.yaml"
    config_path.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")
    projects_path = ROOT / "output" / "lab-projects.json"
    save(projects_path, settings["projects"])
    with TemporaryCertificate(setup) as environment:
        command = ["-m", "wasm_agent.cli", "collect", "--config", str(config_path),
                   "--output-dir", str(ROOT / "output")]
        if options.get("collect_all_subscriptions"):
            command.append("--all-subscriptions")
        code = child(command, environment)
        if code == 1:
            time.sleep(15)
            code = child(command, environment)
        if code not in (0, 2):
            raise RuntimeError("진단 SP 수집 실행 실패; 관리자 수집으로 대체하지 않음")
        collection = json.loads((ROOT / "output" / "collection.json").read_text(encoding="utf-8"))
        changes = []
        if options.get("auto_grant_needed_read_roles"):
            for entry in collection["issues"]:
                if entry["reason"] != "permission_denied" or "HTTP 403" not in entry["detail"]:
                    continue
                if entry["collector"] == "agent_usage":
                    scope, role = lab["workspace_id"], "Log Analytics Reader"
                elif entry["collector"] == "cost":
                    scope = "/subscriptions/" + entry["subscription_id"]
                    role = "Cost Management Reader"
                else:
                    continue
                record = {"scope": scope, "role": role}
                if record not in changes:
                    ensure_assignment(cli, setup["principal_id"], "ServicePrincipal", scope, ROLES[role])
                    changes.append(record)
            if changes:
                before = ROOT / "output" / "before-additional-read-roles"
                before.mkdir(exist_ok=True)
                for name in ("collection.json", "inventory.json", "inventory.csv", "findings.json",
                             "summary.csv", "cost_monthly.csv", "report.md", "report.html"):
                    source = ROOT / "output" / name
                    if source.exists():
                        source.replace(before / name)
                time.sleep(30)
                code = child(command, environment)
                if code not in (0, 2):
                    raise RuntimeError("제한된 추가 읽기 역할 적용 후 수집 실행 실패")
        lab["additional_diagnostic_read_roles"] = changes
        save(ROOT / "output" / "lab.json", lab)
        for attempt in range(3):
            current = json.loads((ROOT / "output" / "collection.json").read_text(encoding="utf-8"))
            pending = [
                agent for agent in current["agents"]
                if agent["platform"] == "langchain" and agent["usage_30d"] is None
            ]
            if not pending or not lab.get("functional_smoke_complete"):
                break
            print(f"실제 Agent 로그 유입 대기: {len(pending)}개, 재조회 {attempt + 1}/3", flush=True)
            time.sleep(30)
            code = child(command, environment)
            if code not in (0, 2):
                raise RuntimeError("로그 유입 대기 후 진단 SP 수집 실행 실패")
        preflight = child([
            "scripts/verify_permissions.py", "--tenant-id", setup["tenant_id"],
            "--expected-principal-id", setup["principal_id"],
            "--subscriptions", *setup["subscription_ids"], "--projects-file", str(projects_path),
        ], environment)
        if preflight not in (0, 2):
            raise RuntimeError("진단 SP 접근 사전 점검 실행 실패")
    collection = json.loads((ROOT / "output" / "collection.json").read_text(encoding="utf-8"))
    expected = lab.get("expected_agent_count", 3)
    if len(collection["agents"]) < expected or len(collection["completed_subscriptions"]) != 3:
        raise RuntimeError(f"승인된 3개 구독/{expected}개 Agent 샘플의 실측 발견을 확인하지 못했습니다.")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="관리자 샘플 준비와 진단 Reader Run-through 분리 실행")
    parser.add_argument("command", choices=["plan", "test", "validate", "deploy", "collect", "all"])
    parser.add_argument("--setup-file", type=Path, default=ROOT / "output" / "setup.json")
    parser.add_argument("--lab-config", type=Path, default=ROOT / "config" / "lab.yaml")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--prepare-providers", action="store_true")
    parser.add_argument("--reuse-infrastructure", action="store_true")
    args = parser.parse_args(argv)
    logging.getLogger("azure").setLevel(logging.WARNING)
    output = ROOT / "output"
    output.mkdir(exist_ok=True)
    started = datetime.now(UTC).isoformat()
    try:
        setup = json.loads(args.setup_file.read_text(encoding="utf-8-sig"))
        options = load_yaml(args.lab_config)
        if args.command == "plan":
            print(json.dumps(plan(setup, options), ensure_ascii=False, indent=2))
            return 0
        if args.command == "test":
            offline()
            return 0
        if args.command == "validate":
            from scripts.lab.validate import validate

            return validate(AzureCLI(), setup, options, ROOT, args.prepare_providers)
        if args.command in ("deploy", "all"):
            if not args.apply:
                raise ValueError("샘플 배포에는 승인 확인용 --apply가 필요합니다.")
            validation = ROOT / ".azure" / "validation.json"
            if not validation.is_file() or not json.loads(validation.read_text())["passed"]:
                raise ValueError("배포 전 검증 .azure/validation.json passed=true가 필요합니다.")
        if args.command == "all":
            offline()
        cli = AzureCLI()
        if args.command in ("deploy", "all"):
            lab = deploy(cli, setup, options, ROOT, reuse_infrastructure=args.reuse_infrastructure)
            save(output / "lab.json", lab)
            if args.command == "deploy":
                print("샘플 배포 완료. 진단 수집은 collect 명령으로 별도 실행합니다.", flush=True)
                return 0
        else:
            lab = json.loads((output / "lab.json").read_text(encoding="utf-8"))
        code = collect_live(setup, lab, cli, options) if args.command in ("collect", "all") else 0
        save(output / "runthrough.json", {
            "started_at": started, "finished_at": datetime.now(UTC).isoformat(),
            "status": "partial" if code == 2 else "completed",
            "collection_exit_code": code, "temporary_certificate_cleaned": True,
            "sample_resources": "retained", "administrator_collection_fallback": False,
        })
        print("Run-through 완료: 샘플 유지, 일회성 인증서 정리, output/report.html 확인", flush=True)
        return code
    except (RuntimeError, ValueError, KeyError, TypeError, OSError, AzureError, OpenAIError,
            subprocess.SubprocessError) as exc:
        save(output / "runthrough.json", {
            "started_at": started, "finished_at": datetime.now(UTC).isoformat(),
            "status": "failed", "error_type": type(exc).__name__,
            "sample_resources": "created resources are retained; rerun after fixing the reported phase",
        })
        message = str(exc) if type(exc) in (RuntimeError, ValueError) else type(exc).__name__
        print(f"Run-through 중단: {redact(message)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
