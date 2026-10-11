"""Execute the existing keyboard_search MCP tools in-process inside Lambda.

The MCP implementation is reused with a unified SQLite adapter and stricter
original-expression selectors; no remote/always-on MCP host is needed.
"""

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from . import catalog

VENDOR = Path(__file__).resolve().parents[1] / "vendor/keyboard_search"
sys.path.insert(0, str(VENDOR))
import engine
import search_service
from experience import discovery, evidence
from policy import POLICY_MD
from schemas import AttributeSelector

TOOLS = json.loads(Path(__file__).with_name("tool_schemas.json").read_text())
COMPARISON_POLICY = "raw-expression-v1"
DEMO_POLICY = "데모 정책: 정규 군집/대표명은 참고용이다. 모든 체감 선택자 clauses에 비어 있지 않은 raw_aspect_ids를 명시해야 한다. cluster_selector는 사용할 수 없다. 상태는 원래 state_variant_id를 선택한다. 여러 원래 표현의 OR 결합은 선택 표현을 사용자에게 명시하며, 군집 전체로 자동 확장하지 않는다."
POLICY_MD += "\n\n" + DEMO_POLICY
for tool in TOOLS:
    clause = tool["parameters"].get("$defs", {}).get("AttributeClause")
    if clause:
        clause["properties"]["raw_aspect_ids"] = {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        }
        clause["required"] = ["aspect_cluster_id", "raw_aspect_ids"]
SCHEMAS = {t["name"]: t["parameters"] for t in TOOLS}


def plain(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def document(product):
    return catalog.rows(
        "SELECT markdown FROM documents WHERE product_id=?", (product["product_id"],)
    )[0]["markdown"]


def details(product, topics=None):
    return search_service.details(product, topics)


def invoke(name: str, args: dict):
    if name not in SCHEMAS:
        raise ValueError("Unknown tool")
    schema = SCHEMAS[name]
    if set(args) - set(schema.get("properties", {})):
        raise ValueError("Unknown tool arguments")
    Draft202012Validator(schema).validate(args)
    engine.DB_PATH = catalog.path()
    if name == "get_search_guide":
        result = search_service.guide()
    elif name == "search_products":
        result = search_service.search(args)
    elif name == "compare_products":
        result = search_service.compare(args["products"], args.get("experience_topics"))
    elif name == "get_product_details":
        result = details(args["product"], args.get("experience_topics"))
    elif name == "search_product_docs":
        result = engine.search_docs(
            args["query"], args.get("products"), args.get("max_results", 15)
        )
    elif name == "find_review_attributes":
        result = discovery.find_review_attributes(**args)
    elif name == "list_review_states":
        result = discovery.list_review_states(
            **{**args, "attribute": AttributeSelector.model_validate(args["attribute"])}
        )
    elif name == "get_review_evidence":
        result = evidence.get_review_evidence(
            **{**args, "attribute": AttributeSelector.model_validate(args["attribute"])}
        )
    else:
        raise ValueError("Unsupported tool")
    result = plain(result)
    if name == "get_search_guide":
        result["demo_comparison_policy"] = DEMO_POLICY
    if name == "find_review_attributes":

        def remove_cluster_selector(value):
            if isinstance(value, dict):
                value.pop("cluster_selector", None)
                for child in value.values():
                    remove_cluster_selector(child)
            elif isinstance(value, list):
                for child in value:
                    remove_cluster_selector(child)

        remove_cluster_selector(result)
    return result


__all__ = ["POLICY_MD", "TOOLS", "invoke"]
