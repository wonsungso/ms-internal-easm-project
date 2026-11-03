from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

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
