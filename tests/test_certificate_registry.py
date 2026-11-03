from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from scripts.lab.certificates import GraphCertificates


def test_graph_certificate_operations_preserve_all_existing_keys() -> None:
    original = {
        "keyId": "11111111-1111-4111-8111-111111111111",
        "key": "public-existing-certificate", "type": "AsymmetricX509Cert", "usage": "Verify",
    }
    keys = [original.copy()]
    methods = []

    def request(method: str, url: str, **kwargs: object) -> Mock:
        methods.append(method)
        if method == "PATCH":
            keys[:] = kwargs["json"]["keyCredentials"]
            return Mock(status_code=204, content=b"")
        payload = {"value": [{"id": "22222222-2222-4222-8222-222222222222"}]} if url.endswith("/applications") else {
            "keyCredentials": [entry.copy() for entry in keys],
        }
        return Mock(status_code=200, content=b"json", json=Mock(return_value=payload))

    with patch("scripts.lab.certificates.DefaultAzureCredential"), patch(
        "scripts.lab.certificates.requests.request", side_effect=request,
    ):
        registry = GraphCertificates("33333333-3333-4333-8333-333333333333")
        certificate = Mock()
        certificate.public_bytes.return_value = b"public-der"
        now = datetime.now(UTC)
        added = "44444444-4444-4444-8444-444444444444"
        registry.add(certificate, added, now, now + timedelta(hours=4))
        assert keys[0] == original
        assert keys[1]["keyId"] == added
        registry.remove(added)
        assert keys == [original]
        assert methods.count("PATCH") == 2
        registry.close()


def test_graph_does_not_replace_unknown_existing_certificate_content() -> None:
    with patch("scripts.lab.certificates.DefaultAzureCredential"):
        registry = GraphCertificates("33333333-3333-4333-8333-333333333333")
        registry.object_id = "22222222-2222-4222-8222-222222222222"
        with patch.object(registry, "request") as request, pytest.raises(RuntimeError, match="보존할 수 없어"):
            registry.replace([{"keyId": "existing", "key": None}])
        request.assert_not_called()
        registry.close()
