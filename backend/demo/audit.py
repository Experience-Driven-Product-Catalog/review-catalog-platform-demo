"""Private, append-only request/result records. Never persist continuation tokens."""

import json
import logging
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import boto3
from botocore.config import Config
from openai import APIError

from . import agent, catalog, reports

RETENTION_DAYS = 90
POLICY_VERSION = "security-audit-v1"


def identifier(value=None):
    try:
        return str(UUID(value)) if value else str(uuid4())
    except (ValueError, TypeError, AttributeError):
        return str(uuid4())


def put(key, record):
    bucket = os.environ.get("AUDIT_BUCKET")
    if not bucket:
        raise agent.PublicError(
            "AUDIT_UNAVAILABLE",
            "기록 저장소가 준비되지 않아 요청을 처리할 수 없습니다.",
        )
    try:
        boto3.client(
            "s3",
            config=Config(
                connect_timeout=3, read_timeout=5, retries={"max_attempts": 2}
            ),
        ).put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode(),
            ContentType="application/json; charset=utf-8",
            ServerSideEncryption="AES256",
            IfNoneMatch="*",
        )
    except Exception as exc:  # noqa: BLE001 - SDK errors must not disclose payloads
        logging.getLogger(__name__).error("Audit write failed: %s", type(exc).__name__)
        raise agent.PublicError(
            "AUDIT_UNAVAILABLE",
            "보안 기록을 저장하지 못해 처리를 완료할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from None


def events(kind, body, factory):
    now = datetime.now(UTC)
    request_id = str(uuid4())
    session_id = str(uuid4())
    parent_id = None
    if kind == "chat":
        try:
            state = agent.chat_state(body)
            session_id = identifier(state.get("audit_session_id"))
            parent_id = state.get("audit_request_id")
        except agent.PublicError:
            # Invalid sessions are recorded under a new, untrusted-input-free key.
            pass
    context = {"session_id": session_id, "request_id": request_id}
    prefix = f"audit/v1/{kind}/{now:%Y/%m/%d}/{session_id}/{request_id}"
    common = {
        "schema_version": 1,
        "policy_version": POLICY_VERSION,
        "kind": kind,
        **context,
        "parent_request_id": parent_id,
        "received_at": now.isoformat(),
        "retention_days": RETENTION_DAYS,
        "catalog_version": catalog.metadata()["source_data_version"],
        "model": os.environ.get("ANSWER_MODEL", "gpt-6.1-sol")
        if kind == "chat"
        else os.environ.get("EXTRACTION_MODEL", "gpt-6-luna"),
    }
    submitted = body.model_dump(exclude={"continuation", "previous_response_id"})
    put(prefix + "/request.json", {**common, "event": "request", "input": submitted})
    try:
        iterator = (
            factory(body, audit_context=context) if kind == "chat" else factory(body)
        )
        for event in iterator:
            if event["type"] == "result":
                data = event["data"]
                data["audit"] = {
                    **context,
                    "policy_version": POLICY_VERSION,
                    "retention_days": RETENTION_DAYS,
                }
                if kind == "report":
                    data["policy"]["stored"] = True
                    data["policy"]["catalog_updated"] = False
                    data["markdown"] = reports.render(data)
                saved = {
                    k: v
                    for k, v in data.items()
                    if k not in {"continuation", "previous_response_id"}
                }
                put(
                    prefix + "/result.json",
                    {
                        **common,
                        "event": "result",
                        "completed_at": datetime.now(UTC).isoformat(),
                        "output": saved,
                    },
                )
            yield event
    except Exception as exc:  # Record only safe failure classification, then re-raise.
        code = (
            exc.code
            if isinstance(exc, agent.PublicError)
            else "OPENAI_ERROR"
            if isinstance(exc, APIError)
            else "INTERNAL_ERROR"
        )
        # A failed result write must never be returned as success, even if this write fails too.
        put(
            prefix + "/error.json",
            {
                **common,
                "event": "error",
                "failed_at": datetime.now(UTC).isoformat(),
                "error_code": code,
            },
        )
        raise
