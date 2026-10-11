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


def products():
    return rows(
        "SELECT product_id,name,brand,model,size_class,resolution_class,refresh_hz,review_count FROM products ORDER BY name"
    )
