"""Migrate the fixed nine-monitor snapshot to meta-search's schema; no collection or clustering."""

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from vendor.meta_search.textnorm import make_id

CATEGORY = "computer_monitor"
SYNTHETIC_AT = "2026-10-14T00:00:00Z"
SALES_POLICY = "synthetic-offers-v1"
SALES_NOTICE = "판매처·가격·배송·재고·링크는 데모 가상 정보입니다. 확인 시각은 가상 데이터 기준일이며 실제 조회·판매·구매 가능성을 뜻하지 않습니다."
# New taxonomy names for well-known monitor attributes; remaining source keys stay discoverable.
RENAMES = {
    "size_inch": "screen_size",
    "refresh_hz": "refresh_rate",
    "brightness_nits": "brightness",
    "width_mm": "width",
    "height_mm": "height",
    "depth_mm": "depth",
    "weight_kg": "weight",
    "built_in_speaker": "built_in_speakers",
}
LABELS = {
    "screen_size": "화면 크기",
    "size_class": "화면 크기 등급",
    "resolution_class": "해상도 등급",
    "resolution": "해상도",
    "refresh_rate": "화면 재생 빈도",
    "panel_type": "패널 종류",
    "brightness": "밝기",
    "contrast_ratio": "명암비",
    "response_gtg_ms": "GTG 응답 속도",
    "response_mprt_ms": "MPRT 응답 속도",
    "hdmi_count": "HDMI 단자 수",
    "dp_count": "DP 단자 수",
    "width": "너비",
    "height": "높이",
    "depth": "깊이",
    "weight": "무게",
    "aspect_ratio": "화면 비율",
}
UNITS = {
    "screen_size": "inch",
    "size_class": "inch",
    "refresh_rate": "Hz",
    "brightness": "cd/m²",
    "width": "mm",
    "height": "mm",
    "depth": "mm",
    "weight": "kg",
    "response_gtg_ms": "ms",
    "response_mprt_ms": "ms",
}
EXCLUDE = {
    "product_id",
    "name",
    "brand",
    "model",
    "source_name",
    "objective_name",
    "review_count",
    "source_file",
    "caveats",
    "price_krw",
    "price_low_krw",
    "price_high_krw",
    "price_basis",
    "availability",
}
BOOLS = {"has_dsub", "has_headphone_out"}


def build(source, output):
    if source.resolve() == output.resolve():
        raise ValueError("Source snapshot must not be overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".building")
    temporary.unlink(missing_ok=True)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    with (
        sqlite3.connect(
            source.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
        ) as src,
        sqlite3.connect(temporary) as db,
    ):
        src.row_factory = sqlite3.Row
        db.executescript((ROOT / "backend/vendor/meta_search/schema.sql").read_text())
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "INSERT INTO categories(category_id,display_name,taxonomy_status,taxonomy_version) VALUES (?,?,?,?)",
            (CATEGORY, "모니터", "normalized", 1),
        )
        db.execute(
            "CREATE TABLE demo_product_ids(product_id INTEGER PRIMARY KEY REFERENCES products,legacy_id TEXT UNIQUE NOT NULL)"
        )
        db.execute(
            "CREATE TABLE demo_source_products(product_id INTEGER PRIMARY KEY REFERENCES products,source_json TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE demo_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)"
        )
        products = [
            dict(p) for p in src.execute("SELECT * FROM products ORDER BY product_id")
        ]
        assert len(products) == 9
        ids = {p["product_id"]: i + 1 for i, p in enumerate(products)}
        columns = {
            r["name"]: r["type"] for r in src.execute("PRAGMA table_info(products)")
        }
        definitions = {}
        for key, typ in columns.items():
            if key in EXCLUDE:
                continue
            name = RENAMES.get(key, key)
            kind = (
                "boolean"
                if key in BOOLS
                else "number"
                if typ in ("INTEGER", "REAL")
                else "string"
            )
            definitions[name] = (
                LABELS.get(name, name),
                kind,
                UNITS.get(name),
                "기존 모니터 SQLite 객관 속성",
            )
        definitions["resolution"] = ("해상도", "string", None, "가로 × 세로 픽셀")
        for f in src.execute("SELECT * FROM feature_catalog"):
            definitions[RENAMES.get(f["feature_key"], f["feature_key"])] = (
                f["label_ko"],
                "boolean",
                None,
                f["description"],
            )
        for key, (label, kind, unit, definition) in definitions.items():
            db.execute(
                "INSERT INTO category_attributes VALUES (?,?,?,?,?,?,?,?)",
                (
                    CATEGORY,
                    key,
                    label,
                    definition,
                    "core" if key in LABELS else "extra",
                    kind,
                    unit,
                    "기존 데이터 보존 변환",
                ),
            )
        for p in products:
            pid = ids[p["product_id"]]
            md = src.execute(
                "SELECT markdown FROM documents WHERE product_id=?", (p["product_id"],)
            ).fetchone()[0]
            db.execute(
                "INSERT INTO products(product_id,category_id,name,brand,model,model_key,source_url,details_md,status) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    pid,
                    CATEGORY,
                    p["name"],
                    p["brand"],
                    p["model"],
                    p["product_id"],
                    "https://catalog.example.invalid/monitors/" + p["product_id"],
                    md,
                    "ready",
                ),
            )
            db.execute(
                "INSERT INTO demo_product_ids VALUES (?,?)", (pid, p["product_id"])
            )
            db.execute(
                "INSERT INTO demo_source_products VALUES (?,?)",
                (pid, json.dumps(p, ensure_ascii=False)),
            )
            values = {
                RENAMES.get(k, k): (bool(v) if k in BOOLS else v)
                for k, v in p.items()
                if k not in EXCLUDE and v is not None
            }
            values["resolution"] = f"{p['resolution_w']}x{p['resolution_h']}"
            for f in src.execute(
                "SELECT * FROM product_features WHERE product_id=?", (p["product_id"],)
            ):
                values[RENAMES.get(f["feature_key"], f["feature_key"])] = (
                    f["status"] == "yes"
                )
            for key, value in values.items():
                db.execute(
                    "INSERT INTO product_attributes VALUES (?,?,?,?,?)",
                    (pid, CATEGORY, key, json.dumps(value, ensure_ascii=False), "page"),
                )
            base = p["price_low_krw"] or p["price_krw"]
            assert base
            # Three intentionally fictional offers, near the source's fixed historical price.
            for i, (retailer, host, path) in enumerate(
                [
                    ("쿠팡", "www.coupang.com.invalid", "vp/products"),
                    ("G마켓", "link.gmarket.co.kr.invalid", "item"),
                    ("11번가", "www.11st.co.kr.invalid", "products"),
                ]
            ):
                price = max(1000, round(base * (1 + [0, 0.035, -0.02][i]) / 100) * 100)
                availability = (
                    ["available", "sold_out", "discontinued", "unknown"][(pid + i) % 4]
                    if i == 2
                    else ("sold_out" if pid == 6 and i == 1 else "available")
                )
                shipping = [0, 2500, None if pid % 3 == 0 else 3000][i]
                days = [1 + (pid % 2), 3, None if pid % 3 == 0 else 5][i]
                url = f"https://{host}/{path}/{900000000000 + pid * 100 + i}"
                db.execute(
                    "INSERT INTO offers(product_id,seller,retailer,url,price,currency,shipping_fee,shipping_days,availability,last_checked_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        pid,
                        f"데모 모니터몰 {pid:02d}-{i + 1}",
                        retailer + " (데모)",
                        url,
                        price,
                        "KRW",
                        shipping,
                        days,
                        availability,
                        SYNTHETIC_AT,
                    ),
                )
        for row in src.execute("SELECT * FROM reviews"):
            db.execute(
                "INSERT INTO reviews(review_id,product_id,body) VALUES (?,?,?)",
                (row["review_id"], ids[row["product_id"]], row["review"]),
            )
        for row in src.execute("SELECT * FROM aspects"):
            db.execute(
                "INSERT INTO aspect_clusters VALUES (?,?,?)",
                (row["aspect_cluster_id"], CATEGORY, row["aspect"]),
            )
        for row in src.execute("SELECT * FROM states"):
            db.execute(
                "INSERT INTO state_clusters VALUES (?,?,?)",
                (row["status_cluster_id"], row["aspect_cluster_id"], row["status"]),
            )
        for u in src.execute(
            "SELECT u.*,r.product_id FROM opinion_units u JOIN reviews r ON r.review_id=u.review_idx"
        ):
            db.execute(
                "INSERT INTO opinion_units VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    u["idx"],
                    u["review_idx"],
                    ids[u["product_id"]],
                    CATEGORY,
                    u["raw_aspect"],
                    u["raw_status"],
                    u["excerpt"],
                    u["opinion"],
                    u["sentiment"],
                    make_id("av", CATEGORY, u["raw_aspect"]),
                    make_id("sv", CATEGORY, u["raw_status"])
                    if u["raw_status"] is not None
                    else None,
                    u["aspect_cluster_id"],
                    u["status_cluster_id"],
                ),
            )
        counts = {
            t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
            for t in [
                "products",
                "reviews",
                "opinion_units",
                "offers",
                "category_attributes",
            ]
        }
        assert counts["reviews"] == 1609 and counts["opinion_units"] == 4828
        meta = {
            "schema_version": "meta-demo-2",
            "source_data_version": "meta-demo-2-" + sha[:12] + "-" + SALES_POLICY,
            "source_legacy_sha256": sha,
            "built_at": datetime.now(UTC).isoformat(),
            "counts": counts,
            "category": CATEGORY,
            "policy": "fixed-nine/original-expression/read-only",
            "sales": {
                "synthetic": True,
                "policy": SALES_POLICY,
                "reference_at": SYNTHETIC_AT,
                "notice": SALES_NOTICE,
            },
            "catalog_input_storage": False,
        }
        db.executemany(
            "INSERT INTO demo_metadata VALUES (?,?)",
            [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()],
        )
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        db.commit()
        db.execute("VACUUM")
    temporary.replace(output)
    meta["sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name("manifest.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--source", type=Path, default=ROOT / "data/source/keyboard_search.sqlite"
    )
    p.add_argument("--output", type=Path, default=ROOT / "data/catalog.sqlite")
    a = p.parse_args()
    build(a.source, a.output)
