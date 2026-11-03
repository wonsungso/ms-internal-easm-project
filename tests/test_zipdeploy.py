from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scripts.lab.zipdeploy import deploy_zip


@pytest.mark.parametrize("pending_status", [200, 202])
def test_direct_zip_requires_new_successful_kudu_operation(tmp_path: Path, pending_status: int) -> None:
    archive = tmp_path / "sample.zip"
    archive.write_bytes(b"fixture")
    credential = Mock()
    credential.get_token.return_value.token = "fixture-token"
    accepted = Mock(status_code=202, headers={"Location": "https://fixture.scm.azurewebsites.net/api/deployments/new"})
    pending = Mock(status_code=pending_status)
    pending.json.return_value = {"id": "new", "status": 1, "complete": False}
    complete = Mock(status_code=200)
    complete.json.return_value = {"id": "new", "status": 4, "complete": True}
    with patch("scripts.lab.zipdeploy.requests.post", return_value=accepted), patch(
        "scripts.lab.zipdeploy.requests.get", side_effect=[pending, complete],
    ), patch("scripts.lab.zipdeploy.time.sleep"):
        result = deploy_zip(
            {"name": "fixture", "defaultHostName": "fixture.azurewebsites.net"},
            archive, credential, {"previous"},
        )
    assert result["id"] == "new"
    assert result["status"] == 4


def test_direct_zip_does_not_send_token_to_external_status_url(tmp_path: Path) -> None:
    archive = tmp_path / "sample.zip"
    archive.write_bytes(b"fixture")
    accepted = Mock(status_code=202, headers={"Location": "https://untrusted.invalid/api/deployments/new"})
    complete = Mock(status_code=200)
    complete.json.return_value = {"id": "new", "status": 4, "complete": True}
    with patch("scripts.lab.zipdeploy.requests.post", return_value=accepted), patch(
        "scripts.lab.zipdeploy.requests.get", return_value=complete,
    ) as get:
        result = deploy_zip(
            {"name": "fixture", "defaultHostName": "fixture.azurewebsites.net"}, archive, Mock(), set(),
        )
    assert result["id"] == "new"
    assert get.call_args.args[0] == "https://fixture.scm.azurewebsites.net/api/deployments/latest"


def test_direct_zip_failure_is_not_success(tmp_path: Path) -> None:
    archive = tmp_path / "sample.zip"
    archive.write_bytes(b"fixture")
    accepted = Mock(status_code=202, headers={"Location": "/api/deployments/failed"})
    failed = Mock(status_code=200)
    failed.json.return_value = {"id": "failed", "status": 3, "complete": True}
    with patch("scripts.lab.zipdeploy.requests.post", return_value=accepted), patch(
        "scripts.lab.zipdeploy.requests.get", return_value=failed,
    ), pytest.raises(RuntimeError, match="status=3"):
        deploy_zip({"name": "fixture", "defaultHostName": "fixture.azurewebsites.net"}, archive, Mock(), set())
