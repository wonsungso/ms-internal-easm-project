from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.lab.bootstrap import plan
from scripts.setup.setup_account import AzureCLI
from wasm_agent.utils.settings import load_yaml

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="별도 승인 후 실행하는 샘플 전용 정리. 기본값은 dry-run.")
    parser.add_argument("--setup-file", type=Path, default=ROOT / "output" / "setup.json")
    parser.add_argument("--lab-config", type=Path, default=ROOT / "config" / "lab.yaml")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-lab-id")
    args = parser.parse_args(argv)
    setup = json.loads(args.setup_file.read_text(encoding="utf-8-sig"))
    lab = plan(setup, load_yaml(args.lab_config))
    if args.apply and args.confirm_lab_id != lab["lab_id"]:
        raise ValueError("삭제에는 정확한 --confirm-lab-id가 필요합니다. 자동 삭제하지 않습니다.")
    cli = AzureCLI()
    if cli.run("account", "show")["tenantId"].lower() != setup["tenant_id"]:
        raise ValueError("정리 관리자 테넌트 불일치")
    verified = []
    for group in lab["groups"]:
        existing = next((row for row in cli.run("group", "list", "--subscription", group["subscription_id"])
                         if row["name"].lower() == group["name"].lower()), None)
        if not existing:
            print(f"이미 없는 샘플 그룹: {group['name']}")
            continue
        if (existing.get("tags") or {}).get("seagent-lab") != lab["lab_id"]:
            raise ValueError("소유 태그가 다릅니다. 어떤 그룹도 삭제하지 않았습니다.")
        verified.append(group)
    for group in verified:
        print(f"{'DELETE' if args.apply else 'DRY-RUN'}: {group['id']}")
        if args.apply:
            cli.run("group", "delete", "--name", group["name"],
                    "--subscription", group["subscription_id"], "--yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
