from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.lab.auth import TemporaryCertificate
from scripts.lab.bootstrap import AdminARM, plan
from scripts.lab.cleanup import main as cleanup
from scripts.lab.run import main
from wasm_agent.utils.settings import load_yaml

ROOT = Path(__file__).parents[1]


class FakeCLI:
    def __init__(self) -> None:
        self.ids = {"existing-public-certificate"}
        self.calls: list[tuple[str, ...]] = []

    def certificates(self) -> list[dict]:
        self.calls.append(("list",))
        return [{"keyId": key} for key in self.ids]

    def add(self, certificate: object, key_id: str, start: object, end: object) -> None:
        self.calls.append(("add", key_id))
        self.ids.add(key_id)

    def remove(self, key_id: str) -> None:
        self.calls.append(("remove", key_id))
        self.ids.remove(key_id)

    def close(self) -> None:
        pass


def setup_values() -> dict:
    return {
        "tenant_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "client_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "principal_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "subscription_ids": [
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
            "33333333-3333-4333-8333-333333333333",
        ],
    }


def test_certificate_cleanup_preserves_existing_keys_and_parent_environment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    directory = tmp_path / "temporary"
    directory.mkdir()
    cli = FakeCLI()
    with patch("scripts.lab.auth.tempfile.mkdtemp", return_value=str(directory)), patch(
        "scripts.lab.auth.restrict_directory",
    ), TemporaryCertificate(setup_values(), registry=cli) as environment:
        private_file = Path(environment["AZURE_CLIENT_CERTIFICATE_PATH"])
        assert private_file.is_file()
        assert environment["AZURE_CLIENT_ID"] == setup_values()["client_id"]
        assert "AZURE_CLIENT_SECRET" not in environment
        assert len(cli.ids) == 2 and "existing-public-certificate" in cli.ids
    assert not directory.exists()
    assert cli.ids == {"existing-public-certificate"}
    assert any(call[0] == "remove" and call[1] != "existing-public-certificate" for call in cli.calls)
    assert "PRIVATE KEY" not in capsys.readouterr().out


def test_certificate_cleanup_also_runs_after_collection_failure(tmp_path: Path) -> None:
    directory = tmp_path / "temporary"
    directory.mkdir()
    cli = FakeCLI()
    with patch("scripts.lab.auth.tempfile.mkdtemp", return_value=str(directory)), patch(
        "scripts.lab.auth.restrict_directory",
    ), pytest.raises(ValueError, match="fixture collection failure"):
        with TemporaryCertificate(setup_values(), registry=cli):
            raise ValueError("fixture collection failure")
    assert cli.ids == {"existing-public-certificate"}
    assert not directory.exists()


def test_acl_failure_does_not_register_any_credential(tmp_path: Path) -> None:
    directory = tmp_path / "temporary"
    directory.mkdir()
    cli = FakeCLI()
    with patch("scripts.lab.auth.tempfile.mkdtemp", return_value=str(directory)), patch(
        "scripts.lab.auth.restrict_directory", side_effect=RuntimeError("ACL failure"),
    ), pytest.raises(RuntimeError, match="ACL failure"):
        with TemporaryCertificate(setup_values(), registry=cli):
            pytest.fail("must not enter")
    assert not cli.calls
    assert not directory.exists()


def test_lab_plan_has_three_scoped_groups_and_no_secret() -> None:
    options = load_yaml(ROOT / "config" / "lab.yaml")
    result = plan(setup_values(), options)
    assert len(result["groups"]) == 3
    assert result["region"] == options["region"]
    assert result["after_run"] == "retain"
    assert result["capacity"] == 1
    assert result["budget_usd"] == 100
    assert "PRIVATE KEY" not in json.dumps(result)


def test_new_generation_changes_resource_names_without_changing_approved_scope() -> None:
    options = load_yaml(ROOT / "config" / "lab.yaml")
    original = plan(setup_values(), {key: value for key, value in options.items() if key != "generation"})
    rebuilt = plan(setup_values(), {**options, "generation": "new-run"})
    assert original["lab_id"] != rebuilt["lab_id"]
    assert original["account_name"] != rebuilt["account_name"]
    assert original["host_names"] != rebuilt["host_names"]
    assert original["groups"] == rebuilt["groups"]
    assert original["region"] == rebuilt["region"]


def test_administrator_arm_blocks_writes_outside_sample_groups() -> None:
    arm = AdminARM(None, ["/subscriptions/fixture/resourceGroups/owned"])
    with pytest.raises(ValueError, match="승인된 리소스 그룹 밖"):
        arm.request("PUT", "/subscriptions/fixture/resourceGroups/foreign/providers/Microsoft.Web/sites/x",
                    "2024-04-01", {})


def test_lab_cli_plan_does_not_construct_azure_cli(tmp_path: Path) -> None:
    settings = tmp_path / "setup.json"
    settings.write_text(json.dumps(setup_values()), encoding="utf-8")
    with patch("scripts.lab.run.AzureCLI", side_effect=AssertionError("no Azure calls")):
        assert main(["plan", "--setup-file", str(settings)]) == 0


def test_cleanup_rejects_missing_confirmation_before_azure(tmp_path: Path) -> None:
    settings = tmp_path / "setup.json"
    settings.write_text(json.dumps(setup_values()), encoding="utf-8")
    with patch("scripts.lab.cleanup.AzureCLI", side_effect=AssertionError("no Azure calls")), pytest.raises(
        ValueError, match="confirm-lab-id",
    ):
        cleanup(["--setup-file", str(settings), "--apply"])


def test_cleanup_dry_run_does_not_delete_owned_groups(tmp_path: Path) -> None:
    from unittest.mock import Mock

    setup = setup_values()
    settings = tmp_path / "setup.json"
    settings.write_text(json.dumps(setup), encoding="utf-8")
    lab = plan(setup, load_yaml(ROOT / "config" / "lab.yaml"))
    cli = Mock()
    cli.run.side_effect = [
        {"tenantId": setup["tenant_id"]},
        *[[{"name": group["name"], "tags": {"seagent-lab": lab["lab_id"]}}] for group in lab["groups"]],
    ]
    with patch("scripts.lab.cleanup.AzureCLI", return_value=cli):
        assert cleanup(["--setup-file", str(settings)]) == 0
    assert all(call.args[:2] != ("group", "delete") for call in cli.run.call_args_list)
