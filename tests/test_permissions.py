from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import requests
from azure.core.exceptions import ClientAuthenticationError

from scripts import verify_permissions as verify
from wasm_agent.azure import credential_token

SID = "11111111-1111-4111-8111-111111111111"
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PRINCIPAL = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def response(code: int, payload: dict | None = None) -> Mock:
    value = Mock()
    value.status_code = code
    value.headers = {}
    value.json.return_value = payload if payload is not None else {"value": []}
    return value


def credential() -> Mock:
    value = Mock()
    value.get_token.return_value.token = "not-a-real-token"
    return value


@pytest.mark.parametrize("url,audience", [
    ("http://management.azure.com/test", verify.ARM_SCOPE),
    ("https://management.azure.com.evil.invalid/test", verify.ARM_SCOPE),
    ("https://evil.invalid/api/projects/p", verify.AI_SCOPE),
    ("https://user:password@management.azure.com/test", verify.ARM_SCOPE),
    ("https://management.azure.com:8443/test", verify.ARM_SCOPE),
])
def test_rejects_untrusted_token_destination(url: str, audience: str) -> None:
    token_source = credential()
    session = Mock()
    http = verify.ReaderHTTP(token_source, session)
    with pytest.raises(ValueError):
        http.request("GET", url, audience)
    session.request.assert_not_called()
    token_source.get_token.assert_not_called()


@pytest.mark.parametrize("method,path", [
    ("DELETE", "/subscriptions/test"),
    ("PUT", "/subscriptions/test"),
    ("POST", "/subscriptions/test/providers/Microsoft.Resources/deployments"),
    ("GET", "/subscriptions/test/listKeys"),
])
def test_forbids_write_and_secret_apis(method: str, path: str) -> None:
    session = Mock()
    http = verify.ReaderHTTP(credential(), session)
    with pytest.raises(ValueError):
        http.request(method, verify.ARM + path)
    session.request.assert_not_called()


def test_retry_429_and_server_failure_uses_exponential_backoff() -> None:
    session = Mock()
    session.request.side_effect = [response(429), response(503), response(200)]
    http = verify.ReaderHTTP(credential(), session)
    with patch.object(verify.time, "sleep") as sleep:
        assert http.request("GET", verify.ARM + "/test") == {"value": []}
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2]
    assert session.request.call_count == 3
    assert session.request.call_args.kwargs["allow_redirects"] is False


def test_cost_management_specific_retry_header_is_respected() -> None:
    limited = response(429)
    limited.headers = {"x-ms-ratelimit-microsoft.costmanagement-entity-retry-after": "7"}
    session = Mock()
    session.request.side_effect = [limited, response(200)]
    with patch.object(verify.time, "sleep") as sleep:
        verify.ReaderHTTP(credential(), session).request("GET", verify.ARM + "/test")
    sleep.assert_called_once_with(7)


def test_certificate_registration_propagation_is_retried_without_other_identity() -> None:
    source = Mock()
    token = SimpleNamespace(token="fixture")
    source.get_token.side_effect = [ClientAuthenticationError("AADSTS700027"), token]
    with patch.object(verify.time, "sleep") as sleep:
        assert credential_token(source, verify.ARM_SCOPE) is token
    assert source.get_token.call_count == 2
    sleep.assert_called_once_with(1)


def test_unrelated_authentication_error_is_not_silently_retried() -> None:
    source = Mock()
    source.get_token.side_effect = ClientAuthenticationError("AADSTS700016")
    with pytest.raises(ClientAuthenticationError), patch.object(verify.time, "sleep") as sleep:
        credential_token(source, verify.ARM_SCOPE)
    assert source.get_token.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("code,status,reason", [
    (403, "DENIED", "permission_denied"),
    (404, "FEATURE_UNAVAILABLE", "feature_unavailable"),
    (400, "ERROR", "error"),
])
def test_http_null_reason_is_not_fabricated(code: int, status: str, reason: str) -> None:
    session = Mock()
    session.request.return_value = response(code)
    result = verify.probe(
        verify.ReaderHTTP(credential(), session), SID, "BI-SY-08",
        "sample", "GET", verify.ARM + "/test",
    )
    assert result.status == status
    assert result.reason == reason
    assert "license_missing" not in result.detail


def test_graph_unlicensed_403_is_license_missing_not_permission_denied() -> None:
    session = Mock()
    payload = {"error": {"code": "Forbidden", "message": "Your tenant is not licensed for this feature."}}
    session.request.return_value = response(403, payload)
    result = verify.probe(
        verify.ReaderHTTP(credential(), session), SID, "OE-SY-15", "tenant", "GET",
        "https://graph.microsoft.com/beta/identityProtection/riskyAgents", audience=verify.MSGRAPH_SCOPE,
    )
    assert (result.status, result.reason) == ("FEATURE_UNAVAILABLE", "license_missing")


def test_foundry_feature_header_is_sent_only_when_requested() -> None:
    session = Mock()
    session.request.return_value = response(200)
    http = verify.ReaderHTTP(credential(), session)
    url = "https://x.services.ai.azure.com/api/projects/p/redTeams/runs?api-version=v1"
    http.request("GET", url, verify.AI_SCOPE, extra_headers={"Foundry-Features": "RedTeams=V1Preview"})
    http.request("GET", url, verify.AI_SCOPE)
    first, second = (call.kwargs["headers"] for call in session.request.call_args_list)
    assert first["Foundry-Features"] == "RedTeams=V1Preview"
    assert "Foundry-Features" not in second

def test_network_failure_is_not_feature_unavailable() -> None:
    session = Mock()
    session.request.side_effect = requests.ConnectionError("do not log this body")
    http = verify.ReaderHTTP(credential(), session)
    with patch.object(verify.time, "sleep"):
        result = verify.probe(http, SID, "OT-SY-19", "sample", "GET", verify.ARM + "/test")
    assert result.status == "ERROR"
    assert result.reason == "error"
    assert "do not log" not in result.detail


def test_pagination_refuses_external_host() -> None:
    session = Mock()
    session.request.return_value = response(200, {
        "value": [], "nextLink": "https://evil.invalid/test",
    })
    http = verify.ReaderHTTP(credential(), session)
    with pytest.raises(ValueError):
        http.list_arm(verify.ARM + "/test")
    assert session.request.call_count == 1


def test_pagination_collects_all_pages() -> None:
    session = Mock()
    session.request.side_effect = [
        response(200, {"value": [{"id": "one"}], "nextLink": verify.ARM + "/test?page=2"}),
        response(200, {"value": [{"id": "two"}]}),
    ]
    assert verify.ReaderHTTP(credential(), session).list_arm(verify.ARM + "/test") == [
        {"id": "one"}, {"id": "two"},
    ]


def test_identity_must_match_expected_principal_and_tenant() -> None:
    encoded = base64.urlsafe_b64encode(
        json.dumps({"tid": TENANT, "oid": PRINCIPAL}).encode(),
    ).decode().rstrip("=")
    source = Mock()
    source.get_token.return_value = SimpleNamespace(token=f"header.{encoded}.signature")
    verify.verify_identity(source, TENANT, PRINCIPAL)
    with pytest.raises(verify.AccessError, match="다릅니다"):
        verify.verify_identity(source, TENANT, "cccccccc-cccc-4ccc-8ccc-cccccccccccc")


@pytest.mark.parametrize("actions,expected", [
    (["*/read"], False),
    (["*"], True),
    (["Microsoft.CognitiveServices/*"], True),
    (["Microsoft.CognitiveServices/accounts/AIServices/agents/read"], False),
    (["Microsoft.CognitiveServices/accounts/listkeys/action"], True),
])
def test_broad_permission_guard(actions: list[str], expected: bool) -> None:
    assert verify.rejects_broad_permissions([{"actions": actions}]) is expected


def test_subscription_failure_does_not_prevent_other_two() -> None:
    subscriptions = [
        SID, "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333",
    ]

    def list_arm(url: str) -> list[dict]:
        if f"/subscriptions/{subscriptions[1]}/" in url:
            raise verify.AccessError("permission_denied", "fixture denial")
        if "/permissions?" in url:
            return [{"actions": ["*/read"], "dataActions": []}]
        return []

    with patch.object(verify.ReaderHTTP, "list_arm", side_effect=list_arm), patch.object(
        verify.ReaderHTTP, "request", return_value={"value": []},
    ):
        results = [r for sid in subscriptions for r in verify.check_subscription(credential(), sid, [])]
    assert {r.subscription_id for r in results} == set(subscriptions)
    failed = [r for r in results if r.subscription_id == subscriptions[1]]
    assert len(failed) == len(verify.SE_CODES)
    assert all(r.status == "DENIED" for r in failed)
    assert any(r.status == "OK" for r in results if r.subscription_id == SID)
    assert all(r.status != "DENIED" for r in results if r.subscription_id == subscriptions[2])


def test_no_project_does_not_claim_foundry_access() -> None:
    with patch.object(
        verify.ReaderHTTP, "list_arm",
        side_effect=[[{"actions": ["*/read"]}], []],
    ), patch.object(verify.ReaderHTTP, "request", return_value={"value": []}):
        results = verify.check_subscription(credential(), SID, [])
    evaluation = next(r for r in results if r.se_code == "BI-SY-08")
    assert evaluation.status == "FEATURE_UNAVAILABLE"
    assert evaluation.reason == "not_found"


def test_entra_probes_run_while_the_credential_is_still_open(tmp_path) -> None:
    state = {"open": False}

    class Context:
        def __enter__(self):
            state["open"] = True
            return credential()

        def __exit__(self, *args):
            state["open"] = False

    def probes(*args, **kwargs):
        assert state["open"], "credential closed before Entra probes"
        return []

    with patch("azure.identity.DefaultAzureCredential", Context), patch.object(
        verify, "verify_identity",
    ), patch.object(verify, "check_subscription", return_value=[]), patch.object(
        verify, "check_entra", side_effect=probes,
    ) as entra:
        code = verify.main([
            "--tenant-id", TENANT, "--expected-principal-id", PRINCIPAL, "--subscriptions", SID,
            "--rbac-path", str(tmp_path / "p.md"), "--output", str(tmp_path / "p.json"),
        ])
    assert code == 0 and entra.called


def test_rbac_report_contains_permission_denial_and_additional_role() -> None:
    report = verify.render_rbac([
        verify.Result(SID, "BI-SY-08", "sample", "DENIED", "permission_denied", "fixture"),
    ])
    assert "Cost Management Reader" in report
    assert "DENIED" in report
    assert "permission_denied" in report
    assert "사용자 지정" in report
