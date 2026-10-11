"""리뷰당 한 표 집계와 원래 상태별 근거 분류."""
from __future__ import annotations

from collections import defaultdict
import math

SENTIMENTS = ("positive", "negative", "mixed", "neutral", "unknown")


def collapse_sentiments(values) -> str:
    known = set(values) - {"unknown"}
    return "unknown" if not known else next(iter(known)) if len(known) == 1 else "mixed"


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    """기존 보고서의 95% Wilson 식. 표본 0은 미평가로 반환한다."""
    if not total:
        return None, None
    p = successes / total
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0., (centre - margin) / denominator), min(1., (centre + margin) / denominator)


def review_groups(rows: list[dict]) -> list[list[dict]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["product_id"], row["review_id"])].append(row)
    return [grouped[key] for key in sorted(grouped)]


def sentiment_distribution(rows: list[dict]) -> dict:
    votes = [collapse_sentiments(r["sentiment"] for r in group) for group in review_groups(rows)]
    n = len(votes)
    counts = {s: votes.count(s) for s in SENTIMENTS}
    lo, hi = wilson_interval(counts["positive"], n)
    return {"counts": counts, "review_count": n,
            "shares": {s: counts[s] / n if n else None for s in SENTIMENTS},
            "positive_wilson_95": {"lower": lo, "upper": hi}}


def classify_reviews(rows: list[dict], desired=None, contrary=(), sentiments=None) -> list[dict]:
    desired_set = None if desired is None else set(desired)
    contrary_set = set(contrary)
    out = []
    for units in review_groups(rows):
        state_units = [u for u in units if desired_set is None or u["state_variant_id"] in desired_set]
        vote = collapse_sentiments(u["sentiment"] for u in state_units)
        matching = state_units if sentiments is None or vote in sentiments else []
        opposing = [u for u in units if u["state_variant_id"] in contrary_set]
        unknown = [u for u in units if u["state_variant_id"] is None]
        other = [u for u in units if u["state_variant_id"] is not None and u not in state_units and u not in opposing]
        labels = []
        for name, group in (("matching", matching), ("contrary", opposing), ("other", other), ("unknown_state", unknown)):
            if group:
                labels.append(name)
        out.append({"product_id": units[0]["product_id"], "review_id": units[0]["review_id"],
                    "units": units, "labels": labels, "sentiment": collapse_sentiments(u["sentiment"] for u in units),
                    "matching_sentiment": vote, "state_units": state_units,
                    "matching_unit_ids": [u["idx"] for u in matching],
                    "contrary_unit_ids": [u["idx"] for u in opposing]})
    return out


def state_distribution(rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        groups[row["state_variant_id"]].append(row)
    out = []
    for sid, units in groups.items():
        out.append({"state_variant_id": sid, "raw_status": units[0]["raw_status"],
                    "status": units[0]["status"], "status_cluster_id": units[0]["status_cluster_id"],
                    "review_count": len(review_groups(units)), "sentiment": sentiment_distribution(units),
                    "evidence_unit_ids": [u["idx"] for u in units]})
    return sorted(out, key=lambda r: (-r["review_count"], r["raw_status"] or "", r["state_variant_id"] or ""))


def summary(rows: list[dict], total_reviews: int, desired=None, contrary=(), sentiments=None) -> dict:
    groups = classify_reviews(rows, desired, contrary, sentiments)
    ids = lambda label: [g["review_id"] for g in groups if label in g["labels"]]
    n = len(groups)
    return {"related_review_count": n, "catalog_review_count": total_reviews,
            "mention_rate": n / total_reviews if total_reviews else None,
            "sentiment": sentiment_distribution(rows), "state_distribution": state_distribution(rows),
            "matching_review_count": len(ids("matching")),
            "contrary_review_count": len(ids("contrary")) if contrary else None,
            "contrary_scope": "specified_state_ids" if contrary else "not_evaluated",
            "other_review_count": len(ids("other")), "unknown_state_review_count": len(ids("unknown_state")),
            "matching_review_ids": ids("matching"),
            "contrary_review_ids": ids("contrary") if contrary else None,
            "matching_and_contrary_review_count": sum("matching" in g["labels"] and "contrary" in g["labels"] for g in groups),
            "evidence_unit_ids": [r["idx"] for r in rows],
            "claim_scope": "review_report"}
