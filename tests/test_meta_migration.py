import json
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from demo import catalog, tools
from vendor.meta_search.textnorm import make_id

SOURCE = Path(__file__).resolve().parents[1] / "data/source/keyboard_search.sqlite"


def test_all_original_products_reviews_units_and_cluster_labels_are_preserved():
    with sqlite3.connect(SOURCE.as_uri() + "?mode=ro&immutable=1", uri=True) as old:
        old.row_factory = sqlite3.Row
        products = {p["product_id"]: p for p in catalog.products()}
        for row in catalog.rows("SELECT * FROM demo_product_ids"):
            original = dict(
                old.execute(
                    "SELECT * FROM products WHERE product_id=?", (row["legacy_id"],)
                ).fetchone()
            )
            current = products[row["product_id"]]
            assert (
                current["name"] == original["name"]
                and current["review_count"] == original["review_count"]
            )
            preserved = json.loads(
                catalog.rows(
                    "SELECT source_json FROM demo_source_products WHERE product_id=?",
                    (row["product_id"],),
                )[0]["source_json"]
            )
            assert preserved == original
        before = {
            r["review_id"]: r["review"] for r in old.execute("SELECT * FROM reviews")
        }
        assert before == {
            r["review_id"]: r["body"] for r in catalog.rows("SELECT * FROM reviews")
        }
        original = {
            r["idx"]: dict(r) for r in old.execute("SELECT * FROM opinion_units")
        }
        for unit in catalog.rows("SELECT * FROM opinion_units"):
            prior = original[unit["unit_id"]]
            for field in [
                "raw_aspect",
                "raw_status",
                "excerpt",
                "opinion",
                "sentiment",
                "aspect_cluster_id",
            ]:
                assert unit[field] == prior[field]
            assert unit["review_id"] == prior["review_idx"]
            assert unit["state_cluster_id"] == prior["status_cluster_id"]
            assert unit["aspect_variant_id"] == make_id(
                "av", "computer_monitor", unit["raw_aspect"]
            )
        assert {
            r["aspect_cluster_id"]: r["aspect"]
            for r in old.execute("SELECT * FROM aspects")
        } == {
            r["aspect_cluster_id"]: r["label"]
            for r in catalog.rows("SELECT * FROM aspect_clusters")
        }
        for p in catalog.products():
            assert (
                tools.invoke("get_product_details", {"product_id": p["product_id"]})[
                    "details_md"
                ]
                == old.execute(
                    "SELECT markdown FROM documents WHERE product_id=?",
                    (p["legacy_id"],),
                ).fetchone()[0]
            )
    assert catalog.rows("PRAGMA integrity_check")[0]["integrity_check"] == "ok"
    assert not catalog.rows("PRAGMA foreign_key_check")
    assert catalog.rows("SELECT COUNT(*) AS n FROM jobs")[0]["n"] == 0


def test_objective_eav_values_preserve_false_and_unknown():
    guide = tools.invoke("get_search_guide", {})
    assert len(guide["products"]) == 9 and len(guide["categories"]) == 1
    assert {"screen_size", "refresh_rate", "hdr10"} <= {
        a["key"] for a in guide["attributes"]
    }
    result = tools.invoke(
        "search_products",
        {
            "filters": [
                {"key": "size_class", "op": "eq", "value": 27},
                {"key": "resolution_class", "op": "eq", "value": "QHD"},
            ]
        },
    )
    assert {p["model"] for p in result["results"]} == {"Q27G2S", "C27G54T"}
    assert any(
        r["value_json"] == "false"
        for r in catalog.rows(
            "SELECT value_json FROM product_attributes WHERE key='has_dsub'"
        )
    )
    assert not catalog.rows(
        "SELECT * FROM product_attributes WHERE product_id=1 AND key='hdr10'"
    )


def test_synthetic_offers_and_all_sales_filters_use_one_offer():
    offers = catalog.rows("SELECT * FROM offers")
    assert len(offers) == 27
    assert all(urlsplit(o["url"]).hostname.endswith(".invalid") for o in offers)
    conditions = {
        "max_price": 300000,
        "max_shipping_fee": 0,
        "max_shipping_days": 2,
        "retailers": ["쿠팡"],
        "availability": ["available"],
    }
    expected = {
        o["product_id"]
        for o in offers
        if o["price"] <= 300000
        and o["shipping_fee"] == 0
        and o["shipping_days"] is not None
        and o["shipping_days"] <= 2
        and "쿠팡" in o["retailer"]
        and o["availability"] == "available"
    }
    result = tools.invoke("search_products", {"offer_filter": conditions})
    assert {p["product_id"] for p in result["results"]} == expected
    assert result["sales_data_policy"]["synthetic"] is True
    assert any(c["type"] == "판매" for c in result["applied_conditions"])
    offers = tools.invoke("get_offers", {"product_ids": [1, 3]})["products"]
    for product in offers:
        for offer in product["offers"]:
            assert offer["total_price"] == (
                offer["price"] + offer["shipping_fee"]
                if offer["shipping_fee"] is not None
                else None
            )
    unavailable = tools.invoke(
        "search_products", {"offer_filter": {"retailers": ["존재하지 않는 판매처"]}}
    )
    assert unavailable["matched_count"] == 0


def test_meta_connection_is_read_only_and_mutating_tools_unavailable():
    from vendor.meta_search.db import database

    with (
        database(catalog.path()) as connection,
        pytest.raises(sqlite3.OperationalError),
    ):
        connection.execute("DELETE FROM offers")
    assert len(tools.TOOLS) == 9
    assert {"register_product", "get_registration_status"}.isdisjoint(tools.SCHEMAS)


def test_condition_cards_hide_unrestricted_and_non_attribute_rows():
    assert tools.invoke("search_products", {})["applied_conditions"] == []
    assert (
        tools.invoke("search_products", {"offer_filter": {"currency": "KRW"}})[
            "applied_conditions"
        ]
        == []
    )
    result = tools.invoke(
        "search_products",
        {
            "user_request": "27형을 찾고 싶어요",
            "interpretation_notes": ["추가 조건 없음"],
            "filters": [{"key": "size_class", "op": "eq", "value": 27}],
            "offer_filter": {"max_shipping_fee": 0},
            "sort": {"by": "price", "order": "desc"},
        },
    )
    cards = result["applied_conditions"]
    assert [(c["type"], c["method"]) for c in cards] == [
        ("객관", "filter"),
        ("판매", "filter"),
        ("판매", "sort"),
    ]
    assert all(
        c["type"] in ("객관", "체감", "판매") and c["value"] != "제한 없음"
        for c in cards
    )
    assert not any("27형을 찾고 싶어요" in c["value"] for c in cards)
    assert "size_class" not in cards[0]["value"]
    assert "배송비" in cards[1]["value"]
    assert "내림차순" in cards[2]["value"]


def test_evidence_topic_is_search_and_display_names_are_plain():
    from vendor.meta_search.textnorm import make_id

    result = tools.invoke(
        "search_products",
        {
            "evidence_topics": [
                {
                    "topic_id": "bleed",
                    "aspect_variant_ids": [make_id("av", "computer_monitor", "빛샘")],
                }
            ]
        },
    )
    assert result["applied_conditions"] == [
        {
            "type": "체감",
            "condition": "체감",
            "value": "빛샘 리뷰 근거",
            "method": "search",
        }
    ]
    offers = tools.invoke("get_offers", {"product_ids": [1]})["products"][0]["offers"]
    assert {o["retailer"] for o in offers} == {"쿠팡", "G마켓", "11번가"}
    assert all("데모" not in o["seller"] and "가상" not in o["seller"] for o in offers)
