from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.lab import codespace_collect as remote


def test_codespace_name_cannot_inject_shell() -> None:
    with pytest.raises(ValueError):
        remote.run("name;rm something")


def test_remote_key_is_removed_on_collection_failure(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "setup.json").write_text(json.dumps({
        "tenant_id": "tenant", "client_id": "client", "principal_id": "reader",
        "subscription_ids": ["subscription"],
    }), encoding="utf-8")
    (output / "lab.json").write_text(json.dumps({
        "project_id": "project", "project_endpoint": "https://example.test",
    }), encoding="utf-8")
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.yaml").write_text(yaml.safe_dump({
        "allowed_models_file": "allowed.yaml", "criteria_file": "criteria.yaml",
        "tag_conventions_file": "tags.yaml",
    }), encoding="utf-8")
    commands = []

    def cli(*args, **kwargs):
        commands.append(args)
        if "mktemp" in args[-1]:
            return subprocess.CompletedProcess(args, 0, "/home/vscode/wasm-agent-auth-12345678\n", "")
        if "WASM_COLLECTION_EXIT" in args[-1]:
            raise RuntimeError("fixture remote failure")
        return subprocess.CompletedProcess(args, 0, "", "")

    with patch.object(remote, "ROOT", tmp_path), patch.object(remote, "gh", side_effect=cli), patch.object(
        remote, "TemporaryCertificate",
    ) as certificate:
        certificate.return_value.__enter__.return_value = {"AZURE_CLIENT_CERTIFICATE_PATH": "fixture.pem"}
        with pytest.raises(RuntimeError, match="fixture remote failure"):
            remote.run("approved-codespace")
        certificate.return_value.__exit__.assert_called_once()
    assert any("rm -f /home/vscode/wasm-agent-auth-12345678/credential.pem" in cmd[-1] for cmd in commands)
