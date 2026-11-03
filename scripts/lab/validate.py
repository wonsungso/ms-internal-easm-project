from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.lab.bootstrap import deployment_parameters, plan


def validate(cli: Any, setup: dict, options: dict, root: Path, prepare_providers: bool) -> int:
    proof: dict[str, Any] = {
        "passed": False, "checked_at": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0], "recipe": "AZCLI with Bicep",
        "checks": [],
    }
    proof_path = root / ".azure" / "validation.json"
    proof_path.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    for command in [
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "-m", "ruff", "check", "src", "scripts", "samples", "tests"],
    ]:
        completed = subprocess.run(command, cwd=root, check=False)
        if completed.returncode:
            raise RuntimeError("배포 전 로컬 검증 실패. Azure 배포를 시작하지 않습니다.")
        proof["checks"].append({"command": command[1:], "status": "passed"})
    context = cli.run("account", "show")
    if context["tenantId"].lower() != setup["tenant_id"]:
        raise ValueError("배포 전 관리자 테넌트 불일치")
    lab = plan(setup, options)
    cli.run("bicep", "build", "--file", str(root / "infra" / "main.bicep"), "--stdout")
    proof["checks"].append({"command": "az bicep build --stdout", "status": "passed"})
    for index, group in enumerate(lab["groups"]):
        sid = group["subscription_id"]
        print(f"배포 전 ARM 검증: 구독 {index + 1}/3", flush=True)
        namespace = "Microsoft.CognitiveServices" if index == 0 else "Microsoft.Web"
        providers = cli.run("provider", "list", "--subscription", sid)
        for required in ("Microsoft.Resources", namespace, "Microsoft.OperationalInsights", "Microsoft.Insights"):
            state = next((entry["registrationState"] for entry in providers
                          if entry["namespace"].lower() == required.lower()), None)
            if state != "Registered":
                if not prepare_providers:
                    raise RuntimeError(f"필요 공급자 {required} 미등록. --prepare-providers로 승인된 준비를 실행하세요.")
                cli.run("provider", "register", "--namespace", required, "--subscription", sid, "--wait")
        policies = cli.run("policy", "assignment", "list", "--scope", "/subscriptions/" + sid,
                           "--subscription", sid)
        parameters = deployment_parameters(lab, index)
        common = [
            "--subscription", sid, "--location", lab["region"],
            "--template-file", str(root / "infra" / "main.bicep"),
            "--parameters", *parameters,
        ]
        for attempt in range(3):
            try:
                cli.run("deployment", "sub", "validate", *common)
                preview = cli.run("deployment", "sub", "what-if", "--no-pretty-print", *common)
                break
            except RuntimeError as exc:
                if attempt == 2:
                    raise RuntimeError(f"구독 {index + 1}/3 ARM 검증 실패: {exc}") from exc
                time.sleep(10)
        if any(change.get("changeType") == "Delete" for change in (preview or {}).get("changes", [])):
            raise RuntimeError("what-if에 삭제가 포함되어 있습니다. 샘플 유지 승인 범위를 넘어 중단합니다.")
        proof["checks"].append({
            "subscription_id": sid, "template_validate": "passed", "what_if": "passed",
            "policy_assignments_retrieved": len(policies), "destructive_preview": False,
        })
        proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    proof["passed"] = True
    proof["finished_at"] = datetime.now(UTC).isoformat()
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print("배포 전 검증 통과: Python/Bicep/3개 구독 validate·what-if·정책 조회", flush=True)
    return 0
