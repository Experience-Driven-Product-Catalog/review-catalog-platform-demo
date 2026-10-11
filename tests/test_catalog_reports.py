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
        e["product"]["product_id"] != "aoc-q27g2s" for e in result["alternatives"]
    )


def test_search_never_relaxes_and_unknown_stays_unknown():
    result = tools.invoke("search_products", {"min_size_class": 99})
    assert result["matched_count"] == 0 and result["products"] == []
    assert result["applied_conditions"]
    assert tools.invoke("search_products", {})["matched_count"] == 9
    with pytest.raises(ValueError):
        tools.invoke("search_products", {"made_up_filter": True})


def test_all_mcp_discovery_and_evidence_tools():
    attributes = tools.invoke("find_review_attributes", {"query": "빛샘"})
    assert attributes["total_count"] > 0
    # Use the actual MCP selector returned by discovery, never invent an ID.
    aid = catalog.rows(
        "SELECT aspect_cluster_id FROM aspect_variants WHERE raw_aspect='빛샘'"
    )[0]["aspect_cluster_id"]
    selector = {"clauses": [{"aspect_cluster_id": aid}]}
    states = tools.invoke("list_review_states", {"attribute": selector})
    assert states["total_count"] > 0
    evidence = tools.invoke("get_review_evidence", {"attribute": selector, "limit": 2})
    assert evidence["reviews"] and len(evidence["reviews"]) <= 2
    result = tools.invoke(
        "search_products",
        {"experience_conditions": [{"condition_id": "c1", "attribute": selector}]},
    )
    assert result["matched_count"] > 0
    assert tools.invoke("get_product_details", {"product": "aoc-q27g2s"})[
        "detail_document_markdown"
    ]
    assert tools.invoke("search_product_docs", {"query": "시야각"})
    assert tools.invoke("compare_products", {"products": ["aoc-q27g2s", "lg-32qn650"]})
