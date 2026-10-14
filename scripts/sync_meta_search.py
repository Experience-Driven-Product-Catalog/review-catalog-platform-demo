"""Vendor only meta-search read paths. Run with the source project's Python environment."""

import argparse
import ast
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, default=ROOT.parent / "meta-search")
args = parser.parse_args()
source = args.source.resolve() / "src/meta_search"
target = ROOT / "backend/vendor/meta_search"
target.mkdir(parents=True, exist_ok=True)
files = ["__init__.py", "policy.py", "textnorm.py", "validation.py", "schema.sql"]
files += [str(p.relative_to(source)) for p in sorted((source / "search").glob("*.py"))]
hashes = {}
for relative in files:
    data = (source / relative).read_bytes()
    hashes[relative] = hashlib.sha256(data).hexdigest()
    dest = target / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = data.decode().replace(
        "from mcp.server.fastmcp.exceptions import ToolError",
        "from ..errors import ToolError",
    )
    dest.write_text(text)
(target / "errors.py").write_text(
    'class ToolError(ValueError):\n    """MCP tool validation error exposed through Responses function calling."""\n'
)
(
    target / "db.py"
).write_text('''"""Demo adapter: the published snapshot is always read-only."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

@contextmanager
def database(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro&immutable=1", uri=True, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        yield connection
    finally:
        connection.close()
''')
# Preserve the demo's original-expression policy in product detail/guide summaries.
p = target / "search/service.py"
s = p.read_text().replace(
    'groups[unit["aspect_cluster_id"]].append(unit)',
    'groups[unit["aspect_variant_id"]].append(unit)',
)
s = s.replace(
    '"aspect_cluster_id": aid,\n                "label": selected[0]["aspect_label"],',
    '"aspect_cluster_id": selected[0]["aspect_cluster_id"],\n                "aspect_variant_id": aid,\n                "label": selected[0]["raw_aspect"],',
)
p.write_text(s)
# Extract original function signatures without importing server.py (which initializes DB/jobs).
sys.path.insert(0, str(source.parent))
import typing

from mcp.server.fastmcp.tools.base import Tool
from meta_search.search import models
from pydantic import Field

namespace = {**vars(typing), **vars(models), "Field": Field}
allowed = {
    "get_search_guide",
    "search_products",
    "compare_products",
    "get_product_details",
    "search_product_docs",
    "find_review_attributes",
    "list_review_states",
    "get_review_evidence",
    "get_offers",
}
schemas = []
server = source / "server.py"
hashes["server.py"] = hashlib.sha256(server.read_bytes()).hexdigest()
for node in ast.parse(server.read_text()).body:
    if isinstance(node, ast.FunctionDef) and node.name in allowed:
        node.decorator_list = []
        exec(  # noqa: S102 - trusted local source signatures, no server bootstrap
            compile(ast.Module(body=[node], type_ignores=[]), str(server), "exec"),
            namespace,
        )
        tool = Tool.from_function(namespace[node.name])
        schemas.append(
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "strict": False,
            }
        )
assert len(schemas) == 9
(ROOT / "backend/demo/tool_schemas.json").write_text(
    json.dumps(schemas, ensure_ascii=False, indent=2) + "\n"
)
(target / "UPSTREAM.json").write_text(
    json.dumps(
        {
            "source": "meta-search/src/meta_search",
            "files": hashes,
            "adaptations": [
                "ToolError transport shim",
                "read-only SQLite connection",
                "top aspect summaries use original expression IDs",
            ],
        },
        indent=2,
    )
    + "\n"
)
old = ROOT / "backend/vendor/keyboard_search"
if old.exists():
    shutil.rmtree(old)
print("Vendored 9 read-only tools; no registration, clustering, models or jobs.")
