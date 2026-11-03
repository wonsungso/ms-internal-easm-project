from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scripts.setup import setup_account as setup

SID = "11111111-1111-4111-8111-111111111111"
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PRINCIPAL = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PROJECT = f"/subscriptions/{SID}/resourceGroups/test/providers/Microsoft.CognitiveServices/accounts/test/projects/p"


def arguments(*extra: str) -> list[str]:
    return [
        "--tenant-id", TENANT, "--subscriptions", SID,
        "--account-type", "user", "--account-name", "diagnostic@example.invalid",
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
    assert setup.main(arguments("--create-principal")) == 1


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
            "--cost-reader",
        ]) == 0
    plan = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert plan["subscriptions"] == [SID]
    assert plan["subscription_roles"] == ["Reader", "Cost Management Reader"]
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


def test_apply_reuses_identity_and_persists_only_allowlisted_metadata(
    config_file: Path, tmp_path: Path,
) -> None:
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
        if args[:3] == ("role", "assignment", "list"):
            return [{
                "principalId": PRINCIPAL, "scope": f"/subscriptions/{SID}",
                "roleDefinitionId": setup.ROLES["Reader"],
            }]
        raise AssertionError(f"Unexpected mutation: {args[:3]}")

    cli.run.side_effect = run
    with patch.object(setup, "AzureCLI", return_value=cli):
        assert setup.main([
            "--config-file", str(config_file), "--result-file", str(output), "--apply",
        ]) == 0
    text = output.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["principal_id"] == PRINCIPAL
    assert payload["client_id"] == client_id
    assert payload["verified_assignments"][0]["role"] == "Reader"
    assert payload["diagnostic_preflight"] == "not_run"
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
    script = Path(__file__).parents[1] / "scripts" / "setup" / "manage.sh"
    result = subprocess.run(
        [bash_executable(), str(script), command, "--dry-run", "--config-file", str(config_file)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "Choose the mode" in result.stderr


def test_bash_plan_runs_end_to_end_without_azure(config_file: Path, tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "scripts" / "setup" / "manage.sh"
    output = tmp_path / "result.json"
    environment = os.environ.copy()
    environment["WASM_AGENT_PYTHON"] = sys.executable
    environment["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run([
        bash_executable(), str(script), "plan", "--config-file", str(config_file),
        "--result-file", str(output), "--monitoring-reader",
    ], capture_output=True, text=True, encoding="utf-8", env=environment, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.split("\n", 1)[1])
    assert payload["account_name"] == "diagnostic"
    assert payload["subscription_roles"] == ["Reader", "Monitoring Reader"]
    assert not output.exists()
