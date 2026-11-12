from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scripts import setup_account as setup

SID = "11111111-1111-4111-8111-111111111111"
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PRINCIPAL = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PROJECT = f"/subscriptions/{SID}/resourceGroups/test/providers/Microsoft.CognitiveServices/accounts/test/projects/p"


def arguments(*extra: str) -> list[str]:
    return [
        "--tenant-id", TENANT, "--subscriptions", SID,
        "--account-type", "service-principal", "--account-name", "diagnostic",
        *extra,
    ]


def test_dry_run_never_constructs_azure_cli(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(setup, "AzureCLI", side_effect=AssertionError("must not authenticate")):
        assert setup.main(arguments("--dry-run")) == 0
    assert "DRY-RUN" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--dry-run", "--what-if"])
def test_foundry_dry_run_lists_only_read_data_actions(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert setup.main(arguments(
        "--foundry-project-scopes", PROJECT, "--create-foundry-read-role", flag,
    )) == 0
    text = capsys.readouterr().out
    payload = json.loads(text.split("\n", 1)[1])
    assert payload["foundry_custom_role"]["Actions"] == []
    assert payload["foundry_custom_role"]["DataActions"] == [
        "Microsoft.CognitiveServices/accounts/AIServices/agents/read",
        "Microsoft.CognitiveServices/accounts/AIServices/evaluations/read",
        "Microsoft.CognitiveServices/accounts/AIServices/assets/read",
    ]
    assert payload["foundry_custom_role"]["AssignableScopes"] == [f"/subscriptions/{SID}"]


@pytest.mark.parametrize("scope", [
    "/", f"/subscriptions/{SID}", "/providers/Microsoft.Management/managementGroups/test",
    PROJECT.replace(SID, "22222222-2222-4222-8222-222222222222"),
])
def test_forbids_broad_or_foreign_foundry_scope(scope: str) -> None:
    assert setup.main(arguments(
        "--foundry-project-scopes", scope, "--create-foundry-read-role",
    )) == 1


def test_assignment_is_idempotent() -> None:
    scope = f"/subscriptions/{SID}"
    role = setup.ROLES["Reader"]
    cli = Mock()
    cli.run.return_value = [{
        "principalId": PRINCIPAL,
        "scope": scope,
        "roleDefinitionId": f"{scope}/providers/Microsoft.Authorization/roleDefinitions/{role}",
    }]
    setup.ensure_assignment(cli, PRINCIPAL, "User", scope, role)
    assert all(call.args[:3] != ("role", "assignment", "create") for call in cli.run.call_args_list)


def test_missing_client_id_sp_fails_without_name_fallback_or_creation(config_file: Path) -> None:
    args = setup.parser().parse_args(["--config-file", str(config_file), "--apply"])
    setup.load_config(args)
    cli = Mock()
    cli.run.side_effect = RuntimeError("Azure CLI 작업 실패: ad sp show (exit=3)")
    with pytest.raises(RuntimeError, match="Client ID에 해당하는 진단 SP"):
        setup.resolve_principal(cli, args)
    cli.run.assert_called_once_with("ad", "sp", "show", "--id", args.client_id)


@pytest.mark.parametrize("old_principal", [
    None, "cccccccc-cccc-4ccc-8ccc-cccccccccccc", "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
])
def test_client_id_resolves_missing_or_incorrect_principal_id(
    config_file: Path, old_principal: str | None,
) -> None:
    args = setup.parser().parse_args(["--config-file", str(config_file), "--apply"])
    setup.load_config(args)
    args.principal_id = old_principal
    cli = Mock()
    cli.run.return_value = {"id": PRINCIPAL, "appId": args.client_id, "displayName": args.account_name}
    assert setup.resolve_principal(cli, args)["id"] == PRINCIPAL
    assert args.principal_id == PRINCIPAL
    cli.run.assert_called_once_with("ad", "sp", "show", "--id", args.client_id)


@pytest.mark.parametrize("field,value", [
    ("appId", "dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
    ("displayName", "another-app"),
    ("id", "not-a-guid"),
])
def test_client_resolution_rejects_mismatched_response_before_any_write(
    config_file: Path, field: str, value: str,
) -> None:
    args = setup.parser().parse_args(["--config-file", str(config_file), "--apply"])
    setup.load_config(args)
    cli = Mock()
    cli.run.return_value = {
        "id": PRINCIPAL, "appId": args.client_id, "displayName": args.account_name, field: value,
    }
    with pytest.raises((ValueError, setup.argparse.ArgumentTypeError)):
        setup.resolve_principal(cli, args)
    assert cli.run.call_count == 1


def test_scoped_assignment_list_uses_valid_cli_arguments() -> None:
    scope = f"/subscriptions/{SID}"
    cli = Mock()
    cli.run.return_value = []
    assert not setup.assignment_exists(cli, PRINCIPAL, scope, setup.ROLES["Reader"])
    cli.run.assert_called_once_with(
        "role", "assignment", "list", "--scope", scope, "--subscription", SID,
    )
    assert "--all" not in cli.run.call_args.args


def test_assignment_create_then_verify() -> None:
    scope = f"/subscriptions/{SID}"
    role = setup.ROLES["Reader"]
    assignment = {"principalId": PRINCIPAL, "scope": scope, "roleDefinitionId": role}
    cli = Mock()
    cli.run.side_effect = [[], {}, [assignment]]
    setup.ensure_assignment(cli, PRINCIPAL, "User", scope, role)
    assert cli.run.call_args_list[1].args[:3] == ("role", "assignment", "create")
    assert cli.run.call_args_list[2].args[:3] == ("role", "assignment", "list")


def test_assignment_not_verified_is_explicit_failure() -> None:
    cli = Mock()
    cli.run.return_value = []
    with patch.object(setup.time, "sleep"), pytest.raises(RuntimeError, match="확인되지"):
        setup.ensure_assignment(cli, PRINCIPAL, "User", f"/subscriptions/{SID}", setup.ROLES["Reader"])


@pytest.mark.parametrize("change", ["write", "wildcard", "root", "built-in"])
def test_rejects_overprivileged_existing_custom_role(change: str) -> None:
    spec = setup.role_spec([SID])
    role = {
        "roleType": "CustomRole",
        "assignableScopes": spec["AssignableScopes"],
        "permissions": [{
            "actions": [], "notActions": [], "notDataActions": [],
            "dataActions": list(spec["DataActions"]),
        }],
    }
    if change == "write":
        role["permissions"][0]["actions"] = ["Microsoft.Resources/deployments/write"]
    elif change == "wildcard":
        role["permissions"][0]["dataActions"] = ["Microsoft.CognitiveServices/*"]
    elif change == "root":
        role["assignableScopes"] = ["/"]
    else:
        role["roleType"] = "BuiltInRole"
    with pytest.raises(ValueError):
        setup.verify_custom_role(role, spec)


def test_tenant_mismatch_stops_before_creating_identity() -> None:
    cli = Mock()
    cli.run.return_value = {"tenantId": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"}
    with pytest.raises(ValueError, match="테넌트"):
        setup.execute(setup.parser().parse_args(arguments("--apply")), cli)
    assert cli.run.call_count == 1


def test_duplicate_sp_names_are_not_arbitrarily_selected() -> None:
    cli = Mock()
    cli.run.return_value = [
        {"displayName": "diagnostic", "id": PRINCIPAL},
        {"displayName": "diagnostic", "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"},
    ]
    args = setup.parser().parse_args([
        "--tenant-id", TENANT, "--subscriptions", SID,
        "--account-type", "service-principal", "--account-name", "diagnostic",
    ])
    with pytest.raises(ValueError, match="여러 개"):
        setup.resolve_principal(cli, args)


def test_user_creation_never_prompts_for_or_passes_password() -> None:
    assert setup.main(arguments("--account-type", "user", "--create-principal")) == 1


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "setup.json"
    path.write_text(json.dumps({
        "tenant_id": TENANT, "subscription_ids": [SID],
        "account_type": "service-principal", "account_name": "diagnostic",
        "principal_id": PRINCIPAL,
        "client_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    }), encoding="utf-8")
    return path


def test_config_plan_needs_no_repeated_ids_or_azure(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "result.json"
    with patch.object(setup, "AzureCLI", side_effect=AssertionError("must not authenticate")):
        assert setup.main([
            "--config-file", str(config_file), "--result-file", str(output), "--dry-run",
        ]) == 0
    plan = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert plan["subscriptions"] == [SID]
    assert plan["subscription_roles"] == list(setup.DEFAULT_ROLES)
    assert plan["graph_application_roles"] == list(setup.ENTRA_GRAPH_ROLES)
    assert plan["foundry_custom_role"]["DataActions"] == setup.role_spec([SID])["DataActions"]
    assert plan["foundry_project_scopes"] == [f"/subscriptions/{SID}"]
    assert not output.exists()


@pytest.mark.parametrize("data", [
    [], {"tenant_id": "not-a-uuid"}, {"subscription_ids": "not-an-array"},
    {"subscription_ids": []}, {"subscription_ids": [123]}, {"account_type": "owner"},
])
def test_invalid_config_fails_before_azure(
    config_file: Path, data: object,
) -> None:
    if isinstance(data, dict):
        merged = json.loads(config_file.read_text(encoding="utf-8"))
        merged.update(data)
    else:
        merged = data
    config_file.write_text(json.dumps(merged), encoding="utf-8")
    with patch.object(setup, "AzureCLI", side_effect=AssertionError("must not authenticate")):
        assert setup.main(["--config-file", str(config_file)]) == 1


def test_login_is_device_code_and_does_not_change_parent_environment(config_file: Path) -> None:
    original = os.environ.get("AZURE_CORE_LOGIN_EXPERIENCE_V2")
    with patch.object(setup, "cli_prefix", return_value=["az"]), patch.object(
        setup.subprocess, "run", return_value=Mock(returncode=0),
    ) as run:
        assert setup.main(["--config-file", str(config_file), "--login"]) == 0
    assert run.call_args.args[0] == [
        "az", "login", "--tenant", TENANT, "--use-device-code", "--output", "none",
    ]
    assert run.call_args.kwargs["env"]["AZURE_CORE_LOGIN_EXPERIENCE_V2"] == "off"
    assert os.environ.get("AZURE_CORE_LOGIN_EXPERIENCE_V2") == original


@pytest.mark.parametrize("supplied_principal", [None, PRINCIPAL, "dddddddd-dddd-4ddd-8ddd-dddddddddddd"])
def test_apply_reuses_identity_and_persists_only_allowlisted_metadata(
    config_file: Path, tmp_path: Path, supplied_principal: str | None,
) -> None:
    config = json.loads(config_file.read_text(encoding="utf-8"))
    config["principal_id"] = supplied_principal
    config_file.write_text(json.dumps(config), encoding="utf-8")
    output = tmp_path / "result.json"
    client_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    cli = Mock()

    def run(*args: str) -> object:
        if args[:2] == ("account", "show"):
            return {"tenantId": TENANT}
        if args[:3] == ("ad", "sp", "show"):
            return {
                "id": PRINCIPAL, "appId": client_id, "displayName": "diagnostic",
                "passwordCredentials": [{"secretText": "must-not-be-persisted"}],
            }
        if args[:3] == ("role", "definition", "list"):
            spec = setup.role_spec([SID])
            return [{
                "name": "dddddddd-dddd-4ddd-8ddd-dddddddddddd", "roleType": "CustomRole",
                "assignableScopes": spec["AssignableScopes"],
                "permissions": [{"dataActions": spec["DataActions"]}],
            }]
        if args[:3] == ("role", "assignment", "list"):
            return [{
                "principalId": PRINCIPAL, "scope": f"/subscriptions/{SID}",
                "roleDefinitionId": setup.ROLES["Reader"],
            }]
        raise AssertionError(f"Unexpected mutation: {args[:3]}")

    cli.run.side_effect = run
    with patch.object(setup, "AzureCLI", return_value=cli), patch.object(
        setup, "ensure_assignment",
    ) as assign, patch.object(setup, "ensure_graph_roles", return_value=list(setup.ENTRA_GRAPH_ROLES)) as graph:
        assert setup.main([
            "--config-file", str(config_file), "--result-file", str(output), "--apply",
        ]) == 0
    text = output.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["principal_id"] == PRINCIPAL
    assert payload["client_id"] == client_id
    assert payload["verified_assignments"][0]["role"] == "Reader"
    assert payload["diagnostic_preflight"] == "not_run"
    assert assign.call_count == len(setup.DEFAULT_ROLES) + 1
    graph.assert_called_once_with(cli, PRINCIPAL)
    assert payload["verified_graph_roles"] == list(setup.ENTRA_GRAPH_ROLES)
    assert "must-not-be-persisted" not in text
    assert "passwordCredentials" not in text


def test_failed_apply_does_not_replace_previous_result(config_file: Path, tmp_path: Path) -> None:
    output = tmp_path / "previous.json"
    output.write_text('{"previous": true}', encoding="utf-8")
    cli = Mock()
    cli.run.side_effect = RuntimeError("fixture failure")
    with patch.object(setup, "AzureCLI", return_value=cli):
        assert setup.main([
            "--config-file", str(config_file), "--result-file", str(output), "--apply",
        ]) == 1
    assert json.loads(output.read_text(encoding="utf-8")) == {"previous": True}


def test_verify_requires_sp_authentication_instead_of_using_admin_cli(config_file: Path) -> None:
    with patch.dict(setup.os.environ, {}, clear=True), patch.object(
        setup.subprocess, "run", side_effect=AssertionError("must not fall back"),
    ):
        assert setup.main(["--config-file", str(config_file), "--verify"]) == 1


@pytest.mark.parametrize("flag", ["--cost-reader", "--create-principal", "--security-reader"])
def test_verify_refuses_role_or_identity_changes(config_file: Path, flag: str) -> None:
    with patch.object(setup.subprocess, "run", side_effect=AssertionError("must not mutate")):
        assert setup.main(["--config-file", str(config_file), "--verify", flag]) == 1


def test_verify_passes_saved_ids_and_certificate_without_login(
    config_file: Path, tmp_path: Path,
) -> None:
    certificate = tmp_path / "placeholder.pem"
    certificate.write_text("test placeholder; not a private key", encoding="utf-8")
    with patch.dict(setup.os.environ, {}, clear=True), patch.object(
        setup.subprocess, "run", return_value=Mock(returncode=2),
    ) as run:
        assert setup.main([
            "--config-file", str(config_file), "--verify",
            "--certificate-path", str(certificate),
        ]) == 2
    command = run.call_args.args[0]
    assert command[command.index("--expected-principal-id") + 1] == PRINCIPAL
    assert command[command.index("--subscriptions") + 1:] == [SID]
    assert "login" not in command
    environment = run.call_args.kwargs["env"]
    assert environment["AZURE_TENANT_ID"] == TENANT
    assert environment["AZURE_CLIENT_ID"] == "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    assert environment["AZURE_CLIENT_CERTIFICATE_PATH"] == str(certificate.resolve())
    assert "test placeholder" not in str(run.call_args)


@pytest.mark.parametrize("environment", [
    {"AZURE_CLIENT_SECRET": "not-a-real-secret"},
    {"AZURE_TENANT_ID": "dddddddd-dddd-4ddd-8ddd-dddddddddddd"},
    {"AZURE_CLIENT_CERTIFICATE_PATH": "missing.pem"},
    {"AZURE_CLIENT_CERTIFICATE_PATH": "file.pem", "AZURE_FEDERATED_TOKEN_FILE": "token"},
])
def test_verify_rejects_conflicting_or_missing_credentials(
    config_file: Path, environment: dict[str, str], capsys: pytest.CaptureFixture[str],
) -> None:
    with patch.dict(setup.os.environ, environment, clear=True), patch.object(
        setup.subprocess, "run", side_effect=AssertionError("must not fall back"),
    ):
        assert setup.main(["--config-file", str(config_file), "--verify"]) == 1
    assert "not-a-real-secret" not in capsys.readouterr().err


def test_verify_supports_federation_without_certificate(config_file: Path, tmp_path: Path) -> None:
    token_file = tmp_path / "placeholder-token"
    token_file.write_text("fixture, not a token", encoding="utf-8")
    with patch.dict(setup.os.environ, {"AZURE_FEDERATED_TOKEN_FILE": str(token_file)}, clear=True):
        args = setup.parser().parse_args(["--config-file", str(config_file), "--verify"])
        setup.load_config(args)
        env = setup.verify_environment(args)
    assert env["AZURE_FEDERATED_TOKEN_FILE"] == str(token_file)
    assert env["AZURE_TENANT_ID"] == TENANT


def test_entra_reader_assigns_only_missing_graph_application_roles_and_is_idempotent() -> None:
    graph_id = "99999999-9999-4999-8999-999999999999"
    values = list(setup.ENTRA_GRAPH_ROLES)
    ids = {value: f"00000000-0000-4000-8000-{index:012d}" for index, value in enumerate(values, 1)}
    assigned: list[dict] = [{"resourceId": graph_id, "appRoleId": ids[values[0]]}]
    client_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    requested = [
        {"resourceAppId": "other-api", "resourceAccess": [{"id": "preserve", "type": "Scope"}]},
        {"resourceAppId": setup.GRAPH_APP_ID, "resourceAccess": [{"id": ids[values[0]], "type": "Role"}]},
    ]
    calls: list[tuple[str, ...]] = []

    class FakeCLI:
        def run(self, *args: str):
            calls.append(args)
            if args[:3] == ("ad", "sp", "show"):
                if args[-1] != setup.GRAPH_APP_ID:
                    return {"appId": client_id}
                return {"id": graph_id, "appRoles": [
                    {"id": ids[value], "value": value, "allowedMemberTypes": ["Application"]} for value in values
                ] + [{"id": "x", "value": "Delegated.Only", "allowedMemberTypes": ["User"]}]}
            if args[:4] == ("ad", "app", "permission", "list"):
                return requested
            if args[:4] == ("ad", "app", "permission", "add"):
                assert args[args.index("--api") + 1] == setup.GRAPH_APP_ID
                requested[1]["resourceAccess"].extend(
                    {"id": value.removesuffix("=Role"), "type": "Role"}
                    for value in args[args.index("--api-permissions") + 1:]
                )
                return {}
            if args[:3] == ("rest", "--method", "GET"):
                return {"value": list(assigned)}
            if args[:3] == ("rest", "--method", "POST"):
                body = json.loads(args[args.index("--body") + 1])
                assigned.append({"resourceId": body["resourceId"], "appRoleId": body["appRoleId"]})
                return {}
            raise AssertionError(args)

    principal = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert setup.ensure_graph_roles(FakeCLI(), principal) == values
    posts = [call for call in calls if call[:3] == ("rest", "--method", "POST")]
    assert len(posts) == len(values) - 1
    assert all(f"/servicePrincipals/{principal}/appRoleAssignments" in call[call.index("--url") + 1] for call in posts)
    calls.clear()
    setup.ensure_graph_roles(FakeCLI(), principal)
    assert not [call for call in calls if call[:3] == ("rest", "--method", "POST")]
    assert not [call for call in calls if call[:4] == ("ad", "app", "permission", "add")]
    assert requested[0]["resourceAccess"] == [{"id": "preserve", "type": "Scope"}]


def test_default_graph_roles_match_collector_and_do_not_include_retired_diagnostics() -> None:
    from easm_agent.collect_agent365 import Agent365Collector
    from easm_agent.collect_entra import EntraCollector

    assert setup.ENTRA_GRAPH_ROLES == EntraCollector.required_roles + Agent365Collector.required_roles
    assert set(setup.ENTRA_GRAPH_ROLES) == {
        "AgentIdentity.Read.All", "AgentIdentityBlueprint.Read.All", "Application.Read.All",
        "CopilotPackages.Read.All",
    }


def test_default_apply_creates_only_read_foundry_role_and_grants_full_bundle(config_file: Path) -> None:
    args = setup.parser().parse_args(["--config-file", str(config_file), "--apply"])
    setup.load_config(args)
    spec = setup.role_spec([SID])
    role = {
        "name": "dddddddd-dddd-4ddd-8ddd-dddddddddddd", "roleType": "CustomRole",
        "assignableScopes": spec["AssignableScopes"],
        "permissions": [{"dataActions": spec["DataActions"]}],
    }
    cli = Mock()
    created = False

    def run(*command: str):
        nonlocal created
        if command[:2] == ("account", "show"):
            return {"tenantId": TENANT}
        if command[:3] == ("ad", "sp", "show"):
            return {"id": PRINCIPAL, "appId": args.client_id, "displayName": args.account_name}
        if command[:3] == ("role", "definition", "list"):
            return [role] if created else []
        if command[:3] == ("role", "definition", "create"):
            definition = json.loads(command[command.index("--role-definition") + 1])
            assert definition == spec and definition["Actions"] == []
            created = True
            return role
        raise AssertionError(command)

    cli.run.side_effect = run
    with patch.object(setup, "ensure_assignment") as assign, patch.object(
        setup, "ensure_graph_roles", return_value=list(setup.ENTRA_GRAPH_ROLES),
    ) as graph:
        setup.execute(args, cli)
    assert created and assign.call_count == 5
    assert {call.args[3] for call in assign.call_args_list} == {f"/subscriptions/{SID}"}
    assert {call.args[4] for call in assign.call_args_list} == {
        *(setup.ROLES[name] for name in setup.DEFAULT_ROLES), role["name"],
    }
    graph.assert_called_once_with(cli, PRINCIPAL)


def test_entra_reader_requires_available_roles_and_is_apply_only(config_file: Path) -> None:
    class MissingCLI:
        def run(self, *args: str):
            return {"id": "g", "appRoles": []}

    with pytest.raises(ValueError, match="AgentIdentity.Read.All"):
        setup.ensure_graph_roles(MissingCLI(), "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    with patch.object(setup.subprocess, "run", side_effect=AssertionError("must not call Azure")):
        assert setup.main(["--config-file", str(config_file), "--verify", "--entra-reader"]) == 1
        with pytest.raises(SystemExit) as exc:
            setup.main(["--config-file", str(config_file), "--dry-run", "--no-entra"])
        assert exc.value.code == 2


def test_verify_always_checks_entra_and_rejects_skip(config_file: Path, tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("fixture", encoding="utf-8")
    with patch.dict(setup.os.environ, {"AZURE_FEDERATED_TOKEN_FILE": str(token_file)}, clear=True), patch.object(
        setup.subprocess, "run", return_value=Mock(returncode=0),
    ) as run:
        assert setup.main(["--config-file", str(config_file), "--verify"]) == 0
        assert "--no-entra" not in run.call_args.args[0]
        with pytest.raises(SystemExit) as exc:
            setup.main(["--config-file", str(config_file), "--verify", "--no-entra"])
        assert exc.value.code == 2


def test_graph_consent_failure_explains_pim_and_retains_original_error() -> None:
    cli = Mock()
    role = "Application.Read.All"
    graph_id, role_id = "graph-service-principal", "role-id"
    cli.run.side_effect = [
        {"id": graph_id, "appRoles": [{"id": role_id, "value": role, "allowedMemberTypes": ["Application"]}]},
        {"appId": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"},
        [{"resourceAppId": setup.GRAPH_APP_ID, "resourceAccess": [{"id": role_id, "type": "Role"}]}],
        {"value": []},
        RuntimeError("Graph denied: Authorization_RequestDenied"),
    ]
    with pytest.raises(RuntimeError, match="관리자 동의가 완료되지") as error:
        setup.ensure_graph_roles(cli, PRINCIPAL, (role,))
    message = str(error.value)
    assert "Privileged Role Administrator" in message and "Global Reader" in message
    assert "bash setup.sh login --login-resource graph" in message
    assert "기존 Azure 역할 할당은 유지" in message and "Authorization_RequestDenied" in message
    assert cli.run.call_args.args[:3] == ("rest", "--method", "POST")
    assert cli.run.call_count == 5


@pytest.mark.parametrize("error_code", ["Authorization_RequestDenied", "Request_BadRequest"])
def test_cli_failure_exposes_only_fixed_safe_error_code_not_response_body(error_code: str) -> None:
    cli = object.__new__(setup.AzureCLI)
    cli.prefix = ["az"]
    response = subprocess.CompletedProcess(
        [], 1, stdout="secret-stdout", stderr=f'ERROR: {{"error":{{"code":"{error_code}",'
        '"message":"secret-token someone@example.invalid"}}}',
    )
    with patch.object(setup.subprocess, "run", return_value=response), pytest.raises(RuntimeError) as error:
        cli.run("rest", "--method", "POST", "--body", '{"secret":"never-print"}')
    message = str(error.value)
    assert f"code={error_code}" in message
    assert all(value not in message for value in ("secret-token", "someone@example.invalid", "never-print", "secret-stdout"))


def bash_executable() -> str:
    if os.name == "nt":
        path = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        if path.is_file():
            return str(path)
    else:
        path = shutil.which("bash")
        if path:
            return path
    pytest.skip("Bash is not installed")


@pytest.mark.parametrize("command", ["plan", "apply"])
def test_bash_does_not_allow_mode_override(command: str, config_file: Path) -> None:
    script = Path(__file__).parents[1] / "scripts" / "setup.sh"
    result = subprocess.run(
        [bash_executable(), str(script), command, "--dry-run", "--config-file", str(config_file)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "Choose the mode" in result.stderr


def test_bash_plan_runs_end_to_end_without_azure(config_file: Path, tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "scripts" / "setup.sh"
    output = tmp_path / "result.json"
    environment = os.environ.copy()
    environment["EASM_AGENT_PYTHON"] = sys.executable
    environment["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run([
        bash_executable(), str(script), "plan", "--config-file", str(config_file),
        "--result-file", str(output), "--monitoring-reader",
    ], capture_output=True, text=True, encoding="utf-8", env=environment, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.split("\n", 1)[1])
    assert payload["account_name"] == "diagnostic"
    assert payload["subscription_roles"] == [*setup.DEFAULT_ROLES, "Monitoring Reader"]
    assert not output.exists()


def test_customer_handoff_plan_runs_without_repository_or_installed_collector(
    config_file: Path, tmp_path: Path,
) -> None:
    customer = tmp_path / "customer"
    customer.mkdir()
    scripts = Path(__file__).parents[1] / "scripts"
    for name in ("setup_account.py", "foundry-reader.json"):
        shutil.copyfile(scripts / name, customer / name)
    shutil.copyfile(config_file, customer / "setup.json")
    environment = {
        **os.environ, "PYTHONPATH": "", "PATH": "", "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run([
        sys.executable, "-I", "-X", "utf8", str(customer / "setup_account.py"),
        "--config-file", "setup.json", "--dry-run",
    ], cwd=customer, env=environment, capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.split("\n", 1)[1])
    assert payload["subscription_roles"] == list(setup.DEFAULT_ROLES)
    assert payload["foundry_custom_role"]["DataActions"] == setup.role_spec([SID])["DataActions"]
    assert payload["graph_application_roles"] == list(setup.ENTRA_GRAPH_ROLES)
    assert {file.name for file in customer.iterdir()} == {
        "setup_account.py", "foundry-reader.json", "setup.json",
    }


def test_customer_bash_plan_uses_colocated_setup_without_repository(
    config_file: Path, tmp_path: Path,
) -> None:
    customer = tmp_path / "customer"
    customer.mkdir()
    scripts = Path(__file__).parents[1] / "scripts"
    for name in ("setup.sh", "setup_account.py", "foundry-reader.json"):
        shutil.copyfile(scripts / name, customer / name)
    shutil.copyfile(config_file, customer / "setup.json")
    original = (customer / "setup.json").read_bytes()
    environment = {
        **os.environ, "EASM_AGENT_PYTHON": sys.executable, "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [bash_executable(), str(customer / "setup.sh"), "plan"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.split("\n", 1)[1])
    assert payload["subscription_roles"] == list(setup.DEFAULT_ROLES)
    assert payload["graph_application_roles"] == list(setup.ENTRA_GRAPH_ROLES)
    assert (customer / "setup.json").read_bytes() == original
    assert not (tmp_path / ".easm-agent").exists()


@pytest.mark.parametrize("command", ["login", "apply"])
def test_customer_bash_modes_forward_colocated_input_and_output(command: str, tmp_path: Path) -> None:
    customer = tmp_path / "customer"
    customer.mkdir()
    shutil.copyfile(Path(__file__).parents[1] / "scripts" / "setup.sh", customer / "setup.sh")
    (customer / "setup_account.py").write_text(
        "import json,sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8",
    )
    environment = {**os.environ, "EASM_AGENT_PYTHON": sys.executable}
    result = subprocess.run(
        [bash_executable(), str(customer / "setup.sh"), command],
        cwd=tmp_path, env=environment, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr
    args = json.loads(result.stdout)
    for flag in ("--config-file", "--result-file"):
        assert Path(args[args.index(flag) + 1]).resolve() == (customer / "setup.json").resolve()
    assert args[-1] == "--" + command


def test_customer_bash_verify_requires_ms_repository(tmp_path: Path) -> None:
    script = tmp_path / "setup.sh"
    shutil.copyfile(Path(__file__).parents[1] / "scripts" / "setup.sh", script)
    result = subprocess.run(
        [bash_executable(), str(script), "verify"],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 1
    assert "verify must run in the MS repository" in result.stderr
