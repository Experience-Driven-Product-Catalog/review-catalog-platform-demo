"""체감 카탈로그의 읽기 전용 연결과 선택자 검증."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import unicodedata

from schemas import AttributeSelector

ROOT = Path(__file__).resolve().parents[2]
POLICY_VERSION = "review-evidence-v1"
SCHEMA_VERSION = "1.0.0"


def compact(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", value).casefold())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=8)
def _verified(db_path: str, db_signature: tuple, manifest_signature: tuple, objective_signature: tuple) -> dict:
    path = Path(db_path)
    manifest = json.loads(path.with_name("manifest.json").read_text())
    import engine
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("policy_version") != POLICY_VERSION:
        raise ValueError("체감 카탈로그의 스키마/정책 버전이 서버와 다릅니다. 다시 빌드하세요.")
    if digest(path) != manifest.get("sqlite_sha256"):
        raise ValueError("체감 SQLite 해시가 매니페스트와 다릅니다.")
    if digest(engine.DB_PATH) != manifest.get("objective_db_sha256"):
        raise ValueError("객관 DB가 체감 카탈로그 빌드 이후 변경되었습니다. 다시 빌드하세요.")
    return manifest


def _signature(path: Path) -> tuple:
    s = path.stat()
    return (str(path.resolve()), s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


class Repository:
    def __init__(self):
        from demo import catalog
        self.path = catalog.path()
        self.con = catalog.connect()
        self.manifest = {r["key"]: json.loads(r["value"]) for r in self.con.execute("SELECT * FROM metadata")}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.con.close()

    def query(self, sql: str, params=()) -> list[dict]:
        return [dict(r) for r in self.con.execute(sql, params)]

    def versions(self) -> dict:
        return {k: self.manifest[k] for k in ("data_version", "schema_version", "policy_version")}

    def products(self) -> dict[str, dict]:
        return {p["product_id"]: p for p in self.query("SELECT * FROM products ORDER BY product_id")}

    def product_ids(self, tokens: list[str] | None) -> list[str] | None:
        if tokens is None:
            return None
        if not tokens:
            raise ValueError("products는 빈 목록일 수 없습니다.")
        import engine
        products, _ = engine.load_data()
        return list(dict.fromkeys(engine.resolve_product(t, products)["product_id"] for t in tokens))

    def selector_sql(self, attribute: AttributeSelector) -> tuple[str, list]:
        clauses, args = [], []
        for clause in attribute.clauses:
            if not self.query("SELECT 1 FROM aspects WHERE aspect_cluster_id=?", [clause.aspect_cluster_id]):
                raise ValueError(f"존재하지 않는 속성 ID: {clause.aspect_cluster_id}")
            part = "u.aspect_cluster_id=?"
            args.append(clause.aspect_cluster_id)
            if clause.raw_aspect_ids is not None:
                for rid in clause.raw_aspect_ids:
                    if not self.query("SELECT 1 FROM aspect_variants WHERE raw_aspect_id=? AND aspect_cluster_id=?", [rid, clause.aspect_cluster_id]):
                        raise ValueError(f"속성 군집에 속하지 않는 원래 속성 ID: {rid}")
                part += " AND u.raw_aspect_id IN (" + ",".join("?" for _ in clause.raw_aspect_ids) + ")"
                args.extend(clause.raw_aspect_ids)
            clauses.append("(" + part + ")")
        return "(" + " OR ".join(clauses) + ")", args

    def validate_states(self, attribute: AttributeSelector, *groups) -> None:
        ids = set().union(*(set(g or []) for g in groups))
        where, args = self.selector_sql(attribute)
        if ids:
            available = {r["state_variant_id"] for r in self.query("SELECT DISTINCT u.state_variant_id FROM opinion_units u WHERE " + where, args)}
            for sid in ids:
                if sid not in available:
                    raise ValueError(f"선택 속성에서 관측되지 않은 상태 ID: {sid}")

    def rows(self, attribute: AttributeSelector, products: list[str] | None = None) -> list[dict]:
        where, args = self.selector_sql(attribute)
        if products is not None:
            if not products:
                return []
            where += " AND r.product_id IN (" + ",".join("?" for _ in products) + ")"
            args.extend(products)
        return self.query("SELECT u.*, r.review_id, r.product_id, r.review AS review_text FROM opinion_units u JOIN reviews r ON u.review_idx=r.review_id WHERE " + where + " ORDER BY r.product_id,r.review_id,u.idx", args)

    def labels(self, attribute: AttributeSelector, states: list[str] | None = None) -> dict:
        selected = []
        for clause in attribute.clauses:
            name = self.query("SELECT aspect FROM aspects WHERE aspect_cluster_id=?", [clause.aspect_cluster_id])[0]["aspect"]
            raw = None if clause.raw_aspect_ids is None else [self.query("SELECT raw_aspect FROM aspect_variants WHERE raw_aspect_id=?", [rid])[0]["raw_aspect"] for rid in clause.raw_aspect_ids]
            selected.append({"aspect_cluster_id": clause.aspect_cluster_id, "aspect": name, "raw_aspects": raw})
        state_labels = None if states is None else [self.query("SELECT state_variant_id, raw_status, status_cluster_id FROM state_variants WHERE state_variant_id=?", [sid])[0] for sid in states]
        return {"attributes": selected, "states": state_labels}
