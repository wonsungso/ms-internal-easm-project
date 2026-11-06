from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.package_customer_setup import ARCHIVE, FILES, ROOT, build_customer_setup


def test_committed_customer_archive_matches_sources_and_has_no_certificates(tmp_path: Path) -> None:
    generated = build_customer_setup(tmp_path / "customer-setup.zip")
    assert generated.read_bytes() == ARCHIVE.read_bytes()
    assert build_customer_setup(generated).read_bytes() == ARCHIVE.read_bytes()
    with ZipFile(ARCHIVE) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == list(FILES)
        for name in FILES:
            body = archive.read(name)
            assert body == (ROOT / "scripts" / name).read_bytes().replace(b"\r\n", b"\n")
            assert b"\r\n" not in body
            assert not name.endswith((".pem", ".key", ".pfx"))


def test_downloaded_archive_plan_runs_without_repository(tmp_path: Path) -> None:
    if os.name == "nt":
        bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        if not bash.is_file():
            pytest.skip("Bash is not installed")
        executable = str(bash)
    else:
        executable = shutil.which("bash")
        if executable is None:
            pytest.skip("Bash is not installed")
    customer = tmp_path / "customer-setup"
    with ZipFile(ARCHIVE) as archive:
        archive.extractall(customer)
    (customer / "setup.json").write_text(json.dumps({
        "tenant_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "subscription_ids": [
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
            "33333333-3333-4333-8333-333333333333",
        ],
        "account_type": "service-principal", "account_name": "wasmagent-diagnostic",
        "client_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    }), encoding="utf-8")
    result = subprocess.run(
        [executable, "setup.sh", "plan"], cwd=customer,
        env={**os.environ, "WASM_AGENT_PYTHON": sys.executable, "PYTHONIOENCODING": "utf-8",
             "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.split("\n", 1)[1])
    assert len(payload["subscriptions"]) == 3
    assert len(payload["subscription_roles"]) == 4
    assert len(payload["foundry_custom_role"]["DataActions"]) == 3
    assert len(payload["graph_application_roles"]) == 3
    assert not (tmp_path / ".wasm-agent").exists()
    help_result = subprocess.run(
        [executable, "setup.sh", "cleanup-plan", "--help"], cwd=customer,
        env={**os.environ, "WASM_AGENT_PYTHON": sys.executable, "PYTHONIOENCODING": "utf-8",
             "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "--apply" in help_result.stdout and "--config-file" in help_result.stdout
