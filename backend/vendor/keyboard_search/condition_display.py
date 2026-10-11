"""화면에서 색상별 조건 칩으로 표시할 간단한 JSON을 만든다."""
from __future__ import annotations

SALE_KEYS = {"min_price_krw", "max_price_krw", "availability"}
SALE_SORTS = {"price", "price_per_megapixel"}
SENTIMENT_LABELS = {"positive":"긍정", "negative":"부정", "mixed":"혼합", "neutral":"중립", "unknown":"판단 불가"}
GROUP_LABELS = {"all":"전체 근거", "matching":"일치 근거", "contrary":"상반 근거", "other":"기타 상태 근거", "unknown_state":"상태 미기재 근거"}
FIELD_LABELS = {"size_classes":"화면 크기", "min_size_class":"화면 크기", "max_size_class":"화면 크기",
                "min_price_krw":"가격", "max_price_krw":"가격", "availability":"판매 상태",
                "name_contains":"이름·모델", "require_dsub":"D-Sub 단자", "require_headphone_out":"헤드폰 출력"}


def item(kind: str, condition: str, value: str) -> dict:
    return {"type":kind,"condition":condition,"value":value}


def objective_conditions(constraints) -> list[dict]:
    result = []
    for c in constraints:
        kind = "판매" if c.key in SALE_KEYS else "객관"
        name = FIELD_LABELS.get(c.key,c.field_label)
        if c.key.startswith("feature:"):
            value = "지원"
        elif c.key in {"require_dsub","require_headphone_out"}:
            value = "있음"
        else:
            prefix = c.field_label + ": "
            value = c.label[len(prefix):] if c.label.startswith(prefix) else c.label.partition(": ")[2] or c.label
            if c.kind == "set":
                value = value.replace(" / "," 또는 ")
        result.append(item(kind,name,value))
    return result


def objective_sort(sort_key: str, sort_label: str, secondary: bool = False) -> dict:
    return item("판매" if sort_key in SALE_SORTS else "객관","동점 정렬" if secondary else "정렬",sort_label)


def attribute_name(labels: dict) -> str:
    names = []
    for a in labels["attributes"]:
        expressions = a["raw_aspects"] if a["raw_aspects"] is not None else [a["aspect"]]
        for name in expressions:
            if name not in names:
                names.append(name)
    return " 또는 ".join(names)


def state_names(labels: dict) -> str | None:
    if labels["states"] is None:
        return None
    return " 또는 ".join(dict.fromkeys(s["raw_status"] for s in labels["states"]))


def review_condition(labels: dict, minimum: int = 1, sentiments=None) -> dict:
    parts = []
    states = state_names(labels)
    if states is not None:
        parts.append(states + " 보고")
    if sentiments:
        parts.append(" 또는 ".join(SENTIMENT_LABELS[s] for s in sentiments) + " 평가")
    value = "·".join(parts) + f" 리뷰 {minimum}개 이상" if parts else f"관련 리뷰 {minimum}개 이상"
    return item("체감",attribute_name(labels),value)


def contrary_limit(labels: dict, limit: int) -> dict:
    return item("체감",attribute_name(labels) + " 상반 보고",f"{state_names(labels)} 리뷰 {limit}개 이하")


def experience_sort(labels: dict, metric: str, order: str) -> dict:
    direction = "높은 순" if order == "desc" else "낮은 순"
    if metric == "positive_wilson_lower":
        value = f"{attribute_name(labels)} 긍정 평가 근거 {direction}"
    else:
        value = f"{attribute_name(labels)}의 {state_names(labels)} 보고 근거 {direction}"
    return item("체감","정렬",value)


def evidence_topic(labels: dict) -> dict:
    states = state_names(labels)
    return item("체감",attribute_name(labels) + " 참고",f"{states} 보고 등 관련 리뷰 확인" if states else "관련 리뷰 확인")
