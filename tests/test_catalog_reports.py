import hashlib
import sqlite3

import pytest
from demo import catalog, reports, tools


def test_catalog_is_fixed_read_only():
    assert len(catalog.products()) == 9
    assert catalog.metadata()["counts"]["reviews"] == 1609
    assert catalog.metadata()["counts"]["opinion_units"] == 4828
    db = catalog.connect()
    with pytest.raises(sqlite3.OperationalError):
        db.execute("DELETE FROM reviews")
    db.close()
    assert not catalog.rows(
        "SELECT name FROM sqlite_master WHERE name IN ('conversations','submissions','pipeline_runs')"
    )


def test_exact_match_preserves_null_and_rejects_unknown():
    units = [
        {"raw_aspect": "가격", "raw_status": "저렴함"},
        {"raw_aspect": "가격", "raw_status": None},
        {"raw_aspect": "가격", "raw_status": "지구최저가"},
        {"raw_aspect": "데이터에없는속성", "raw_status": "좋음"},
        {"raw_aspect": "전반적 상품 경험", "raw_status": None},
    ]
    result = reports.normalize(units)
    assert [r["mapping_state"] for r in result] == [
        "mapped_exact",
        "mapped_exact",
        "unresolved_status",
        "unresolved_aspect",
        "excluded",
    ]
    assert result[1]["status_id"] is None
    assert result[0]["aspect_id"] == "D-A-000048"


def test_review_votes_and_wilson():
    assert reports.collapse(["positive", "unknown"]) == "positive"
    assert reports.collapse(["positive", "neutral"]) == "mixed"
    assert reports.collapse(["unknown", "unknown"]) == "unknown"
    low, high = reports.wilson(5, 10)
    assert low == pytest.approx(0.23659309, abs=1e-7)
    assert high == pytest.approx(0.76340691, abs=1e-7)
    assert reports.distribution(["positive", "unknown"])["shares"]["positive"] == 0.5


def test_report_does_not_write_and_includes_overview():
    before = hashlib.sha256(catalog.path().read_bytes()).hexdigest()
    result = reports.generate(
        "aoc-q27g2s",
        "가격이 비싸요",
        [
            {
                "raw_aspect": "가격",
                "raw_status": "비쌈",
                "sentiment": "negative",
                "excerpt": "가격이 비싸요",
                "opinion": "가격이 비싸다고 평가함",
            }
        ],
    )
    assert result["policy"]["stored"] is False
    assert result["overview"]["aspects"]
    assert "상품의 기존 리뷰 요약" in result["markdown"]
    assert "최신 리뷰" not in result["markdown"]
    assert before == hashlib.sha256(catalog.path().read_bytes()).hexdigest()
    assert all(
        e["product"]["product_id"] != catalog.resolve_product_id("aoc-q27g2s")
        for e in result["alternatives"]
    )


def test_search_never_relaxes_and_unknown_stays_unknown():
    result = tools.invoke(
        "search_products",
        {"filters": [{"key": "screen_size", "op": "gte", "value": 99}]},
    )
    assert result["matched_count"] == 0 and result["products"] == []
    assert result["applied_conditions"]
    assert tools.invoke("search_products", {})["matched_count"] == 9
    unknown = tools.invoke(
        "search_products", {"filters": [{"key": "hdr10", "op": "eq", "value": True}]}
    )
    assert any(
        p["product_id"] == catalog.resolve_product_id("aoc-q27g2s")
        for p in unknown["undetermined"]
    )
    with pytest.raises(ValueError):
        tools.invoke("search_products", {"made_up_filter": True})


def test_all_mcp_discovery_and_evidence_tools():
    attributes = tools.invoke("find_review_attributes", {"query": "빛샘"})
    assert attributes["total"] > 0
    aid = next(
        v["aspect_variant_id"]
        for c in attributes["clusters"]
        for v in c["variants"]
        if v["raw_aspect"] == "빛샘"
    )
    selector = {"aspect_variant_ids": [aid]}
    states = tools.invoke("list_review_states", selector)
    assert states["total"] > 0
    evidence = tools.invoke("get_review_evidence", {**selector, "limit": 2})
    assert evidence["reviews"] and len(evidence["reviews"]) <= 2
    result = tools.invoke(
        "search_products",
        {"experience_conditions": [{"condition_id": "c1", **selector}]},
    )
    assert result["matched_count"] > 0
    pid = catalog.resolve_product_id("aoc-q27g2s")
    assert tools.invoke("get_product_details", {"product_id": pid})["details_md"]
    assert tools.invoke("search_product_docs", {"query": "시야각"})["results"]
    assert tools.invoke(
        "compare_products",
        {"product_ids": [pid, catalog.resolve_product_id("lg-32qn650")]},
    )
    assert (
        len(tools.invoke("get_offers", {"product_ids": [pid]})["products"][0]["offers"])
        == 3
    )


def test_original_expression_statistics_do_not_merge_canonical_collisions():
    # This source cluster contains opposite states. The source remains untouched.
    mapped = reports.normalize(
        [
            {"raw_aspect": "빛샘", "raw_status": state}
            for state in ("심함", "심하지 않음")
        ]
    )
    assert mapped[0]["status_id"] == "D-S-000918"
    # The other wording exists in the cluster but not for the exact raw aspect.
    assert mapped[1]["mapping_state"] == "unresolved_status"
    assert mapped[0]["state_variant_id"] != mapped[1]["state_variant_id"]
    _, aspects, pairs, _ = reports.base()
    # Independently count unique reviews for every original expression axis.
    for fields, aggregates in [
        ("aspect_variant_id", aspects),
        ("aspect_variant_id,state_variant_id", pairs),
    ]:
        rows = catalog.rows(
            f"SELECT u.product_id,{fields},count(DISTINCT u.review_id) AS n "
            f"FROM opinion_units u JOIN reviews r ON r.review_id=u.review_id "
            f"GROUP BY r.product_id,{fields}"
        )
        for row in rows:
            key = (row["product_id"], *(row[f] for f in fields.split(",")))
            assert aggregates[key]["support"] == row["n"]
    row = catalog.rows(
        "SELECT r.product_id FROM opinion_units u JOIN reviews r ON r.review_id=u.review_id WHERE raw_aspect='빛샘' AND raw_status='심함' LIMIT 1"
    )[0]
    result = reports.generate(
        row["product_id"],
        "빛샘이 심함",
        [
            {
                "raw_aspect": "빛샘",
                "raw_status": "심함",
                "sentiment": "negative",
                "excerpt": "빛샘이 심함",
                "opinion": "빛샘이 심함",
            }
        ],
    )
    assert result["comparisons"][0]["status"] == "심함"
    assert result["comparisons"][0]["catalog"]["status"] == "심함"
    assert result["policy"]["comparison_basis"] == "raw-expression-v1"
    for alternative in result["alternatives"]:
        assert alternative["matches"][0]["status"] == "심함"


def test_original_expression_selectors_are_required():
    from jsonschema import ValidationError

    for args in ({}, {"aspect_variant_ids": None}, {"aspect_variant_ids": []}):
        with pytest.raises(ValidationError):
            tools.invoke("list_review_states", args)
    discovery = tools.invoke("find_review_attributes", {"query": "빛샘"})
    assert "cluster_selector" not in str(discovery)
    for name in ("register_product", "get_registration_status"):
        with pytest.raises(ValueError):
            tools.invoke(name, {})
