"""Meta-search's read-only functions adapted to the fixed demo snapshot."""

import json
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator
from vendor.meta_search.policy import INSTRUCTIONS
from vendor.meta_search.search.service import SearchService

from . import catalog

TOOLS = json.loads(Path(__file__).with_name("tool_schemas.json").read_text())
COMPARISON_POLICY = "raw-expression-v1"
DEMO_POLICY = """데모 우선 정책:
- 27인치/32인치 같은 크기 등급은 size_class, 실제 표기된 대각선 크기를 정확히 요구하면 screen_size를 사용한다.
- 고정 모니터 9개만 검색한다. 상품 등록·재수집·재군집화 기능은 없다.
- aspect_variant_ids와 state_variant_id는 원래 표현 기준이다. 군집 대표명은 참고용이며 같은 군집이라는 이유로 다른 표현을 자동 합치지 않는다.
- 속성 탐색의 variants와 matched_selector에서 원래 표현을 선택한다. 여러 표현 OR 결합은 선택한 표현을 사용자에게 명시한다.
- 판매처·가격·배송·재고·링크는 모두 데모 가상 데이터다. 실제 판매/가격 조사 결과로 표현하지 않는다. 채팅 시작 안내에서 출처와 과거/더미 정보임을 설명하므로 이후 답변에서는 '가상', '(데모)', '더미 판매처' 같은 접두어를 반복하지 않고 일반적인 판매처·가격·배송 표현을 쓴다. 사용자가 진위를 물으면 실제 조회 결과가 아님을 설명한다.
- .invalid URL은 실제 구매 링크가 아니다. last_checked_at은 가상 데이터 기준일이며 실제 확인일이 아니다.
- 기존 상세 문서의 과거 가격과 offers의 가상 판매가는 구분한다. 판매 필터·정렬은 offers를 사용한다.
- 적용 조건은 웹 UI가 별도로 표시하므로 답변에 applied_filters_markdown이나 JSON을 반복 출력하지 않는다.
"""
POLICY_MD = (
    "\n".join(
        line for line in INSTRUCTIONS.splitlines() if "register_product" not in line
    )
    + "\n\n"
    + DEMO_POLICY
)
SCHEMAS = {t["name"]: t["parameters"] for t in TOOLS}
for t in TOOLS:
    if t["name"] == "find_review_attributes":
        t["description"] = (
            "체감 속성을 탐색하고 variants에서 원래 표현 aspect_variant_id를 선택한다. 군집 전체 자동 선택 금지."
        )
    if t["name"] == "search_products":
        t["description"] = (
            "전체 객관·체감·판매 조건을 받아 검색한다. 적용 조건은 UI가 별도 표시한다."
        )
    if t["name"] == "get_offers":
        t["description"] = (
            "선택한 모니터들의 판매처·가격·배송·재고·링크를 조회한다. 시작 안내에서 데이터의 한계를 설명한다."
        )


def conditions(args, markdown):
    """Display only active objective/experience/sales operations, without request/result rows."""
    items = []
    sale = args.get("offer_filter") or {}
    sale_active = any(
        sale.get(key) is not None and sale.get(key) != []
        for key in (
            "max_price",
            "min_price",
            "availability",
            "max_shipping_fee",
            "max_shipping_days",
            "retailers",
        )
    )
    for line in markdown.splitlines():
        if not line.startswith("- ") or ": " not in line:
            continue
        label, value = line[2:].split(": ", 1)
        active = (
            (label == "객관" and bool(args.get("filters")))
            or (label == "판매" and sale_active)
            or (label == "체감" and bool(args.get("experience_conditions")))
        )
        if active:
            items.append(
                {"type": label, "condition": label, "value": value, "method": "filter"}
            )
        elif label == "정렬" and args.get("sort"):
            kind = {"price": "판매", "attribute": "객관", "experience": "체감"}[
                args["sort"].get("by", "price")
            ]
            items.append(
                {"type": kind, "condition": kind, "value": value, "method": "sort"}
            )
    if args.get("evidence_topics"):
        from vendor.meta_search.search.render import labels

        units = catalog.rows(
            "SELECT raw_aspect,raw_status,aspect_variant_id,state_variant_id FROM opinion_units"
        )
        for topic in args["evidence_topics"]:
            aspect = labels(topic["aspect_variant_ids"], units, "aspect_variant_id")
            state = labels(
                topic.get("desired_state_variant_ids"), units, "state_variant_id"
            )
            items.append(
                {
                    "type": "체감",
                    "condition": "체감",
                    "value": aspect + (" / " + state if state else "") + " 리뷰 근거",
                    "method": "search",
                }
            )
    return items


def invoke(name, args):
    if name not in SCHEMAS:
        raise ValueError("Unsupported read-only tool")
    schema = SCHEMAS[name]
    if set(args) - set(schema.get("properties", {})):
        raise ValueError("Unknown tool arguments")
    Draft202012Validator(schema).validate(args)
    service = SearchService(SimpleNamespace(db_path=catalog.path()))
    if name == "get_search_guide" and not args.get("category"):
        args = {**args, "category": catalog.metadata()["category"]}
    result = getattr(service, name)(**args)
    if name == "get_search_guide":
        result["answer_policy"] = [
            line for line in result["answer_policy"] if "register_product" not in line
        ]
        result["demo_policy"] = DEMO_POLICY
    if name == "find_review_attributes":
        for group in result["clusters"]:
            group.pop("cluster_selector", None)
            group["cluster_counts_reference_only"] = True
    if name == "list_review_states":
        for group in result["state_clusters"]:
            group["cluster_counts_reference_only"] = True
    if name == "search_products":
        # Keep native results; compatibility fields are consumed by the existing chat UI.
        result["products"] = result["results"]
        result["matched_count"] = (
            result["candidate_count"]
            - len(result["undetermined"])
            - len(result["excluded"])
        )
        result["applied_conditions"] = conditions(
            args, result["applied_filters_markdown"]
        )
    result["sales_data_policy"] = catalog.metadata()["sales"]
    return result


__all__ = ["COMPARISON_POLICY", "POLICY_MD", "TOOLS", "invoke"]
