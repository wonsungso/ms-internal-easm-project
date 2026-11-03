from __future__ import annotations

import base64
import json
import subprocess
import zipfile
from io import BytesIO
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


def test_codespace_download_uses_validated_ssh_stream(tmp_path: Path) -> None:
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
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("report.html", "fixture report")
    name = "wasm-agent-results-20261103T080000Z-abcdef.zip"
    commands = []

    def cli(*args, **kwargs):
        commands.append(args)
        command = args[-1]
        text = ""
        if "mktemp" in command:
            text = "/home/vscode/wasm-agent-auth-12345678\n"
        elif "WASM_COLLECTION_EXIT" in command:
            text = "WASM_COLLECTION_EXIT=2\n"
        elif command.startswith("find "):
            text = name + "\n"
        elif command.startswith("base64 "):
            text = base64.b64encode(buffer.getvalue()).decode()
        return subprocess.CompletedProcess(args, 0, text, "")

    with patch.object(remote, "ROOT", tmp_path), patch.object(remote, "gh", side_effect=cli), patch.object(
        remote, "TemporaryCertificate",
    ) as certificate:
        certificate.return_value.__enter__.return_value = {"AZURE_CLIENT_CERTIFICATE_PATH": "fixture.pem"}
        remote.run("approved-codespace")
    assert (output / "codespace-e2e" / name).read_bytes() == buffer.getvalue()
    proof = json.loads((output / "codespace-e2e-verification.json").read_text(encoding="utf-8"))
    assert proof["collection_exit_code"] == 2 and proof["remote_private_key_cleaned"]
    assert any(command[-1].startswith("base64 ") for command in commands)
