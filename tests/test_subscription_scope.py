from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
import yaml

from wasm_agent.cli import main


def test_all_subscriptions_overrides_config_and_dry_run_never_calls_azure(
    tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"subscriptions": ["11111111-1111-4111-8111-111111111111"]}))
    with patch("wasm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("no Azure calls")):
        assert main(["collect", "--config", str(config), "--all-subscriptions", "--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["subscriptions"] == "auto-enumerate"


def test_all_subscriptions_and_explicit_scope_cannot_be_combined() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["collect", "--all-subscriptions", "--subscriptions", "a"])
    assert exc.value.code == 2


def test_auto_enumeration_handles_hundreds_and_filters_tenant_and_state(tmp_path: Path) -> None:
    from datetime import UTC, datetime
    from unittest.mock import Mock

    from wasm_agent.collect import collect
    from wasm_agent.models import Collection
    from wasm_agent.settings import load_settings

    root = Path(__file__).parents[1]
    settings = load_settings(root / "config" / "config.yaml")
    settings.tenant_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    settings.expected_principal_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    settings.evidence_dir = tmp_path / "evidence"
    ids = [str(UUID(int=index)) for index in range(1, 201)]
    rows = [{"subscriptionId": sid, "tenantId": settings.tenant_id, "state": "Enabled"} for sid in ids]
    rows += [
        {"subscriptionId": str(UUID(int=999)), "tenantId": "another-tenant", "state": "Enabled"},
        {"subscriptionId": str(UUID(int=998)), "tenantId": settings.tenant_id, "state": "Disabled"},
    ]
    http = Mock()
    http.list_arm.return_value = rows
    now = datetime.now(UTC)

    def per_subscription(sid, credential, resolved, store, instant, criteria, tags):
        assert set(resolved.subscriptions) == set(ids)
        return Collection(collected_at=instant, completed_subscriptions=[sid], facts={"inventory_complete": True})

    with patch("wasm_agent.collect.verify_identity"), patch(
        "wasm_agent.collect.ReaderHTTP", return_value=http,
    ), patch("wasm_agent.collect.collect_subscription", side_effect=per_subscription) as worker:
        result = collect(settings, Mock(), now)
    assert set(result.subscriptions) == set(ids)
    assert set(result.completed_subscriptions) == set(ids)
    assert worker.call_count == 200
    assert result.facts["inventory_complete"] is True
    http.close.assert_called_once()
