import json
import time
from collections import defaultdict

import pytest
from demo import agent, catalog, chat_policy, reports, tools
from vendor.meta_search.textnorm import make_id

AID = make_id("av", "computer_monitor", "가성비")


def test_chat_tools_never_expose_review_text_or_sales_time():
    cases = [
        ("get_search_guide", {}),
        ("find_review_attributes", {"query": "가성비"}),
        ("list_review_states", {"aspect_variant_ids": [AID]}),
        (
            "get_review_evidence",
            {"aspect_variant_ids": [AID], "include_full_review": True},
        ),
        ("get_product_details", {"product_id": 1}),
        ("get_offers", {"product_ids": [1]}),
        (
            "search_products",
            {
                "evidence_topics": [{"topic_id": "value", "aspect_variant_ids": [AID]}],
                "sort": {"by": "experience", "aspect_variant_ids": [AID]},
            },
        ),
        (
            "compare_products",
            {
                "product_ids": [1, 2],
                "experience_topics": [
                    {"topic_id": "value", "aspect_variant_ids": [AID]}
                ],
            },
        ),
    ]

    def inspect(value):
        if isinstance(value, dict):
            assert not (value.keys() & chat_policy.HIDDEN)
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    for name, args in cases:
        result = tools.for_chat(name, args)
        inspect(result)
        assert result["chat_answer_policy"] == chat_policy.RULES
        if name == "search_products":
            assert "Wilson" not in json.dumps(result["applied_conditions"])
    raw = tools.invoke(
        "get_review_evidence",
        {"aspect_variant_ids": [AID], "include_full_review": True},
    )
    assert raw["reviews"][0]["full_review"]
    assert "reviews" not in tools.for_chat(
        "get_review_evidence", {"aspect_variant_ids": [AID]}
    )


def test_statistics_use_unique_reviews_not_units_or_pagination():
    statistics = tools.for_chat(
        "get_review_evidence", {"aspect_variant_ids": [AID], "limit": 1}
    )["statistics"]
    by_product = defaultdict(lambda: defaultdict(list))
    for row in catalog.rows(
        "SELECT product_id,review_id,sentiment FROM opinion_units WHERE aspect_variant_id=?",
        (AID,),
    ):
        by_product[row["product_id"]][row["review_id"]].append(row["sentiment"])
    for item in statistics:
        votes = [
            reports.collapse(labels)
            for labels in by_product[item["product_id"]].values()
        ]
        n, k = len(votes), votes.count("positive")
        assert item["related_review_count"] == n
        assert item["positive_review_count"] == k
        assert item["positive_percentage_of_related"] == (
            round(k * 100 / n, 1) if n else None
        )
        assert sum(item["sentiment_distribution"].values()) == n
        assert item["total_review_count"] >= n
    filtered = tools.for_chat(
        "get_review_evidence",
        {"aspect_variant_ids": [AID], "limit": 100, "sentiments": ["positive"]},
    )["statistics"]
    for first, second in zip(statistics, filtered):
        for key in (
            "related_review_count",
            "positive_review_count",
            "positive_percentage_of_related",
        ):
            assert first[key] == second[key]


def test_pre_policy_conversation_cannot_restore_raw_quote_context():
    token = agent.sign(
        {
            "response_id": "resp_old",
            "filters": {},
            "conditions": [],
            "expires": time.time() + 3600,
            "version": catalog.metadata()["source_data_version"],
            "comparison_policy": tools.COMPARISON_POLICY,
        }
    )
    with pytest.raises(agent.PublicError):
        agent.verify(token)
