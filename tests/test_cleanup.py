from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import cleanup_account as cleanup
from scripts.setup_account import role_spec

SID = "11111111-1111-4111-8111-111111111111"
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CLIENT = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
PRINCIPAL = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ROLE = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
OTHER = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


@pytest.fixture
def target() -> dict:
    return {
        "tenant_id": TENANT, "client_id": CLIENT, "principal_id": PRINCIPAL,
        "account_type": "service-principal", "account_name": "wasmagent-diagnostic",
        "subscription_ids": [SID],
    }


class FakeCLI:
    def __init__(self) -> None:
        self.calls = []
        self.app, self.sp, self.role = True, True, True
        self.name = "wasmagent-diagnostic"
        self.eligible = False
        self.deny_pim = False
        self.assignments = [{
            "id": f"/subscriptions/{SID}/providers/Microsoft.Authorization/roleAssignments/target",
            "principalId": PRINCIPAL,
            "roleDefinitionId": f"/subscriptions/{SID}/providers/Microsoft.Authorization/roleDefinitions/{ROLE}",
        }]

    @property
    def mutations(self) -> list:
        return [call for call in self.calls if "delete" in call or "create" in call or "POST" in call]

    def run(self, *args):
        self.calls.append(args)
        if args[:2] == ("account", "show"):
            return {"tenantId": TENANT}
        if args[:3] == ("ad", "app", "list"):
            return [{"id": CLIENT, "appId": CLIENT, "displayName": self.name,
                     "signInAudience": "AzureADMyOrg"}] if self.app else []
        if args[:3] == ("ad", "sp", "list"):
            return [{"id": PRINCIPAL, "appId": CLIENT, "displayName": self.name,
                     "servicePrincipalType": "Application"}] if self.sp else []
        if args[:3] == ("role", "assignment", "list"):
            return deepcopy(self.assignments)
        if args[:3] == ("role", "definition", "list"):
            spec = role_spec([SID])
            return [{
                "name": ROLE, "roleName": spec["Name"], "roleType": "CustomRole",
                "assignableScopes": spec["AssignableScopes"],
                "permissions": [{"dataActions": spec["DataActions"]}],
            }] if self.role else []
        if args[:3] == ("rest", "--method", "GET"):
            if self.deny_pim:
                raise RuntimeError("PIM permission denied")
            return {"value": [{"properties": {"roleDefinitionId": f"/roles/{ROLE}"}}] if self.eligible else []}
        if args[:3] == ("role", "assignment", "delete"):
            identifier = args[args.index("--ids") + 1]
            self.assignments = [row for row in self.assignments if row["id"] != identifier]
            return None
        if args[:3] == ("ad", "app", "delete"):
            self.app = self.sp = False
            return None
        if args[:3] == ("ad", "sp", "delete"):
            self.sp = False
            return None
        if args[:3] == ("role", "definition", "delete"):
            self.role = False
            return None
        raise AssertionError(args)


def test_plan_has_no_mutations(target: dict) -> None:
    cli = FakeCLI()
    result = cleanup.execute(cli, target, False)
    assert result["role_assignments"] == 1 and result["applications"] == 1
    assert result["custom_role"] == "delete_after_target_assignments" and not cli.mutations


def test_apply_deletes_only_exact_identity_and_then_unused_custom_role(target: dict) -> None:
    cli = FakeCLI()
    result = cleanup.execute(cli, target, True)
    assert result["custom_role"] == "deleted"
    assert not cli.app and not cli.sp and not cli.assignments and not cli.role
    assert [call[:3] for call in cli.mutations] == [
        ("role", "assignment", "delete"), ("ad", "app", "delete"), ("role", "definition", "delete"),
    ]
    assert not result["demo_resources_modified"] and not result["permanent_delete"]
    assert cleanup.execute(cli, target, True)["custom_role"] == "already_absent"
    assert len(cli.mutations) == 3


@pytest.mark.parametrize("eligible", [True, False])
def test_shared_or_eligible_role_is_preserved(target: dict, eligible: bool) -> None:
    cli = FakeCLI()
    cli.eligible = eligible
    if not eligible:
        cli.assignments.append({
            "id": f"/subscriptions/{SID}/providers/Microsoft.Authorization/roleAssignments/other",
            "principalId": OTHER, "roleDefinitionId": f"/roles/{ROLE}",
        })
    result = cleanup.execute(cli, target, True)
    assert result["custom_role"] == ("retained_eligible" if eligible else "retained_in_use")
    assert cli.role is True and not cli.app and not cli.sp
    assert not any(call[:3] == ("role", "definition", "delete") for call in cli.calls)
    if not eligible:
        assert cli.assignments[0]["principalId"] == OTHER


def test_pim_lookup_failure_does_not_mean_unused_and_prevents_deletion(target: dict) -> None:
    cli = FakeCLI()
    cli.deny_pim = True
    with pytest.raises(RuntimeError, match="PIM permission denied"):
        cleanup.execute(cli, target, True)
    assert not cli.mutations and cli.app and cli.sp and cli.role


@pytest.mark.parametrize("field,value", [
    ("tenant_id", OTHER), ("principal_id", OTHER), ("client_id", OTHER), ("account_name", "wrong-name"),
])
def test_identity_mismatch_causes_no_mutations(target: dict, field: str, value: str) -> None:
    cli = FakeCLI()
    target[field] = value
    with pytest.raises(ValueError):
        cleanup.execute(cli, target, True)
    assert not cli.mutations


def test_orphan_sp_and_role_assignments_can_be_cleaned_after_app_is_absent(target: dict) -> None:
    cli = FakeCLI()
    cli.app = False
    result = cleanup.execute(cli, target, True)
    assert result["service_principals"] == 0
    assert any(call[:3] == ("ad", "sp", "delete") for call in cli.calls)


def test_out_of_scope_assignment_is_not_deleted(target: dict) -> None:
    cli = FakeCLI()
    cli.assignments[0]["id"] = f"/subscriptions/{OTHER}/providers/Microsoft.Authorization/roleAssignments/x"
    with pytest.raises(ValueError, match="승인 구독 밖"):
        cleanup.execute(cli, target, True)
    assert not cli.mutations


@pytest.mark.parametrize("name", ["wasmagent-lc-demo-chat-login", "wasmagent-lab-AgentIdentityBlueprint"])
def test_demo_names_are_rejected_before_cloud_calls(tmp_path: Path, target: dict, name: str) -> None:
    target["account_name"] = name
    path = tmp_path / "setup.json"
    path.write_text(json.dumps(target), encoding="utf-8")
    with patch.object(cleanup, "AzureCLI", side_effect=AssertionError("No Azure calls")):
        assert cleanup.main(["--config-file", str(path), "--apply"]) == 1


def test_setup_cannot_be_overwritten_even_when_apply_requested(tmp_path: Path, target: dict) -> None:
    path = tmp_path / "setup.json"
    path.write_text(json.dumps(target), encoding="utf-8")
    with patch.object(cleanup, "AzureCLI", side_effect=AssertionError("No Azure calls")):
        assert cleanup.main(["--config-file", str(path), "--result-file", str(path), "--apply"]) == 1
    assert json.loads(path.read_text(encoding="utf-8")) == target


def test_successful_cleanup_receipt_is_separate_from_setup(tmp_path: Path, target: dict) -> None:
    source, receipt = tmp_path / "setup.json", tmp_path / "cleanup-result.json"
    source.write_text(json.dumps(target), encoding="utf-8")
    with patch.object(cleanup, "AzureCLI", return_value=FakeCLI()):
        assert cleanup.main([
            "--config-file", str(source), "--result-file", str(receipt), "--apply",
        ]) == 0
    assert json.loads(source.read_text(encoding="utf-8")) == target
    assert json.loads(receipt.read_text(encoding="utf-8"))["custom_role"] == "deleted"


def test_pim_pagination_is_checked_and_foreign_host_is_rejected() -> None:
    from unittest.mock import Mock

    next_page = f"https://management.azure.com/subscriptions/{SID}/next?page=2"
    cli = Mock()
    cli.run.side_effect = [
        {"value": [], "nextLink": next_page},
        {"value": [{"properties": {"roleDefinitionId": f"/roles/{ROLE}"}}]},
    ]
    assert cleanup.eligible_role_usage(cli, SID, ROLE) is True
    assert cli.run.call_count == 2
    cli.reset_mock()
    cli.run.side_effect = None
    cli.run.return_value = {"value": [], "nextLink": "https://other.invalid/private"}
    with pytest.raises(ValueError, match="승인 범위 밖"):
        cleanup.eligible_role_usage(cli, SID, ROLE)
    assert cli.run.call_count == 1


def test_future_eligibility_schedule_also_prevents_role_deletion() -> None:
    from unittest.mock import Mock

    cli = Mock()
    cli.run.side_effect = [
        {"value": []},
        {"value": [{"properties": {"roleDefinitionId": f"/roles/{ROLE}"}}]},
    ]
    assert cleanup.eligible_role_usage(cli, SID, ROLE) is True
    assert "roleEligibilitySchedules?" in cli.run.call_args.args[-1]
