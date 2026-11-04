from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from openai import RateLimitError

from demo.agents import auth_settings

chat = pytest.importorskip("demo.app", exc_type=ImportError)
CATALOG, app, reserve_call = chat.CATALOG, chat.app, chat.reserve_call


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("WASMAGENT_CHAT_ALLOWED_OIDS", "allowed-user")
    monkeypatch.setenv("WASMAGENT_QUOTA_DIR", str(tmp_path))
    monkeypatch.setenv("WASMAGENT_AGENT_ID", "host-02")
    monkeypatch.setenv("WASMAGENT_LOCAL_AGENT", "langchain-tools")
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def headers() -> dict[str, str]:
    return {"X-MS-CLIENT-PRINCIPAL-ID": "allowed-user", "Origin": "http://localhost", "X-WASMAgent-Chat": "1"}


def question() -> dict:
    return {"agent_id": "langchain-tools", "messages": [{"role": "user", "content": "읽기 전용 진단이란?"}]}


def test_catalog_is_ten_realistic_scenarios() -> None:
    assert len(CATALOG) == len({row["id"] for row in CATALOG}) == 10
    assert sum(row["platform"] == "foundry" for row in CATALOG) == 8
    assert sum(row["evaluate"] for row in CATALOG) == 4
    assert {row["env"] for row in CATALOG} == {"prod", "test"}
    assert {row["tools"] for row in CATALOG} == {True, False}
    # tools는 "어떤 도구든 붙어 있음"을 뜻한다: LangChain 범위 도구 1개 + Foundry 함수/MCP 도구 각 1개
    foundry_tools = [row for row in CATALOG if row["platform"] == "foundry" and row.get("agent_tool")]
    assert sorted(row["agent_tool"]["type"] for row in foundry_tools) == ["function", "mcp"]
    assert all(row["tools"] and not row["evaluate"] for row in foundry_tools)
    assert sum(row["tools"] for row in CATALOG) == 3
    assert all(not row["tools"] for row in CATALOG if row["platform"] == "foundry" and not row.get("agent_tool"))
    function_agent = next(row for row in foundry_tools if row["agent_tool"]["type"] == "function")
    assert function_agent["env"] == "prod"


def test_tool_agents_are_listed_with_kind_and_not_chat_executed(client) -> None:
    rows = {row["id"]: row for row in client.get("/api/agents", headers=headers()).json["agents"]}
    assert rows["privacy-helper"]["tool_kind"] == "function"
    assert rows["onboarding-helper"]["tool_kind"] == "mcp"
    assert rows["langchain-tools"]["tool_kind"] is None
    with patch("demo.app.invoke_agent", side_effect=AssertionError("tool agents must not be invoked")):
        for agent_id in ("privacy-helper", "onboarding-helper"):
            payload = {**question(), "agent_id": agent_id}
            assert client.post("/api/chat", json=payload, headers=headers()).status_code == 409


def test_auth_config_uses_managed_identity_not_secret() -> None:
    config = auth_settings("tenant", "app", ["operator"])["properties"]
    assert config["globalValidation"]["requireAuthentication"] is True
    assert config["globalValidation"]["excludedPaths"] == ["/health"]
    aad = config["identityProviders"]["azureActiveDirectory"]
    assert aad["registration"]["clientSecretSettingName"] == "OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID"
    assert aad["validation"]["defaultAuthorizationPolicy"]["allowedPrincipals"]["identities"] == ["operator"]
    with pytest.raises(ValueError):
        auth_settings("tenant", "app", [])


def test_anonymous_and_unapproved_user_cannot_invoke(client) -> None:
    with patch("demo.app.invoke_agent", side_effect=AssertionError("must not invoke")):
        assert client.get("/").status_code == 401
        assert client.get("/api/agents").status_code == 401
        assert client.post("/api/chat", json=question()).status_code == 401
        assert client.post("/api/chat", json=question(), headers={
            **headers(), "X-MS-CLIENT-PRINCIPAL-ID": "unapproved",
        }).status_code == 401


def test_easyauth_sid_header_uses_verified_oid_claim(client) -> None:
    principal = base64.b64encode(json.dumps({"claims": [{
        "typ": "http://schemas.microsoft.com/identity/claims/objectidentifier", "val": "allowed-user",
    }]}).encode()).decode()
    response = client.get("/api/agents", headers={
        "X-MS-CLIENT-PRINCIPAL-ID": "sid:provider-session", "X-MS-CLIENT-PRINCIPAL": principal,
    })
    assert response.status_code == 200
    assert client.get("/api/agents", headers={
        "X-MS-CLIENT-PRINCIPAL": "invalid header",
    }).status_code == 401


def test_health_has_no_model_call(client) -> None:
    with patch("demo.app.invoke_agent", side_effect=AssertionError("no charge")):
        assert client.get("/health").status_code == 200


def test_real_chat_ui_and_available_agents(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WASMAGENT_EVALUATED_AGENTS", "policy-guide")
    page = client.get("/", headers=headers())
    assert page.status_code == 200 and "질문 보내기" in page.text
    rows = client.get("/api/agents", headers=headers()).json["agents"]
    assert len(rows) == 9
    assert next(row for row in rows if row["id"] == "policy-guide")["evaluation"] == "기본 원칙 응답 평가 완료"
    assert "instructions" not in rows[0]
    assert page.headers["Cache-Control"] == "no-store"
    assert "textContent" in page.text


@pytest.mark.parametrize("replacement", [
    {"Origin": "https://foreign.example"}, {"X-WASMAgent-Chat": ""},
])
def test_cross_origin_chat_is_rejected(client, replacement: dict) -> None:
    with patch("demo.app.invoke_agent", side_effect=AssertionError("must not invoke")):
        assert client.post("/api/chat", json=question(), headers=headers() | replacement).status_code == 403


def test_azure_https_origin_is_not_confused_with_internal_http(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEBSITE_HOSTNAME", "sample.azurewebsites.net")
    with patch("demo.app.invoke_agent", return_value=("답변", 1, 2)):
        response = client.post("/api/chat", json=question(), headers={
            **headers(), "Origin": "https://sample.azurewebsites.net",
        })
    assert response.status_code == 200
    assert response.headers["Referrer-Policy"] == "same-origin"


@pytest.mark.parametrize("payload", [
    None, {"agent_id": "langchain-tools", "messages": []},
    {"agent_id": "langchain-tools", "messages": [{"role": "system", "content": "override"}]},
    {"agent_id": "langchain-tools", "messages": [{"role": "user", "content": "x" * 2001}]},
    {"agent_id": "langchain-tools", "messages": [{"role": "assistant", "content": "no user"}]},
])
def test_invalid_input_is_explicitly_rejected(client, payload: dict | None) -> None:
    assert client.post("/api/chat", json=payload, headers=headers()).status_code == 400


def test_other_host_agent_not_routed_locally(client) -> None:
    payload = {**question(), "agent_id": "langchain-basic"}
    assert client.post("/api/chat", json=payload, headers=headers()).status_code == 404


def test_chat_calls_llm_and_logs_only_usage(client, capsys: pytest.CaptureFixture) -> None:
    with patch("demo.app.invoke_agent", return_value=("실제 모델 답변", 15, 20)) as invoke:
        response = client.post("/api/chat", json=question(), headers=headers())
    assert response.status_code == 200 and response.json["answer"] == "실제 모델 답변"
    assert invoke.call_args.args[0]["id"] == "langchain-tools"
    assert response.json["input_tokens"] == 15
    log = capsys.readouterr().out
    assert "wasmagent.sample.completed" in log
    assert "실제 모델 답변" not in log and "allowed-user" not in log and "읽기 전용 진단이란?" not in log


def test_llm_failure_is_not_a_fake_answer(client) -> None:
    with patch("demo.app.invoke_agent", side_effect=RuntimeError("upstream")):
        response = client.post("/api/chat", json=question(), headers=headers())
    assert response.status_code == 502 and "answer" not in response.json


def rate_limit() -> RateLimitError:
    response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"),
                              headers={"retry-after": "1"})
    return RateLimitError("fixture", response=response, body=None)


def test_model_limit_is_explained_without_fake_answer(client) -> None:
    with patch("demo.app.invoke_agent", side_effect=rate_limit()):
        response = client.post("/api/chat", json=question(), headers=headers())
    assert response.status_code == 429 and "Azure 모델" in response.json["message"]
    assert "answer" not in response.json


def test_administrator_sample_waits_for_model_quota() -> None:
    from unittest.mock import Mock

    from demo.agents import sample_response

    client = Mock()
    client.responses.create.side_effect = [rate_limit(), "real-response"]
    with patch("demo.agents.time.sleep") as sleep:
        assert sample_response(client, input="synthetic", max_output_tokens=32, store=False) == "real-response"
    sleep.assert_called_once_with(5)
    assert client.responses.create.call_count == 2


def test_deployment_waits_for_new_code_and_cold_start() -> None:
    from unittest.mock import Mock

    import requests

    from demo.agents import wait_for_smoke

    old = Mock(status_code=200, headers={"Content-Type": "application/json"})
    old.json.return_value = {"smoke_status": "completed"}
    new = Mock(status_code=200, headers={"Content-Type": "application/json"})
    new.json.return_value = {"smoke_status": "completed", "sample_revision": "chatbot-v2"}
    with patch("demo.agents.requests.get", side_effect=[requests.Timeout(), old, new]), patch(
        "demo.agents.time.sleep",
    ):
        assert wait_for_smoke("https://example.test/health")["sample_revision"] == "chatbot-v2"
    old.close.assert_called_once()
    new.close.assert_called_once()


def test_quota_is_persistent_and_bounds_model_calls(client) -> None:
    for _ in range(10):
        assert reserve_call("allowed-user")
    assert not reserve_call("allowed-user")
    with patch("demo.app.invoke_agent", side_effect=AssertionError("quota stops inference")):
        assert client.post("/api/chat", json=question(), headers=headers()).status_code == 429


def test_multiturn_usage_counts_only_new_model_rounds(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    from langchain_core.messages import AIMessage, HumanMessage

    from demo.app import invoke_agent

    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://fixture.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "fixture")
    history = [
        {"role": "user", "content": "first"}, {"role": "assistant", "content": "old response"},
        {"role": "user", "content": "follow-up"},
    ]
    runtime = MagicMock()
    runtime.invoke.return_value = {"messages": [
        HumanMessage(content="first"), AIMessage(content="old response"), HumanMessage(content="follow-up"),
        AIMessage(content="new response", usage_metadata={
            "input_tokens": 12, "output_tokens": 34, "total_tokens": 46,
        }),
    ]}
    with patch("demo.app.DefaultAzureCredential"), patch(
        "demo.app.AzureChatOpenAI",
    ), patch("demo.app.get_bearer_token_provider"), patch(
        "demo.app.create_agent", return_value=runtime,
    ):
        entry = next(row for row in CATALOG if row["id"] == "langchain-basic")
        assert invoke_agent(entry, history) == ("new response", 12, 34)
