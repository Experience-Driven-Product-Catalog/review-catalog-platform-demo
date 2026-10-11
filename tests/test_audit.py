import copy
import json
import time
from types import SimpleNamespace

import pytest
from demo import agent, audit, catalog, reports, tools
from demo.app import ChatRequest, ReportRequest, app
from fastapi.testclient import TestClient


@pytest.fixture
def records(monkeypatch):
    saved = []
    monkeypatch.setattr(
        audit, "put", lambda key, record: saved.append((key, copy.deepcopy(record)))
    )
    return saved


def chat_factory(body, audit_context):
    agent.chat_state(body)
    payload = {
        "response_id": "resp_test",
        "filters": {},
        "conditions": [],
        "expires": time.time() + 3600,
        "version": catalog.metadata()["source_data_version"],
        "comparison_policy": tools.COMPARISON_POLICY,
        "audit_session_id": audit_context["session_id"],
        "audit_request_id": audit_context["request_id"],
    }
    yield {
        "type": "result",
        "data": {
            "answer": "테스트 답변",
            "continuation": agent.sign(payload),
            "previous_response_id": payload["response_id"],
            "applied_filters": {},
            "applied_conditions": [],
        },
    }


def result(body):
    return list(audit.events("chat", body, chat_factory))[-1]["data"]


def test_records_preserve_turn_chain_but_not_tokens(records):
    first = result(ChatRequest(message="첫 질문"))
    second = result(
        ChatRequest(
            message="후속 질문",
            **{
                k: first[k]
                for k in (
                    "continuation",
                    "previous_response_id",
                    "applied_filters",
                    "applied_conditions",
                )
            },
        )
    )
    fresh = result(ChatRequest(message="새 대화"))
    assert first["audit"]["session_id"] == second["audit"]["session_id"]
    assert fresh["audit"]["session_id"] != first["audit"]["session_id"]
    assert records[2][1]["parent_request_id"] == first["audit"]["request_id"]
    assert len({key for key, _ in records}) == 6
    assert records[0][1]["input"]["message"] == "첫 질문"
    assert records[1][1]["output"]["answer"] == "테스트 답변"
    serialized = json.dumps(records)
    assert first["continuation"] not in serialized
    assert "previous_response_id" not in serialized
    assert "continuation" not in serialized


def test_real_agent_signed_state_contains_audit_context(monkeypatch, records):
    response = SimpleNamespace(
        id="resp_test", status="completed", output=[], output_text="답변"
    )
    monkeypatch.setattr(
        agent,
        "client",
        lambda: SimpleNamespace(
            responses=SimpleNamespace(create=lambda **kw: response)
        ),
    )
    data = list(audit.events("chat", ChatRequest(message="질문"), agent.chat_events))[
        -1
    ]["data"]
    state = agent.verify(data["continuation"])
    assert state["audit_session_id"] == data["audit"]["session_id"]
    assert state["audit_request_id"] == data["audit"]["request_id"]


def test_report_is_saved_before_return_and_catalog_unchanged(records):
    before = catalog.path().read_bytes()
    body = ReportRequest(product_id="aoc-q27g2s", review="리뷰 테스트")

    def factory(body):
        assert records[0][1]["event"] == "request"
        yield {
            "type": "result",
            "data": reports.generate(body.product_id, body.review, []),
        }

    data = list(audit.events("report", body, factory))[-1]["data"]
    assert records[1][1]["output"]["markdown"] == data["markdown"]
    assert data["policy"]["stored"] is True
    assert data["policy"]["catalog_updated"] is False
    assert before == catalog.path().read_bytes()


def test_initial_write_failure_does_not_call_model(monkeypatch):
    called = []

    def fail(*args):
        raise agent.PublicError("AUDIT_UNAVAILABLE", "저장 실패")

    monkeypatch.setattr(audit, "put", fail)
    with pytest.raises(agent.PublicError, match="저장 실패"):
        list(
            audit.events(
                "chat", ChatRequest(message="질문"), lambda *a, **k: called.append(1)
            )
        )
    assert not called


def test_result_write_failure_never_returns_answer(monkeypatch):
    saved = []

    def put(key, record):
        if record["event"] == "result":
            raise agent.PublicError("AUDIT_UNAVAILABLE", "저장 실패")
        saved.append(record)

    monkeypatch.setattr(audit, "put", put)
    monkeypatch.setattr(agent, "chat_events", chat_factory)
    response = TestClient(app).post("/chat", json={"message": "질문"})
    assert "AUDIT_UNAVAILABLE" in response.text
    assert "테스트 답변" not in response.text
    assert [r["event"] for r in saved] == ["request", "error"]


def test_model_failure_does_not_store_exception_details(records):
    def fail(body, **kw):
        raise RuntimeError("secret-provider-error")

    with pytest.raises(RuntimeError):
        list(audit.events("chat", ChatRequest(message="질문"), fail))
    assert records[-1][1]["error_code"] == "INTERNAL_ERROR"
    assert "secret-provider-error" not in json.dumps(records)


def test_s3_create_only_encrypted_write(monkeypatch):
    calls = []
    monkeypatch.setenv("AUDIT_BUCKET", "test-private-audit")
    monkeypatch.setattr(
        audit.boto3,
        "client",
        lambda *a, **k: SimpleNamespace(put_object=lambda **kw: calls.append(kw)),
    )
    audit.put("audit/v1/chat/test/request.json", {"input": "질문"})
    assert calls[0]["IfNoneMatch"] == "*"
    assert calls[0]["ServerSideEncryption"] == "AES256"
    assert "ACL" not in calls[0]
    assert json.loads(calls[0]["Body"])["input"] == "질문"
