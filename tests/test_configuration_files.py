from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from wasm_agent import models
from wasm_agent.cli import main
from wasm_agent.models import Settings, load_criteria, load_settings

ROOT = Path(__file__).parents[1]


def test_config_directory_files_are_canonical() -> None:
    assert models.CRITERIA_FILE == ROOT / "config" / "criteria.yaml"
    assert models.CRITERIA_FILE.is_file() and (ROOT / "config" / "custom-config.yaml").is_file()
    assert not (ROOT / "criteria.yaml").exists() and not (ROOT / "custom-config.yaml").exists()
    assert not (ROOT / "src" / "wasm_agent" / "criteria.yaml").exists()
    assert not (ROOT / "config" / "config.yaml").exists()
    assert load_settings(ROOT / "config" / "custom-config.yaml").allowed_models == []


def test_current_directory_criteria_override_source_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = load_criteria()
    custom["inactivity_days"] = 120
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "criteria.yaml").write_text(yaml.safe_dump(custom), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert load_criteria()["inactivity_days"] == 120


def test_explicit_criteria_override_working_directory_and_customer_settings_take_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    custom = load_criteria()
    custom["required_retention_days"] = 45
    custom["inactivity_days"] = 120
    explicit = tmp_path / "selected.yaml"
    explicit.write_text(yaml.safe_dump(custom), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "criteria.yaml").write_text("inactivity_days: 30", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    criteria = load_criteria(Settings(criteria_file=explicit, required_retention_days=90))
    assert criteria["inactivity_days"] == 120 and criteria["required_retention_days"] == 90


def test_installed_criteria_work_without_source_or_local_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = load_criteria()
    target = tmp_path / "prefix" / "share" / "wasm-agent" / "criteria.yaml"
    target.parent.mkdir(parents=True)
    target.write_text(yaml.safe_dump(custom), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(models, "CRITERIA_FILE", tmp_path / "missing-source.yaml")
    monkeypatch.setattr(models.sysconfig, "get_path", lambda name: str(tmp_path / "prefix"))
    assert load_criteria() == custom


def test_optional_custom_config_not_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert load_settings(Path("config") / "custom-config.yaml") == Settings()
    with patch("wasm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("No Azure calls")):
        assert main(["collect", "--dry-run"]) == 0


@pytest.mark.parametrize("filename,contents", [
    ("missing.yaml", None), ("bad.yaml", "items: ["), ("list.yaml", "[]"),
])
def test_invalid_explicit_criteria_fail_before_any_azure_call(
    tmp_path: Path, filename: str, contents: str | None,
) -> None:
    path = tmp_path / filename
    if contents is not None:
        path.write_text(contents, encoding="utf-8")
    with patch("wasm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("No Azure calls")):
        assert main(["collect", "--criteria", str(path), "--dry-run"]) == 1


def test_explicit_missing_custom_config_is_not_silently_ignored(tmp_path: Path) -> None:
    with patch("wasm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("No Azure calls")):
        assert main(["collect", "--config", str(tmp_path / "missing.yaml"), "--dry-run"]) == 1
