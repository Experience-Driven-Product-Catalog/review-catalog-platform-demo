"""객관 조건과 체감 조건을 결합하고 최종 후보를 정렬한다."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import engine
import condition_display as display
from policy import ANSWER_REQUIREMENTS
from schemas import AttributeSelector, ExperienceCondition, ExperienceSort, EvidenceTopic, ProductSearchResult
from experience.repository import Repository
from experience.aggregation import summary
from experience.evidence import samples
from experience.filtering import evaluate_condition
from experience.ranking import score


def _models(values, cls):
    return [cls.model_validate(v) for v in values or []]


def _unique(items, field):
    ids = [getattr(i,field) for i in items]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{field}는 호출 안에서 유일해야 합니다.")


def _by_product(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["product_id"]].append(r)
    return out


def _describe(labels):
    return " OR ".join(a["aspect"] + (" [" + ", ".join(a["raw_aspects"]) + "]" if a["raw_aspects"] is not None else " [군집 전체]") for a in labels["attributes"])


def _state_names(labels):
    return "상태 제한 없음" if labels["states"] is None else " OR ".join(s["raw_status"] for s in labels["states"])


def topic_summary(repo, topic, rows, product_id):
    return {"topic_id":topic.topic_id,"attribute":topic.attribute.model_dump(),
            "selected_labels":repo.labels(topic.attribute,topic.desired_state_ids),
            "contrary_labels":repo.labels(topic.attribute,topic.contrary_state_ids)["states"] if topic.contrary_state_ids else None,
            **summary(rows,repo.products()[product_id]["review_count"],topic.desired_state_ids,topic.contrary_state_ids),
            "evidence_samples":samples(rows,topic.desired_state_ids,topic.contrary_state_ids)}


def _topic_data(repo, topics):
    result = []
    for topic in topics:
        repo.validate_states(topic.attribute,topic.desired_state_ids,topic.contrary_state_ids)
        result.append((topic,_by_product(repo.rows(topic.attribute))))
    return result


def search(params: dict) -> dict | ProductSearchResult:
    params = dict(params)
    conditions = _models(params.pop("experience_conditions",None),ExperienceCondition)
    sort_input = params.pop("experience_sort",None)
    sorting = ExperienceSort.model_validate(sort_input) if sort_input is not None else None
    topics = _models(params.pop("evidence_topics",None),EvidenceTopic)
    if not conditions and sorting is None and not topics:
        return engine.search(params)
    _unique(conditions,"condition_id")
    _unique(topics,"topic_id")
    products,catalog = engine.load_data()
    constraints, _ = engine.build_constraints(params,catalog)
    ev = engine.evaluate(products,constraints)
    # 기존 엔진의 전체 객관 정렬을 먼저 얻되 표시 제한은 최종 단계로 미룬다.
    objective = engine.search({**params,"limit":len(products)})
    limit = max(1,min(int(params.get("limit") or len(products)),len(products)))
    with Repository() as repo:
        all_ids = list(repo.products())
        product_info = repo.products()
        evaluations = {pid:[] for pid in all_ids}
        condition_descriptions = []
        for condition in conditions:
            repo.validate_states(condition.attribute,condition.desired_state_ids,condition.contrary_state_ids)
            rows = _by_product(repo.rows(condition.attribute))
            for pid in all_ids:
                evaluations[pid].append(evaluate_condition(rows[pid],condition,product_info[pid]["review_count"]))
            label = repo.labels(condition.attribute,condition.desired_state_ids)
            opposite = _state_names(repo.labels(condition.attribute,condition.contrary_state_ids)) if condition.contrary_state_ids else "미평가"
            condition_descriptions.append({"condition_id":condition.condition_id,"selected_labels":label,"contrary_states":opposite})
        scores = {}
        sort_description = None
        if sorting is not None:
            repo.validate_states(sorting.attribute,sorting.desired_state_ids)
            rows = _by_product(repo.rows(sorting.attribute))
            scores = {pid:score(rows[pid],sorting) for pid in all_ids}
            sort_description = repo.labels(sorting.attribute,sorting.desired_state_ids)
        topic_data = _topic_data(repo,topics)
        matched = []
        failed, unknown = [], []
        for p in objective["products"]:
            pid = p["product_id"]
            results = evaluations[pid]
            if any(r["state"] == "FAIL" for r in results):
                failed.append({"product_id":pid,"name":p["name"],"condition_results":results})
            elif any(r["state"] == "UNKNOWN" for r in results):
                unknown.append({"product_id":pid,"name":p["name"],"condition_results":results})
            else:
                matched.append({**p,"condition_results":results})
        # 동점에서 객관 정렬을 유지하되 마지막 결정은 상품 ID로 고정한다.
        sort_key = params.get("sort_by") or "price"
        _,getter,default_order,asc_label,desc_label = engine.SORTS[sort_key]
        order = (params.get("sort_order") or default_order).lower()
        raw = {p["product_id"]:p for p in products}
        def objective_key(p):
            v = getter(raw[p["product_id"]])
            return (v is None, v if order == "asc" else engine._neg(v) if v is not None else 0,p["product_id"])
        matched.sort(key=objective_key)
        if sorting:
            matched.sort(key=lambda p:(scores[p["product_id"]]["score"] is None,
                                       (scores[p["product_id"]]["score"] or 0) * (1 if sorting.order == "asc" else -1)))
            rank = 0
            for p in matched:
                s = dict(scores[p["product_id"]])
                if s["score"] is not None:
                    rank += 1
                    s["rank"] = rank
                p["experience_ranking"] = s
        shown = matched[:limit]
        for p in shown:
            p["experience_topics"] = [topic_summary(repo,t,rows[p["product_id"]],p["product_id"]) for t,rows in topic_data]
            for c,result in zip(conditions,p["condition_results"]):
                units = repo.rows(c.attribute,[p["product_id"]])
                result["evidence_samples"] = samples(units,c.desired_state_ids,c.contrary_state_ids,sentiments=c.sentiments)
        echo = objective["applied_filters"]
        echo.update({"experience_conditions":[c.model_dump(mode="json") for c in conditions],
                     "experience_sort":sorting.model_dump(mode="json") if sorting else None,
                     "evidence_topics":[t.model_dump(mode="json") for t in topics]})
        sort_label = asc_label if order == "asc" else desc_label
        condition_items = display.objective_conditions(constraints)
        for condition in conditions:
            condition_items.append(display.review_condition(repo.labels(condition.attribute,condition.desired_state_ids),condition.min_matching_reviews,condition.sentiments))
            if condition.max_contrary_reviews is not None:
                condition_items.append(display.contrary_limit(repo.labels(condition.attribute,condition.contrary_state_ids),condition.max_contrary_reviews))
        if sorting:
            condition_items.append(display.experience_sort(sort_description,sorting.metric,sorting.order))
        condition_items.append(display.objective_sort(sort_key,sort_label,secondary=sorting is not None))
        for topic in topics:
            if not any(topic.attribute == c.attribute and topic.desired_state_ids == c.desired_state_ids for c in conditions):
                condition_items.append(display.evidence_topic(repo.labels(topic.attribute,topic.desired_state_ids)))
        if sorting:
            metric_label = "관련 리뷰 전체 중 긍정 비율의 95% Wilson 하한" if sorting.metric == "positive_wilson_lower" else "관련 리뷰 전체 중 지정 상태 보고 비율의 95% Wilson 하한"
            sort_label = f"체감 {_describe(sort_description)} / {metric_label} / {'내림차순' if sorting.order == 'desc' else '오름차순'} (동점: {sort_label})"
        md = engine.applied_filters_markdown(constraints,echo,sort_label,limit,len(products),len(matched),params.get("user_request"),params.get("interpretation_notes") or [])
        lines = md.splitlines()
        insert = next(i for i,line in enumerate(lines) if line.startswith("- 정렬:"))
        extra = []
        for c,d in zip(conditions,condition_descriptions):
            extra.append(f"- 체감 조건({c.condition_id}): {_describe(d['selected_labels'])} / 원래 상태: {_state_names(d['selected_labels'])} / 감성: {', '.join(c.sentiments) if c.sentiments else '제한 없음'} / 최소 일치 리뷰 {c.min_matching_reviews}개 / 상반 상태: {d['contrary_states']} / 상반 상한: {c.max_contrary_reviews if c.max_contrary_reviews is not None else '제한 없음'}")
        if sorting and sorting.desired_state_ids:
            extra.append(f"- 체감 정렬의 원래 상태: {_state_names(sort_description)}")
        for topic in topics:
            labels = repo.labels(topic.attribute,topic.desired_state_ids)
            extra.append(f"- 설명용 근거({topic.topic_id}): {_describe(labels)} / 원래 상태: {_state_names(labels)}")
        extra.append("- 체감 조건은 명시적 리뷰 보고의 존재를 검색합니다. 제품 특성의 보장이 아닙니다. 상반 근거는 지정한 상태에 대해서만 평가합니다.")
        lines[insert:insert] = extra
        result = {"applied_filters_markdown":"\n".join(lines),"applied_filters":echo,
                  "applied_conditions":condition_items,
                  "total_products":len(products),"matched_count":len(matched),"products":shown,
                  "table_markdown":engine.markdown_table([raw[p["product_id"]] for p in shown]),**repo.versions(),
                  "applied_experience_conditions":[c.model_dump(mode="json") for c in conditions],
                  "applied_experience_sort":sorting.model_dump(mode="json") if sorting else None,
                  "condition_results":evaluations,"experience_condition_descriptions":condition_descriptions,
                  "excluded_due_to_experience_conditions":failed,
                  "excluded_due_to_insufficient_evidence":unknown,
                  "answer_requirements":ANSWER_REQUIREMENTS}
        if sorting:
            result["table_markdown"] += "\n\n| 상품 | 체감 점수 | 분자 / 분모 | 평가 상태 |\n|---|---:|---:|---|\n" + "\n".join(
                f"| {p['name']} | {p['experience_ranking']['score']:.6f} | {p['experience_ranking']['numerator']} / {p['experience_ranking']['denominator']} | 평가됨 |" if p['experience_ranking']['score'] is not None else f"| {p['name']} | 미평가 | 0 / 0 | 근거 없음 |" for p in shown)
        if "excluded_due_to_unknown_data" in objective:
            result["excluded_due_to_unknown_data"] = objective["excluded_due_to_unknown_data"]
        result["per_condition_matches"] = objective.get("per_condition_matches",[]) + [
            {"condition_id":c.condition_id,"matches_alone":sum(r[i]["state"]=="PASS" for r in evaluations.values()),
             "unknown_alone":sum(r[i]["state"]=="UNKNOWN" for r in evaluations.values())} for i,c in enumerate(conditions)]
        if not matched:
            result["message"] = "조건에 부합하는 상품이 없습니다."
            # 체감 조건을 유지한 상품만 객관 조건 완화의 대상으로 삼는다.
            allowed = [p for p in products if all(r["state"]=="PASS" for r in evaluations[p["product_id"]])]
            suggestions = engine.relaxation_suggestions(allowed,constraints,ev)
            suggestions.pop("near_misses",None)
            result["relaxation_suggestions"] = suggestions
            result["relaxation_suggestions"]["experience_conditions"] = [
                {"condition_id":c.condition_id,"action":"사용자 확인 후에만 상태 허용 범위 또는 최소 리뷰 수를 변경하세요.",
                 "condition_results":{pid:evaluations[pid][i] for pid in all_ids if all(v is True for v in ev[pid].values())}}
                for i,c in enumerate(conditions)]
            result["near_misses"] = [
                {**engine._brief(p),"failed_conditions":[c.label for c in constraints if ev[p["product_id"]][c.key] is False] + [r["condition_id"] for r in evaluations[p["product_id"]] if r["state"]=="FAIL"],
                 "unverifiable_conditions":[c.label for c in constraints if ev[p["product_id"]][c.key] is None] + [r["condition_id"] for r in evaluations[p["product_id"]] if r["state"]=="UNKNOWN"],
                 "label":"조건 불충족 근접 후보 (일치 결과 아님)"}
                for p in sorted(products,key=lambda p:(sum(v is not True for v in ev[p["product_id"]].values())+sum(r["state"]!="PASS" for r in evaluations[p["product_id"]]),p["product_id"]))[:3]]
        return ProductSearchResult.model_validate(result)


def guide() -> dict:
    result = engine.guide()
    result["applied_conditions"] = []
    result["condition_display_contract"] = {"field":"applied_conditions","keys":["type","condition","value"],"types":["객관","체감","판매"],"display":"condition:value","response_prefix":"답변 첫머리에 applied_conditions JSON을 그대로 제시합니다. 색상은 UI에서 type에 따라 지정합니다."}
    try:
        with Repository() as repo:
            result["experience_catalog"] = {**repo.versions(),"counts":repo.manifest["counts"],"available":True}
    except ValueError as e:
        result["experience_catalog"] = {"available":False,"reason":str(e)}
    result["experience_tools"] = {"find_review_attributes":"원래/정규화 속성 문자 검색과 전체 목록 탐색",
                                  "list_review_states":"선택 속성의 원래 상태 ID·근거 확인",
                                  "get_review_evidence":"리뷰 원문과 일치·상반·기타 상태 근거 확인"}
    result["experience_contract"] = {"workflow":["find_review_attributes","list_review_states","search_products","get_review_evidence"],
                                    "selector":"속성 선택 절은 OR, 절 안의 군집 ID와 원래 속성 ID는 AND",
                                    "filter":"조건 사이 AND. 최소 명시적 일치 리뷰 1개. 상반 리뷰는 기본적으로 제외하지 않음",
                                    "states":"원래 상태 ID를 선택. 없음과 거의 없음은 별개. NULL은 없음이 아님",
                                    "metrics":["positive_wilson_lower","state_wilson_lower"],
                                    "denominator":"선택 속성의 전체 관련 리뷰 수. 동일 리뷰는 한 표",
                                    "contrary_policy":"contrary_state_ids 미지정 시 상반 수는 null(미평가). 기타 상태 분포를 확인",
                                    "claim_scope":"review_report"}
    return result


def _extend_topics(result, tokens, topics):
    topics = _models(topics,EvidenceTopic)
    if not topics:
        return result
    _unique(topics,"topic_id")
    with Repository() as repo:
        ids = repo.product_ids(tokens)
        data = _topic_data(repo,topics)
        result.update(repo.versions())
        result["experience_topics"] = {pid:[topic_summary(repo,t,rows[pid],pid) for t,rows in data] for pid in ids}
        result["applied_conditions"] += [display.evidence_topic(repo.labels(t.attribute,t.desired_state_ids)) for t in topics]
    return result


def compare(products, experience_topics=None):
    return _extend_topics(engine.compare(products),products,experience_topics)


def details(product, experience_topics=None):
    return _extend_topics(engine.details(product),[product],experience_topics)
