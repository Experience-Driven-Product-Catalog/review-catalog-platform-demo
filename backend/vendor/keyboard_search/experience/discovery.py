"""원래 표현과 정규화 표현을 이용한 문자 검색과 상태 탐색."""
from collections import defaultdict
from condition_display import item, attribute_name

from schemas import AttributeSelector, AttributeSearchResult, PageRequest, StateListResult
from .aggregation import review_groups, sentiment_distribution
from .repository import Repository, compact


def _match(query, raw, canonical) -> tuple[int | None, str | None]:
    q, r, c = map(compact, (query,raw,canonical))
    if not q:
        return 0, "browse"
    if q == r:
        return 0, "exact_raw"
    if q == c:
        return 1, "exact_canonical"
    if q in r:
        return 2, "substring_raw"
    if q in c:
        return 3, "substring_canonical"
    return None, None


def _page(items, request):
    end = request.offset + request.limit
    return items[request.offset:end], end if end < len(items) else None


def _sample(rows, limit=2):
    return [{"product_id": group[0]["product_id"], "review_id": group[0]["review_id"],
             "opinion_units": [{"opinion_unit_id":u["idx"], "excerpt":u["excerpt"], "raw_aspect":u["raw_aspect"],
                                "raw_status":u["raw_status"], "aspect":u["aspect"], "status":u["status"], "sentiment":u["sentiment"]} for u in group]}
            for group in review_groups(rows)[:limit]]


def find_review_attributes(query="", limit=20, offset=0) -> AttributeSearchResult:
    request = PageRequest(query=query,limit=limit,offset=offset)
    with Repository() as repo:
        nodes = repo.query("SELECT v.*, a.aspect FROM aspect_variants v JOIN aspects a USING(aspect_cluster_id) ORDER BY v.raw_aspect_id")
        candidates = defaultdict(list)
        for v in nodes:
            tier, method = _match(query, v["raw_aspect"], v["aspect"])
            if tier is not None:
                candidates[v["aspect_cluster_id"]].append({**v,"match_method":method,"tier":tier})
        result = []
        for aid, variants in candidates.items():
            best = min(v["tier"] for v in variants)
            # 원래 표현의 완전 일치가 있으면 우선 선택자를 그 표현에만 한정한다.
            picked = [v for v in variants if v["tier"] == best] if best <= 1 and compact(query) else variants
            selector = AttributeSelector.model_validate({"clauses":[{"aspect_cluster_id":aid,"raw_aspect_ids":[v["raw_aspect_id"] for v in picked]}]})
            rows = repo.rows(selector)
            raw = []
            for v in sorted(variants,key=lambda v:(v["tier"],v["raw_aspect"],v["raw_aspect_id"])):
                one = AttributeSelector.model_validate({"clauses":[{"aspect_cluster_id":aid,"raw_aspect_ids":[v["raw_aspect_id"]]}]})
                vr = repo.rows(one)
                raw.append({k:v[k] for k in ("raw_aspect_id","raw_aspect","match_method")} | {"review_count":len(review_groups(vr))})
            result.append({"aspect_cluster_id":aid,"aspect":variants[0]["aspect"],"raw_aspects":raw,
                           "matched_expressions":[v["raw_aspect"] for v in picked],"match_method":picked[0]["match_method"],
                           "review_count":len(review_groups(rows)),"product_count":len({r["product_id"] for r in rows}),
                           "selector":selector.model_dump(),"cluster_selector":{"clauses":[{"aspect_cluster_id":aid,"raw_aspect_ids":None}]},
                           "evidence_samples":_sample(rows),"_tier":best})
        result.sort(key=lambda r:(r["_tier"],-r["review_count"],r["aspect_cluster_id"]))
        page,next_offset = _page(result,request)
        for r in page:
            r.pop("_tier")
        return AttributeSearchResult(**repo.versions(), attributes=page,total_count=len(result),next_offset=next_offset,
                                     applied_conditions=[item("체감","속성 검색",query.strip() or "전체 속성")],
                                     query=query, interpretation_policy="문자 일치 후보만 제공합니다. 의미 확장과 최종 선택은 대화 모델이 근거를 확인합니다.")


def list_review_states(attribute: AttributeSelector, products=None, query="", limit=30, offset=0) -> StateListResult:
    attribute = AttributeSelector.model_validate(attribute)
    request = PageRequest(query=query,limit=limit,offset=offset)
    with Repository() as repo:
        ids = repo.product_ids(products)
        rows = repo.rows(attribute, ids)
        grouped = defaultdict(list)
        for r in rows:
            if r["state_variant_id"] is not None:
                grouped[r["state_variant_id"]].append(r)
        result = []
        for sid, units in grouped.items():
            first = units[0]
            tier,method = _match(query,first["raw_status"],first["status"])
            if tier is None:
                continue
            per_product = defaultdict(list)
            for u in units:
                per_product[u["product_id"]].append(u)
            result.append({"state_variant_id":sid,"aspect_cluster_id":first["aspect_cluster_id"],
                           "status_cluster_id":first["status_cluster_id"],"status":first["status"],"raw_status":first["raw_status"],
                           "review_count":len(review_groups(units)), "product_review_counts":{p:len(review_groups(rs)) for p,rs in sorted(per_product.items())},
                           "sentiment":sentiment_distribution(units), "match_method":method,"evidence_samples":_sample(units),"_tier":tier})
        result.sort(key=lambda r:(r["_tier"],-r["review_count"],r["status_cluster_id"],r["raw_status"],r["state_variant_id"]))
        page,next_offset = _page(result,request)
        for r in page:
            r.pop("_tier")
        unknown = [r for r in rows if r["state_variant_id"] is None]
        return StateListResult(**repo.versions(),states=page,total_count=len(result),next_offset=next_offset,
                               applied_conditions=[item("체감","상태 조회",attribute_name(repo.labels(attribute)))] +
                               ([item("체감","상태 검색",query.strip())] if query.strip() else []) +
                               ([item("객관","대상 상품",", ".join(repo.products()[pid]["objective_name"] for pid in ids))] if ids is not None else []),
                               unknown_state_review_count=len(review_groups(unknown)),
                               unknown_state_product_review_counts={p:len(review_groups([r for r in unknown if r["product_id"]==p])) for p in sorted({r["product_id"] for r in unknown})},
                               attribute=attribute.model_dump(),products=ids,query=query,
                               selection_policy="같은 정규화 상태라도 원래 상태 ID를 각각 선택하세요. 없음과 거의 없음은 별개입니다.")
