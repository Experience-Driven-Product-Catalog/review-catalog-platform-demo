"""Freeze the existing keyboard_search SQLite catalog; never recluster or extract."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(source: Path, output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".building")
    temporary.unlink(missing_ok=True)
    objective = source / "products.sqlite"
    experience = source / "data/experience/experience.sqlite"
    original = json.loads(experience.with_name("manifest.json").read_text())
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha(objective) == original["objective_db_sha256"], (
        "Objective source hash mismatch"
    )
    assert sha(experience) == original["sqlite_sha256"], (
        "Experience source hash mismatch"
    )
    with (
        sqlite3.connect(objective.resolve().as_uri() + "?mode=ro", uri=True) as src,
        sqlite3.connect(temporary, uri=True) as db,
    ):
        src.backup(db)
        db.execute(
            "ATTACH DATABASE ? AS experience",
            (experience.resolve().as_uri() + "?mode=ro",),
        )
        names = [
            r[0]
            for r in db.execute(
                "SELECT name FROM experience.sqlite_master WHERE type='table' AND name != 'products'"
            )
        ]
        for name in names:
            sql = db.execute(
                "SELECT sql FROM experience.sqlite_master WHERE name=?", (name,)
            ).fetchone()[0]
            db.execute(sql)
            db.execute(f'INSERT INTO "{name}" SELECT * FROM experience."{name}"')
        for name, sql in db.execute(
            "SELECT name,sql FROM experience.sqlite_master WHERE type='index' AND sql IS NOT NULL"
        ).fetchall():
            db.execute(sql)
        for column in [
            "source_name TEXT",
            "objective_name TEXT",
            "review_count INTEGER",
        ]:
            db.execute("ALTER TABLE products ADD COLUMN " + column)
        db.execute(
            "UPDATE products SET (source_name,objective_name,review_count)=(SELECT source_name,objective_name,review_count FROM experience.products e WHERE e.product_id=products.product_id)"
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM products WHERE review_count IS NOT NULL"
            ).fetchone()[0]
            == 9
        )
        db.execute(
            "CREATE TABLE documents(product_id TEXT PRIMARY KEY REFERENCES products, markdown TEXT NOT NULL)"
        )
        for pid, filename in db.execute(
            "SELECT product_id,source_file FROM products"
        ).fetchall():
            db.execute(
                "INSERT INTO documents VALUES (?,?)",
                (pid, (source / filename).read_text()),
            )
        db.execute(
            "CREATE INDEX IF NOT EXISTS exact_aspect_lookup ON aspect_variants(raw_aspect)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS exact_status_lookup ON state_variants(aspect_cluster_id,raw_status)"
        )
        db.execute(
            "CREATE TABLE demo_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        meta = {
            "schema_version": "demo-1",
            "source_data_version": original["data_version"],
            "source_objective_sha256": sha(objective),
            "source_experience_sha256": sha(experience),
            "built_at": datetime.now(UTC).isoformat(),
            "counts": original["counts"],
            "policy": "fixed-D/exact-match/read-only",
            "input_storage": False,
        }
        db.executemany(
            "INSERT INTO demo_metadata VALUES (?,?)",
            [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()],
        )
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        db.commit()
        db.execute("DETACH DATABASE experience")
        db.execute("VACUUM")
    temporary.replace(output)
    meta["sha256"] = sha(output)
    output.with_name("manifest.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path, default=Path.home() / ".codex/mcp/keyboard_search"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "data/catalog.sqlite")
    args = parser.parse_args()
    build(args.source, args.output)
