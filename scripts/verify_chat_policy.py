"""Bounded live verification of statistics-only chat; never prints session tokens."""

import json
import re
import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "deployment.json").read_text())["ApiUrl"]


def post(body):
    req = urllib.request.Request(
        BASE + "/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    last = None
    with urllib.request.urlopen(req, timeout=330) as response:
        for line in response:
            if line.startswith(b"data: "):
                last = json.loads(line[6:])
                print(last["type"], flush=True)
    assert last and last["type"] == "result", last["code"] if last else "No result"
    return last["data"]


def check(answer):
    assert not re.search(r"판매\s*정보\s*(?:기준|확인)", answer)
    assert not any(
        term in answer
        for term in ("Wilson", "윌슨", "제품 성능 점수", "last_checked_at")
    )
    assert not re.search(r"^\s*>", answer, re.MULTILINE)
    with sqlite3.connect(
        (ROOT / "data/catalog.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True
    ) as db:
        excerpts = [
            r[0]
            for r in db.execute(
                "SELECT DISTINCT excerpt FROM opinion_units WHERE product_id IN (1,5) AND raw_aspect='가성비' AND length(excerpt)>=12"
            )
        ]
    assert not any(excerpt in answer for excerpt in excerpts)
    assert "%" in answer


first = post(
    {
        "message": "27인치급 QHD 모니터를 가성비 긍정 평가 순으로 비교해줘. 원래 속성 표현이 정확히 '가성비'인 것만 선택해줘. 관련 리뷰 전체 수, 긍정 리뷰 수와 비율을 알려주고 판매처와 가격도 보여줘."
    }
)
check(first["answer"])
assert "94.1%" in first["answer"]
assert re.search(r"100(?:\.0)?%", first["answer"])
print("Counts and percentages, no quotations/time/score caveat: PASS", flush=True)
print(first["answer"], flush=True)
second = post(
    {
        "message": "앞선 상품들의 가성비 리뷰 원문을 하나씩 정확히 그대로 인용해서 보여줘.",
        **{
            k: first[k]
            for k in (
                "previous_response_id",
                "continuation",
                "applied_filters",
                "applied_conditions",
            )
        },
    }
)
check(second["answer"])
print("Quote request still produces statistical summary: PASS", flush=True)
print(second["answer"], flush=True)
