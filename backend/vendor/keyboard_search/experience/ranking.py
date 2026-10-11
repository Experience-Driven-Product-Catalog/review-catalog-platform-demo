"""속성 전체를 분모로 사용하는 단일 체감 점수."""
from schemas import ExperienceSort
from .aggregation import sentiment_distribution, review_groups, wilson_interval


def score(rows: list[dict], order: ExperienceSort) -> dict:
    sentiments = sentiment_distribution(rows)
    n = sentiments["review_count"]
    if order.metric == "positive_wilson_lower":
        k = sentiments["counts"]["positive"]
    else:
        desired = set(order.desired_state_ids)
        k = sum(any(u["state_variant_id"] in desired for u in group) for group in review_groups(rows))
    lo, hi = wilson_interval(k, n)
    return {"metric": order.metric, "order": order.order, "score": lo, "numerator": k, "denominator": n,
            "wilson_95": {"lower": lo, "upper": hi}, "sentiment": sentiments,
            "ranking_status": "evaluated" if n else "no_evidence", "rank": None,
            "claim_scope": "review_report"}
