from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def path() -> Path:
    local = os.environ.get("CATALOG_PATH")
    if local:
        target = Path(local).resolve()
    else:
        import boto3

        expected = os.environ["CATALOG_SHA256"]
        target = Path("/tmp") / f"catalog-{expected}.sqlite"
        if (
            not target.exists()
            or hashlib.sha256(target.read_bytes()).hexdigest() != expected
        ):
            temp = target.with_suffix(".download")
            boto3.client("s3").download_file(
                os.environ["CATALOG_BUCKET"], os.environ["CATALOG_KEY"], str(temp)
            )
            if hashlib.sha256(temp.read_bytes()).hexdigest() != expected:
                temp.unlink(missing_ok=True)
                raise RuntimeError("Catalog checksum mismatch")
            temp.replace(target)
    if not target.is_file():
        raise RuntimeError("Catalog unavailable")
    expected = os.environ.get("CATALOG_SHA256")
    if expected and hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        raise RuntimeError("Catalog checksum mismatch")
    return target


def connect():
    connection = sqlite3.connect(path().as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def rows(sql, params=()):
    db = connect()
    try:
        return [dict(r) for r in db.execute(sql, params)]
    finally:
        db.close()


@lru_cache(maxsize=1)
def metadata():
    return {
        r["key"]: json.loads(r["value"]) for r in rows("SELECT * FROM demo_metadata")
    }


def resolve_product_id(value):
    found = rows(
        "SELECT product_id FROM demo_product_ids WHERE legacy_id=? OR CAST(product_id AS TEXT)=?",
        (str(value), str(value)),
    )
    if not found:
        raise ValueError("등록된 상품이 아닙니다.")
    return found[0]["product_id"]


def products():
    return rows("""
        SELECT p.product_id,m.legacy_id,p.name,p.brand,p.model,p.category_id,
        (SELECT json_extract(value_json,'$') FROM product_attributes WHERE product_id=p.product_id AND key='size_class') AS size_class,
        (SELECT json_extract(value_json,'$') FROM product_attributes WHERE product_id=p.product_id AND key='resolution_class') AS resolution_class,
        (SELECT json_extract(value_json,'$') FROM product_attributes WHERE product_id=p.product_id AND key='refresh_rate') AS refresh_hz,
        (SELECT COUNT(*) FROM reviews WHERE product_id=p.product_id) AS review_count
        FROM products p JOIN demo_product_ids m USING(product_id) WHERE p.status='ready' ORDER BY p.name
    """)
