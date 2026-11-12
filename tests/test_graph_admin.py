from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "demo" / "graph_admin.ps1"
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def invoke(tmp_path: Path, request: dict, stub_status: int | None = None) -> tuple[int, dict]:
    shell = shutil.which("pwsh")
    if shell is None:
        pytest.skip("PowerShell 7 is unavailable")
    source, result = tmp_path / "request.json", tmp_path / "result.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    stubs = ""
    if stub_status is not None:
        content = "" if stub_status == 204 else '{"value":[]}'
        stubs = f"""
function Import-Module {{}}
function Connect-MgGraph {{}}
function Get-MgContext {{
    [pscustomobject]@{{TenantId='{TENANT}'; AuthType='Delegated'; Scopes=@('Application.ReadWrite.All')}}
}}
function Invoke-MgGraphRequest {{
    param([switch]$SkipHttpErrorCheck)
    if ({stub_status} -ge 400 -and -not $SkipHttpErrorCheck) {{
        throw [Net.Http.HttpRequestException]::new('HTTP failure')
    }}
    $r = [Net.Http.HttpResponseMessage]::new([Net.HttpStatusCode]{stub_status})
    $r.Content = [Net.Http.StringContent]::new('{content}')
    return $r
}}
"""
    command = stubs + f"""
& '{SCRIPT}' -TenantId '{TENANT}' -RequestPath '{source}' -ResponsePath '{result}'
exit $LASTEXITCODE
"""
    completed = subprocess.run(
        [shell, "-NoProfile", "-Command", command], capture_output=True, text=True, check=False,
    )
    return completed.returncode, json.loads(result.read_text(encoding="utf-8"))


@pytest.mark.parametrize("payload", [
    {"method": "GET", "path": "//untrusted.invalid/applications"},
    {"method": "PATCH", "path": "/me", "body": {"displayName": "changed"}},
    {"method": "POST", "path": "/applications/id/addPassword", "body": {}},
    {"method": "PATCH", "path": "/applications/id", "body": {"passwordCredentials": []}},
])
def test_invalid_admin_requests_fail_before_authentication(tmp_path: Path, payload: dict) -> None:
    code, result = invoke(tmp_path, payload)
    assert code == 2 and result["success"] is False
    assert result["status_code"] is None and "data" not in result


@pytest.mark.parametrize("status", [200, 204])
def test_admin_transport_preserves_empty_json_and_no_content(tmp_path: Path, status: int) -> None:
    code, result = invoke(tmp_path, {"method": "GET", "path": "/applications"}, status)
    assert code == 0 and result["success"]
    assert result["status_code"] == status
    assert result["data"] == (None if status == 204 else {"value": []})


@pytest.mark.parametrize("status", [403, 404, 429])
def test_admin_transport_preserves_http_failures(tmp_path: Path, status: int) -> None:
    code, result = invoke(tmp_path, {"method": "GET", "path": "/applications"}, status)
    assert code == 2 and result["success"] is False
    assert result["status_code"] == status and "data" not in result
