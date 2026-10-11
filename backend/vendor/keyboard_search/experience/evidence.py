"""상품·속성·원래 상태에 대한 원문 근거를 리뷰 단위로 반환한다."""
from schemas import EvidenceRequest, ReviewEvidenceResult
from condition_display import item, attribute_name, state_names, SENTIMENT_LABELS, GROUP_LABELS
from .aggregation import classify_reviews, summary
from .repository import Repository

UNIT_FIELDS = ("idx", "review_idx", "raw_aspect_id", "state_variant_id", "raw_aspect", "raw_status",
               "aspect_cluster_id", "status_cluster_id", "aspect", "status", "excerpt", "opinion", "sentiment",
               "aspect_mapping_applied", "status_mapping_applied", "aspect_mapping_distance", "status_mapping_distance")


def present_review(group: dict, include_full: bool = False) -> dict:
    item = {k: group[k] for k in ("product_id", "review_id", "labels", "sentiment", "matching_sentiment", "matching_unit_ids", "contrary_unit_ids")}
    item["opinion_units"] = [{**{k: u.get(k) for k in UNIT_FIELDS}, "opinion_unit_id": u["idx"]} for u in group["units"]]
    if include_full:
        item["review_text"] = group["units"][0]["review_text"]
    return item


def samples(rows, desired=None, contrary=(), limit=2, sentiments=None) -> dict:
    groups = classify_reviews(rows, desired, contrary, sentiments)
    return {label: [present_review(g) for g in groups if label in g["labels"]][:limit]
            for label in ("matching", "contrary", "other", "unknown_state")}


def get_review_evidence(**kwargs) -> ReviewEvidenceResult:
    request = EvidenceRequest.model_validate(kwargs)
    with Repository() as repo:
        repo.validate_states(request.attribute, request.desired_state_ids, request.contrary_state_ids)
        products = repo.product_ids(request.products)
        rows = repo.rows(request.attribute, products)
        groups = classify_reviews(rows, request.desired_state_ids, request.contrary_state_ids, request.sentiments)
        selected = [g for g in groups if (request.group == "all" or request.group in g["labels"]) and
                    (request.sentiments is None or (g["matching_sentiment"] if request.group == "matching" else g["sentiment"]) in request.sentiments)]
        page = selected[request.offset:request.offset + request.limit]
        product_counts = repo.products()
        total = sum(p["review_count"] for pid,p in product_counts.items() if products is None or pid in products)
        labels = repo.labels(request.attribute,request.desired_state_ids)
        conditions = [item("체감","근거 속성",attribute_name(labels)),item("체감","근거 범위",GROUP_LABELS[request.group])]
        if request.desired_state_ids is not None:
            conditions.append(item("체감","원하는 상태",state_names(labels)))
        if request.contrary_state_ids:
            conditions.append(item("체감","상반 상태",state_names(repo.labels(request.attribute,request.contrary_state_ids))))
        if request.sentiments:
            conditions.append(item("체감","리뷰 평가"," 또는 ".join(SENTIMENT_LABELS[s] for s in request.sentiments)))
        if products is not None:
            conditions.append(item("객관","대상 상품",", ".join(product_counts[pid]["objective_name"] for pid in products)))
        return ReviewEvidenceResult(**repo.versions(), reviews=[present_review(g,request.include_full_review) for g in page],
                                    applied_conditions=conditions,
                                    total_count=len(selected), next_offset=request.offset + request.limit if request.offset + request.limit < len(selected) else None,
                                    applied_filters_markdown="### 적용된 리뷰 검색 조건\n- " + str(repo.labels(request.attribute,request.desired_state_ids)) +
                                    f"\n- 근거 그룹: {request.group} / 원문 보고 검색(제품 특성 보장 아님)",
                                    summary=summary(rows,total,request.desired_state_ids,request.contrary_state_ids,request.sentiments),
                                    applied_request=request.model_dump(mode="json"))
