from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from flask import Flask, Response, jsonify, request
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI
from openai import OpenAIError, RateLimitError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

HERE = Path(__file__).parent
CATALOG = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 40_000
state: dict[str, object] = {
    "status": "ready", "platform": "langchain", "smoke_status": "not_requested",
    "sample_revision": "chatbot-v2",
}
state_lock = threading.Lock()
inference_lock = threading.Lock()


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1, max_length=2000)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    messages: list[Message] = Field(min_length=1, max_length=10)


@tool
def governance_scope() -> str:
    """Return the synthetic sample's permitted governance scope."""
    return "합성 데이터 기반 설명만 허용합니다. Azure 리소스 변경, 비밀 조회, 고객 데이터 조회는 하지 않습니다."


def principal() -> str | None:
    # App Service Easy Auth validates tokens and replaces these headers before Flask.
    oid = request.headers.get("X-MS-CLIENT-PRINCIPAL-ID")
    allowed = set(os.environ.get("WASMAGENT_CHAT_ALLOWED_OIDS", "").split(","))
    if oid and oid in allowed:
        return oid
    encoded = request.headers.get("X-MS-CLIENT-PRINCIPAL")
    if encoded:
        try:
            claims = json.loads(base64.b64decode(encoded, validate=True))["claims"]
            values = {
                claim["val"] for claim in claims if claim["typ"] in (
                    "oid", "http://schemas.microsoft.com/identity/claims/objectidentifier",
                )
            }
            matches = values & allowed
            return next(iter(matches)) if len(matches) == 1 else None
        except (binascii.Error, ValueError, KeyError, TypeError):
            app.logger.warning("Invalid platform principal header")
    return None


def reserve_call(oid: str) -> bool:
    directory = Path(os.environ.get("WASMAGENT_QUOTA_DIR", "/home/wasmagent-quota"))
    directory.mkdir(parents=True, exist_ok=True)
    now = time.time()
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    user_hash = hashlib.sha256(oid.encode()).hexdigest()
    with sqlite3.connect(directory / "calls.sqlite", timeout=10) as database:
        database.execute("CREATE TABLE IF NOT EXISTS calls (at REAL, day TEXT, identity TEXT)")
        database.execute("BEGIN IMMEDIATE")
        database.execute("DELETE FROM calls WHERE day < ?", (day,))
        daily = database.execute("SELECT COUNT(*) FROM calls WHERE day = ?", (day,)).fetchone()[0]
        minute = database.execute(
            "SELECT COUNT(*) FROM calls WHERE identity = ? AND at > ?", (user_hash, now - 60),
        ).fetchone()[0]
        if daily >= 100 or minute >= 10:
            return False
        database.execute("INSERT INTO calls VALUES (?, ?, ?)", (now, day, user_hash))
    return True


def invoke_agent(entry: dict, messages: list[dict[str, str]]) -> tuple[str, int | None, int | None]:
    with DefaultAzureCredential() as credential:
        if entry["platform"] == "foundry":
            with AIProjectClient(
                endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"], credential=credential, allow_preview=True,
            ) as project, project.get_openai_client(agent_name=entry["id"]).with_options(
                timeout=60, max_retries=1,
            ) as client:
                response = client.responses.create(input=messages, max_output_tokens=256, store=False)
                if response.status != "completed" or not response.output_text:
                    raise RuntimeError("모델이 답변을 완료하지 못했습니다.")
                usage = response.usage
                return response.output_text, usage.input_tokens if usage else None, usage.output_tokens if usage else None
        model = AzureChatOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            api_version="2024-10-21",
            azure_ad_token_provider=get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default",
            ), max_tokens=256, max_retries=1, timeout=60,
        )
        agent = create_agent(
            model=model, tools=[governance_scope] if entry["tools"] else [],
            system_prompt=entry["instructions"],
        )
        response = agent.invoke({"messages": messages}, config={"recursion_limit": 6})
        outputs = [message for message in response["messages"][len(messages):] if message.type == "ai"]
        if not outputs or not isinstance(outputs[-1].content, str) or not outputs[-1].content:
            raise RuntimeError("Agent가 텍스트 답변을 완료하지 못했습니다.")
        usage = [message.usage_metadata for message in outputs]
        complete = all(
            entry and entry.get("input_tokens") is not None and entry.get("output_tokens") is not None
            for entry in usage
        )
        return (
            outputs[-1].content,
            sum(entry["input_tokens"] for entry in usage) if complete else None,
            sum(entry["output_tokens"] for entry in usage) if complete else None,
        )


def record_usage(agent_id: str, inputs: int | None, outputs: int | None) -> None:
    print(json.dumps({
        "event": "wasmagent.sample.completed", "agent_id": agent_id,
        "input_tokens": inputs, "output_tokens": outputs,
    }), flush=True)


@app.get("/")
def index() -> object:
    if not principal():
        return jsonify({"message": "허용된 Entra 계정으로 로그인해야 합니다."}), 401
    return (HERE / "chat.html").read_text(encoding="utf-8")


@app.get("/api/agents")
def agents() -> object:
    if not principal():
        return jsonify({"message": "로그인이 필요합니다."}), 401
    evaluated = set(os.environ.get("WASMAGENT_EVALUATED_AGENTS", "").split(","))
    own = os.environ.get("WASMAGENT_LOCAL_AGENT", "langchain-tools")
    rows = []
    for entry in CATALOG:
        if entry["platform"] == "langchain" and entry["id"] != own:
            continue
        rows.append({
            key: entry[key] for key in ("id", "name", "platform", "env", "tools")
        } | {
            "tool_kind": (entry.get("agent_tool") or {}).get("type"),
            "evaluation": "기본 원칙 응답 평가 완료" if entry["id"] in evaluated else "평가 미수행",
        })
    return jsonify({"agents": rows})


@app.post("/api/chat")
def chat() -> object:
    oid = principal()
    if not oid:
        return jsonify({"message": "허용된 Entra 계정으로 로그인해야 합니다."}), 401
    origin = request.headers.get("Origin")
    hostname = os.environ.get("WEBSITE_HOSTNAME")
    expected_origin = "https://" + hostname if hostname else request.host_url.rstrip("/")
    if origin != expected_origin or request.headers.get("X-WASMAgent-Chat") != "1":
        return jsonify({"message": "같은 사이트의 챗봇 화면에서만 요청할 수 있습니다."}), 403
    try:
        data = ChatInput.model_validate(request.get_json(silent=True))
    except ValidationError:
        return jsonify({"message": "질문은 2,000자, 대화는 10개 메시지 이내의 텍스트로 입력하세요."}), 400
    if data.messages[-1].role != "user" or sum(len(item.content) for item in data.messages) > 8000:
        return jsonify({"message": "마지막 메시지는 질문이어야 하며 전체 대화는 8,000자 이내여야 합니다."}), 400
    own = os.environ.get("WASMAGENT_LOCAL_AGENT", "langchain-tools")
    entry = next((entry for entry in CATALOG if entry["id"] == data.agent_id), None)
    if not entry or (entry["platform"] == "langchain" and entry["id"] != own):
        return jsonify({"message": "이 호스트에서 실행할 수 없는 Agent입니다."}), 404
    if entry.get("agent_tool"):
        return jsonify({"message": "이 Agent의 도구는 구성 수집용 정의만 등록되어 있어 대화에서는 실행하지 않습니다."}), 409
    if not inference_lock.acquire(blocking=False):
        return jsonify({"message": "다른 답변을 생성 중입니다. 잠시 후 다시 시도하세요."}), 429
    try:
        if not reserve_call(oid):
            return jsonify({"message": "샘플 한도: 계정당 분당 10회, 호스트당 하루 100회입니다."}), 429
        answer, inputs, outputs = invoke_agent(entry, [item.model_dump() for item in data.messages])
        agent_id = os.environ["WASMAGENT_AGENT_ID"] if entry["platform"] == "langchain" else entry["id"]
        record_usage(agent_id, inputs, outputs)
        return jsonify({"answer": answer[:4000], "input_tokens": inputs, "output_tokens": outputs})
    except RateLimitError:
        app.logger.warning("Chat inference model rate limit reached")
        return jsonify({"message": "Azure 모델의 현재 요청 한도에 도달했습니다. 1분 뒤 다시 질문하세요."}), 429
    except (AzureError, OpenAIError, RuntimeError) as exc:
        app.logger.error("Chat inference failed: %s", type(exc).__name__)
        return jsonify({"message": "모델 호출에 실패했습니다. 관리자에게 모델 접근 권한과 서비스 상태 확인을 요청하세요."}), 502
    except (sqlite3.Error, OSError):
        app.logger.error("Chat quota storage failed")
        return jsonify({"message": "사용량 제한 저장소를 확인할 수 없어 호출을 중지했습니다."}), 503
    finally:
        inference_lock.release()


@app.after_request
def security_headers(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


def smoke() -> None:
    try:
        with state_lock:
            state["smoke_status"] = "running"
        own = os.environ.get("WASMAGENT_LOCAL_AGENT", "langchain-tools")
        entry = next(entry for entry in CATALOG if entry["id"] == own)
        for attempt in range(6):
            try:
                answer, inputs, outputs = invoke_agent(
                    entry, [{"role": "user", "content": "합성 테스트입니다. 읽기 전용 진단 원칙을 한 문장으로 설명하세요."}],
                )
                break
            except RateLimitError:
                if attempt == 5:
                    raise
                app.logger.warning("Startup model rate limited, retrying in 60 seconds")
                time.sleep(60)
        if not answer:
            raise RuntimeError("빈 답변")
        record_usage(os.environ["WASMAGENT_AGENT_ID"], inputs, outputs)
        with state_lock:
            state["smoke_status"] = "completed"
    except (AzureError, OpenAIError, ValueError, KeyError, OSError, RuntimeError) as exc:
        with state_lock:
            state["smoke_status"] = "failed"
            state["error_type"] = type(exc).__name__
        print(json.dumps({"event": "wasmagent.sample.failed", "error_type": type(exc).__name__}), flush=True)


@app.get("/health")
def health() -> tuple[object, int]:
    with state_lock:
        snapshot = dict(state)
    return jsonify(snapshot), 503 if snapshot["smoke_status"] == "failed" else 200


if os.environ.get("WASMAGENT_SMOKE_ON_START") == "true":
    threading.Thread(target=smoke, daemon=True).start()
