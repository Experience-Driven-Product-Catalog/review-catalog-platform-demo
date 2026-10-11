import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from openai import APIError
from pydantic import BaseModel, ConfigDict, Field

from . import agent, catalog

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(min_length=1, max_length=100)
    review: str = Field(min_length=3, max_length=8000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    previous_response_id: str | None = Field(default=None, max_length=200)
    continuation: str | None = Field(default=None, max_length=64000)
    applied_filters: dict[str, Any] = Field(default_factory=dict)
    applied_conditions: list[dict[str, str]] = Field(
        default_factory=list, max_length=100
    )


@app.middleware("http")
async def headers(request: Request, call_next):
    length = int(request.headers.get("content-length", "0"))
    if length > 100000:
        return JSONResponse({"error": "REQUEST_TOO_LARGE"}, status_code=413)
    result = await call_next(request)
    result.headers["Cache-Control"] = "no-store"
    result.headers["X-Content-Type-Options"] = "nosniff"
    return result


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": os.environ.get("SERVICE", "local"),
        "api_ready": agent.ready(),
    }


@app.get("/catalog")
def get_catalog():
    return {
        "products": catalog.products(),
        "metadata": catalog.metadata(),
        "api_ready": agent.ready(),
    }


def next_event(iterator):
    try:
        return next(iterator)
    except StopIteration:
        return None


async def stream(factory, body):
    # Only catalog data is cached globally. Input and response state live in this generator.
    executor = ThreadPoolExecutor(max_workers=1)
    iterator = factory(body)
    loop = asyncio.get_running_loop()
    future = None

    def encode(event):
        return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    try:
        while True:
            future = loop.run_in_executor(executor, next_event, iterator)
            while not future.done():
                done, _ = await asyncio.wait([future], timeout=10)
                if not done:
                    yield ": keepalive\n\n"
            event = await future
            if event is None:
                break
            yield encode(event)
    except agent.PublicError as e:
        yield encode({"type": "error", "code": e.code, "message": e.message})
    except APIError as e:
        code = (
            "OPENAI_AUTH"
            if getattr(e, "status_code", None) in (401, 403)
            else "OPENAI_UNAVAILABLE"
        )
        yield encode(
            {
                "type": "error",
                "code": code,
                "message": "OpenAI API 연결을 완료하지 못했습니다. 키·모델 권한·사용 한도를 확인해 주세요.",
            }
        )
    except Exception as exc:  # noqa: BLE001 - terminate SSE without disclosing request data
        # Never log user input, model outputs, response identifiers or secrets.
        logging.getLogger(__name__).error("Request failed: %s", type(exc).__name__)
        yield encode(
            {
                "type": "error",
                "code": "INTERNAL_ERROR",
                "message": "처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
            }
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def response(factory, body, service):
    if os.environ.get("SERVICE", "local") not in ("local", service):
        return JSONResponse({"error": "NOT_FOUND"}, status_code=404)
    return StreamingResponse(
        stream(factory, body),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )


@app.post("/report")
def report(body: ReportRequest):
    return response(agent.report_events, body, "report")


@app.post("/chat")
def chat(body: ChatRequest):
    return response(agent.chat_events, body, "chat")
