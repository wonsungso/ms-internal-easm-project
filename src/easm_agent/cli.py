from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import DefaultAzureCredential

from easm_agent.azure import AccessError, EvidenceStore
from easm_agent.collect import collect
from easm_agent.collect_admin_evidence import admin_observations, read_admin_evidence
from easm_agent.collect_agent365 import Agent365Collector, agent365_observations
from easm_agent.collect_entra import EntraCollector
from easm_agent.evaluation import evaluate
from easm_agent.models import (
    Collection,
    Finding,
    allowed_models,
    load_conventions,
    load_criteria,
    load_settings,
)
from easm_agent.proposals import evaluate_proposals
from easm_agent.report import latest_raw, load_result, write_reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="읽기 전용 Azure/Foundry 거버넌스 증적")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("collect")
    command.add_argument("--config", type=Path, default=Path("config") / "custom-config.yaml",
                         help="고객별 선택 설정 파일")
    command.add_argument("--criteria", type=Path, help="등급 기준 YAML 경로 - 기본값 config/criteria.yaml")
    command.add_argument("--setup-file", type=Path)
    scope = command.add_mutually_exclusive_group()
    scope.add_argument("--subscriptions", nargs="+")
    scope.add_argument(
        "--all-subscriptions", action="store_true",
        help="설정 구독 목록 대신 지정 테넌트에서 진단 계정이 접근 가능한 모든 활성 구독 수집",
    )
    command.add_argument("--tenant-id")
    command.add_argument("--expected-principal-id")
    command.add_argument("--manual-agents", type=Path)
    command.add_argument("--admin-evidence-file", action="append", type=Path, default=[])
    command.add_argument("--output-dir", type=Path, default=Path("output"))
    command.add_argument("--fixture", type=Path)
    command.add_argument("--dry-run", action="store_true")
    package = subparsers.add_parser("package", help="raw-data-<타임스탬프>.json을 읽어 Excel 보고서 재생성")
    package.add_argument("--output-dir", type=Path, default=Path("output"))
    package.add_argument("--mode", choices=["live", "fixture"])
    package.add_argument("--admin-evidence-file", action="append", type=Path, default=[])
    package.add_argument("--tenant-id")
    args = parser.parse_args(argv)
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("azure.identity").setLevel(logging.ERROR)
    try:
        if args.command == "package":
            source = latest_raw(args.output_dir)
            if source is None:
                raise ValueError("수집 결과 raw-data JSON을 찾을 수 없습니다.")
            result = load_result(source.parent)
            data = Collection.model_validate(result["collection"])
            findings = [Finding.model_validate(row) for row in result["findings"]]
            recorded_mode = result.get("mode") or data.facts.get("data_mode")
            if recorded_mode and args.mode and recorded_mode != args.mode:
                raise ValueError("수집한 데이터 구분과 지정한 mode가 다릅니다.")
            mode = recorded_mode or args.mode
            if mode not in ("live", "fixture"):
                raise ValueError("기존 파일의 데이터 구분이 없습니다. --mode live 또는 --mode fixture를 명시하세요.")
            if args.admin_evidence_file:
                if mode != "live":
                    raise ValueError("실제 관리자 증적은 fixture 결과에 혼합하지 않습니다.")
                tenants = {str(uuid.UUID(agent.tenant_id)) for agent in data.agents if agent.tenant_id}
                if args.tenant_id:
                    tenants.add(str(uuid.UUID(args.tenant_id)))
                if len(tenants) != 1:
                    raise ValueError("관리자 증적 반영에는 단일 수집 테넌트 확인이 필요합니다.")
                tenant = tenants.pop()
                recorded_directory = data.facts["evidence_directory"]
                if recorded_directory == "embedded:evidence":
                    directory = source.parent / "evidence"
                else:
                    directory = Path(recorded_directory)
                    if not directory.is_dir():
                        raise FileNotFoundError("기존 증적 보관 경로가 없어 관리자 내보내기를 첨부할 수 없습니다.")
                store = EvidenceStore(directory)
                data.facts["evidence_directory"] = str(directory.resolve())
                seen_sources: set[str] = set()
                for path in args.admin_evidence_file:
                    incoming = read_admin_evidence(path, tenant, datetime.now(UTC), store)
                    sources = {read.source for read in incoming.admin_evidence}
                    if seen_sources & sources:
                        raise ValueError("같은 관리자 조회 원천을 중복 반영할 수 없습니다.")
                    seen_sources.update(sources)
                    data.admin_evidence = [read for read in data.admin_evidence if read.source not in sources]
                    data.admin_evidence.extend(incoming.admin_evidence)
                data.proposals = [
                    proposal for proposal in data.proposals
                    if proposal.code not in {item.code for item in admin_observations(data)}
                ] + admin_observations(data)
            data.facts["data_mode"] = mode
            write_reports(data, findings, source.parent, mode, new_run=False)
            return 0
        settings = load_settings(args.config)
        if args.admin_evidence_file:
            settings.admin_evidence_files = args.admin_evidence_file
        if args.fixture and settings.admin_evidence_files:
            raise ValueError("실제 관리자 증적은 fixture 수집에 혼합하지 않습니다.")
        if args.config != Path("config") / "custom-config.yaml" and not args.config.is_file():
            raise FileNotFoundError(f"선택 설정 파일을 찾을 수 없습니다: {args.config}")
        if args.criteria:
            settings.criteria_file = args.criteria
        setup_subscriptions: list[str] = []
        if args.setup_file:
            setup = json.loads(args.setup_file.read_text(encoding="utf-8-sig"))
            settings.tenant_id = setup["tenant_id"]
            settings.expected_principal_id = setup["principal_id"]
            setup_subscriptions = setup.get("subscription_ids") or []
        if args.tenant_id:
            settings.tenant_id = args.tenant_id
        if args.expected_principal_id:
            settings.expected_principal_id = args.expected_principal_id
        if args.subscriptions:
            settings.subscriptions = args.subscriptions
        elif args.all_subscriptions:
            settings.subscriptions = []
        elif setup_subscriptions:
            settings.subscriptions = setup_subscriptions
        if args.manual_agents:
            settings.manual_agents = args.manual_agents
        settings = type(settings).model_validate(settings.model_dump())
        criteria = load_criteria(settings)
        if args.dry_run:
            print(json.dumps({
                "mode": "fixture" if args.fixture else "live",
                "tenant_id": settings.tenant_id,
                "subscriptions": settings.subscriptions or "auto-enumerate",
                "output_dir": str(args.output_dir),
                "foundry_profile": settings.foundry_profile,
                "roles": [
                    "Reader", "Cost Management Reader", "Log Analytics Reader", "Security Reader",
                    "Foundry: agents/read, evaluations/read, assets/read",
                ]
                + ["Graph: " + ", ".join(EntraCollector.required_roles + Agent365Collector.required_roles)],
                "entra": True,
                "azure_calls": False,
            }, ensure_ascii=False, indent=2))
            return 0
        if args.fixture:
            data = Collection.model_validate_json(args.fixture.read_text(encoding="utf-8"))
            for agent in data.agents:
                agent.mark_unknowns()
        else:
            with DefaultAzureCredential() as credential:
                data = collect(settings, credential)
            data.facts["subscription_scope"] = (
                "explicit_subscription_list" if settings.subscriptions else "all_accessible_active_in_tenant"
            )
        data.facts["data_mode"] = "fixture" if args.fixture else "live"
        data.proposals = evaluate_proposals(data, load_conventions(settings))
        data.proposals.extend(agent365_observations(data))
        data.proposals.extend(admin_observations(data))
        findings = evaluate(
            data, criteria, allowed_models(settings),
            load_conventions(settings), settings.policy_facts, settings.interview_levels,
        )
        workbook = write_reports(data, findings, args.output_dir, "fixture" if args.fixture else "live")
        print(f"수집 완료: 구독={len(data.subscriptions)}, Agent/후보={len(data.agents)}, "
              f"이슈={len(data.issues)}, 결과={workbook.parent}")
        return 2 if data.issues else 0
    except (ValueError, KeyError, TypeError, OSError, AccessError, ClientAuthenticationError) as exc:
        detail = str(exc) if isinstance(exc, AccessError) else type(exc).__name__
        if isinstance(exc, ClientAuthenticationError):
            code = re.search(r"AADSTS\d+", str(exc))
            if code:
                detail += " (" + code.group(0) + ")"
        print(f"실행 중단: {detail}. 원문·비밀값·토큰은 출력하지 않았습니다.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
