"""Execute the existing keyboard_search MCP tools in-process inside Lambda.

The tool schemas and search policy are from the MCP server. Only transport and
the unified SQLite storage adapter differ; no remote/always-on MCP host is needed.
"""
import json
import sys
from pathlib import Path
from functools import lru_cache
from jsonschema import Draft202012Validator
from . import catalog

VENDOR=Path(__file__).resolve().parents[1]/'vendor/keyboard_search'
sys.path.insert(0,str(VENDOR))
import engine
import search_service
from experience import discovery,evidence
from schemas import AttributeSelector
from policy import POLICY_MD

TOOLS=json.loads(Path(__file__).with_name('tool_schemas.json').read_text())
SCHEMAS={t['name']:t['parameters'] for t in TOOLS}

def plain(value):return value.model_dump(mode='json') if hasattr(value,'model_dump') else value

def document(product):
    return catalog.rows('SELECT markdown FROM documents WHERE product_id=?',(product['product_id'],))[0]['markdown']

def details(product,topics=None):
    return search_service.details(product,topics)

def invoke(name: str, args: dict):
    if name not in SCHEMAS:raise ValueError('Unknown tool')
    schema=SCHEMAS[name]
    if set(args)-set(schema.get('properties',{})):raise ValueError('Unknown tool arguments')
    Draft202012Validator(schema).validate(args)
    engine.DB_PATH=catalog.path()
    if name=='get_search_guide':result=search_service.guide()
    elif name=='search_products':result=search_service.search(args)
    elif name=='compare_products':result=search_service.compare(args['products'],args.get('experience_topics'))
    elif name=='get_product_details':result=details(args['product'],args.get('experience_topics'))
    elif name=='search_product_docs':result=engine.search_docs(args['query'],args.get('products'),args.get('max_results',15))
    elif name=='find_review_attributes':result=discovery.find_review_attributes(**args)
    elif name=='list_review_states':result=discovery.list_review_states(**{**args,'attribute':AttributeSelector.model_validate(args['attribute'])})
    elif name=='get_review_evidence':result=evidence.get_review_evidence(**{**args,'attribute':AttributeSelector.model_validate(args['attribute'])})
    else:raise ValueError('Unsupported tool')
    return plain(result)
