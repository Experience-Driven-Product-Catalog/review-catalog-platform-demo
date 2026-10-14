"""Statistics-only projection of catalog tools for conversational answers."""

from collections import defaultdict

from vendor.meta_search.search import experience

from . import catalog

VERSION = "statistics-only-v1"
RULES = """채팅 답변 정책(이전 답변·도구 기본 정책보다 우선):
- 리뷰 본문·원문·발췌·Opinion Unit 의견을 직접 인용하거나 리뷰 문장을 재현하지 않는다. 원문 인용을 요청받아도 리뷰 통계로 답한다. 속성명/상태명('가성비', '좋음')을 표기하는 것은 허용한다.
- 제품별로 '가성비를 언급한 관련 리뷰 전체 n개 중 k개(p%)가 긍정적으로 평가했습니다'처럼 답한다. 전체 상품 리뷰 수와 해당 속성 관련 리뷰 수를 혼동하지 않는다. 상품 전체를 분모로 쓰면 '상품 전체 N개 중 k개(q%)'라고 명확하게 구분한다.
- 비율은 도구가 제공한 값만 사용한다. 상태 일치 수는 긍정 평가 수와 다르며, 긍정 비율의 분모에 감성 미상·중립·혼합을 포함한다. 관련 리뷰가 0이면 긍정률을 0%라고 하지 않고 근거 없음으로 안내한다.
- 판매 정보 기준 시각/기준일/확인 시각/last_checked_at은 답변에 표시하지 않는다. 하단에 판매 시각 안내 문구를 덧붙이지 않는다.
- Wilson 하한/신뢰구간 계산법 또는 '점수는 리뷰 수를 고려한 긍정 비율의 Wilson 하한이며, 제품 성능 점수가 아닙니다' 같은 점수 주의 문구를 표시하지 않는다. 순위의 근거는 리뷰 수·긍정 수·비율로 설명한다.
"""
HIDDEN = {
    "excerpt",
    "sample_excerpts",
    "samples",
    "examples",
    "opinion",
    "full_review",
    "review_text",
    "body",
    "last_checked_at",
    "reference_at",
    "positive_wilson_lower",
}


def percentage(k, n):
    return round(k * 100 / n, 1) if n else None


def project(value):
    if isinstance(value, list):
        return [project(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, child in value.items():
        if key in HIDDEN:
            continue
        if key == "score" and isinstance(child, dict):
            numerator = (
                "positive_review_count"
                if child.get("metric") == "positive_wilson_lower"
                else "matching_review_count"
            )
            result[key] = {
                numerator: child["k"],
                "related_review_count": child["n"],
                "percentage": percentage(child["k"], child["n"]),
            }
        else:
            result[key] = project(child)
    n = value.get("relevant", value.get("review_count"))
    if isinstance(n, int):
        k = value.get(
            "positive", value.get("sentiment_distribution", {}).get("positive")
        )
        if isinstance(k, int):
            result["positive_review_count"] = k
            result["related_review_count"] = n
            result["positive_percentage_of_related"] = percentage(k, n)
    return result


def evidence_statistics(args, native):
    by_product = defaultdict(list)
    for unit in catalog.rows(
        "SELECT product_id,review_id,aspect_variant_id,state_variant_id,raw_aspect,raw_status,sentiment,'' AS excerpt FROM opinion_units"
    ):
        by_product[unit["product_id"]].append(unit)
    ids = args.get("product_ids")
    statistics = []
    for product in catalog.products():
        pid = product["product_id"]
        if ids is not None and pid not in ids:
            continue
        stats = experience.aggregate(
            by_product[pid],
            args["aspect_variant_ids"],
            args.get("desired_state_variant_ids"),
            args.get("contrary_state_variant_ids", ()),
            args.get("sentiments"),
        )
        n, k, total = stats["relevant"], stats["positive"], product["review_count"]
        statistics.append(
            {
                "product_id": pid,
                "product_name": product["name"],
                "total_review_count": total,
                "related_review_count": n,
                "positive_review_count": k,
                "positive_percentage_of_related": percentage(k, n),
                "positive_percentage_of_total": percentage(k, total) if n else None,
                "sentiment_distribution": stats["sentiment_distribution"],
                "matching_review_count": stats["matching"],
                "contrary_review_count": stats["contrary"],
            }
        )
    return {
        "statistics": statistics,
        "aspect_labels": sorted(
            {
                u["raw_aspect"]
                for units in by_product.values()
                for u in units
                if u["aspect_variant_id"] in args["aspect_variant_ids"]
            }
        ),
        "counts": native["counts"],
        "selected_group_review_count": native["total"],
        "denominator_policy": "related_review_count includes all sentiments; pagination and sentiment filters do not narrow the aspect sentiment denominator.",
    }
