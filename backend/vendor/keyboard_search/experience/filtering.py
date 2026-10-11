"""명시적 리뷰 존재와 근거 수를 판정한다. 제품 특성을 보장하지 않는다."""
from schemas import ExperienceCondition
from .aggregation import classify_reviews, summary


def evaluate_condition(rows: list[dict], condition: ExperienceCondition, total_reviews: int) -> dict:
    result = summary(rows, total_reviews, condition.desired_state_ids, condition.contrary_state_ids, condition.sentiments)
    if not rows:
        state, reason = "UNKNOWN", "NO_RELATED_REVIEWS"
    else:
        groups = classify_reviews(rows, condition.desired_state_ids, condition.contrary_state_ids, condition.sentiments)
        has_state = condition.desired_state_ids is None or any(r["state_variant_id"] is not None for r in rows)
        known_sentiment = condition.sentiments is None or "unknown" in condition.sentiments or any(
            g["state_units"] and g["matching_sentiment"] != "unknown" for g in groups)
        if not has_state or not known_sentiment and any(g["state_units"] for g in groups):
            state, reason = "UNKNOWN", "REQUIRED_FIELD_UNKNOWN"
        elif result["matching_review_count"] < condition.min_matching_reviews:
            state, reason = "FAIL", "MATCHING_REVIEW_COUNT_BELOW_MINIMUM"
        elif condition.max_contrary_reviews is not None and result["contrary_review_count"] > condition.max_contrary_reviews:
            state, reason = "FAIL", "CONTRARY_REVIEW_COUNT_ABOVE_MAXIMUM"
        else:
            state, reason = "PASS", "EXPLICIT_REVIEW_EVIDENCE_FOUND"
    return {"condition_id": condition.condition_id, "state": state, "reason_code": reason,
            "min_matching_reviews": condition.min_matching_reviews, "max_contrary_reviews": condition.max_contrary_reviews, **result}
