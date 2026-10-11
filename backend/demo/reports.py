"""Deterministic report calculations over the frozen catalog, with ephemeral input."""
from collections import defaultdict, Counter
from functools import lru_cache
import math
import unicodedata
from . import catalog

LABELS=('positive','negative','mixed','neutral','unknown')
KO=dict(zip(LABELS,('긍정','부정','혼합','중립','미상')))

def collapse(labels):
    known=set(labels)-{'unknown'}
    return next(iter(known)) if len(known)==1 else 'mixed' if known else 'unknown'

def wilson(k,n):
    if not n:return [None,None]
    z=1.959963984540054;p=k/n;d=1+z*z/n
    center=(p+z*z/(2*n))/d
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [center-half,center+half]

def distribution(labels):
    counts={label:labels.count(label) for label in LABELS}; n=len(labels)
    shares={k:v/n if n else None for k,v in counts.items()}
    return {'counts':counts,'shares':shares,'support':n,
            'dominant':max(LABELS,key=lambda k:counts[k]) if n else None,
            'positive_wilson':wilson(counts['positive'],n),'negative_wilson':wilson(counts['negative'],n),
            'entropy':-sum(p*math.log2(p) for p in shares.values() if p)/math.log2(5) if n else None}

@lru_cache(maxsize=1)
def base():
    products={p['product_id']:p for p in catalog.products()}
    units=catalog.rows('SELECT u.*,r.product_id FROM opinion_units u JOIN reviews r ON u.review_idx=r.review_id ORDER BY u.idx')
    def aggregate(fields):
        groups=defaultdict(list)
        for unit in units:groups[(unit['product_id'],*(unit[f] for f in fields))].append(unit)
        result={}
        for key,group in groups.items():
            votes=defaultdict(list)
            for u in group:votes[u['review_idx']].append(u['sentiment'])
            stats=distribution([collapse(v) for v in votes.values()]);first=group[0]
            evidence=[];seen=set()
            for u in group:
                if u['review_idx'] in seen:continue
                label=collapse(votes[u['review_idx']])
                if sum(e['sentiment']==label for e in evidence)>=2:continue
                seen.add(u['review_idx']);evidence.append({'review_id':u['review_idx'],'unit_id':u['idx'],'excerpt':u['excerpt'],'opinion':u['opinion'],'sentiment':label})
            result[key]={'aspect':first['aspect'],'status':first['status'] if len(fields)>1 else None,
                         'aspect_id':first['aspect_cluster_id'],'status_id':first['status_cluster_id'] if len(fields)>1 else None,
                         **stats,'mention_rate':stats['support']/products[key[0]]['review_count'],'evidence':evidence}
        return result
    aspects=aggregate(('aspect_cluster_id',));pairs=aggregate(('aspect_cluster_id','status_cluster_id'))
    aspect_ids=sorted({k[1] for k in aspects});priors={}
    for aid in aspect_ids:
        counts={s:sum(v['counts'][s] for k,v in aspects.items() if k[1]==aid) for s in LABELS[:4]}
        total=sum(counts.values());priors[aid]={s:counts[s]/total if total else .25 for s in counts}
    profiles={}
    for pid in products:
        vector=[];rates=[]
        for aid in aspect_ids:
            row=aspects.get((pid,aid));n=row['support'] if row else 0
            counts=row['counts'] if row else dict.fromkeys(LABELS,0)
            rate=n/products[pid]['review_count'];rates.append(rate)
            scale=math.sqrt(rate)*n/(n+5)*(1-counts['unknown']/n if n else 0)
            known=sum(counts[s] for s in LABELS[:4])
            vector.extend(scale*(counts[s]+5*priors[aid][s])/(known+5) for s in LABELS[:4])
        profiles[pid]=(vector,rates)
    def cosine(a,b):
        denom=math.sqrt(sum(x*x for x in a)*sum(x*x for x in b))
        return sum(x*y for x,y in zip(a,b))/denom if denom else 0
    similarities={}
    for pid,(vector,rates) in profiles.items():
        for other,(vec,rs) in profiles.items():
            denom=sum(max(a,b) for a,b in zip(rates,rs))
            overlap=sum(min(a,b) for a,b in zip(rates,rs))/denom if denom else 0
            similarities[(pid,other)]=cosine(vector,vec)*math.sqrt(overlap)
    return products,aspects,pairs,similarities

def normalize(units):
    result=[]
    for unit in units:
        item=dict(unit);aid=None;sid=None;aspect=None;status=None
        raw=unicodedata.normalize('NFC',unit['raw_aspect'])
        candidates=catalog.rows('SELECT DISTINCT a.aspect_cluster_id,a.aspect FROM aspect_variants v JOIN aspects a USING(aspect_cluster_id) WHERE v.raw_aspect=?',(raw,))
        state='unresolved_aspect'
        if raw=='전반적 상품 경험':state='excluded'
        elif len(candidates)==1:
            aid=candidates[0]['aspect_cluster_id'];aspect=candidates[0]['aspect']
            state='mapped_exact' if unit['raw_status'] is None else 'unresolved_status'
            if unit['raw_status'] is not None:
                candidates=catalog.rows('SELECT DISTINCT s.status_cluster_id,s.status FROM state_variants v JOIN states s USING(status_cluster_id) WHERE v.aspect_cluster_id=? AND v.raw_status=?',(aid,unicodedata.normalize('NFC',unit['raw_status'])))
                if len(candidates)==1:sid=candidates[0]['status_cluster_id'];status=candidates[0]['status'];state='mapped_exact'
        item.update(aspect_id=aid,status_id=sid,aspect=aspect,status=status,mapping_state=state)
        result.append(item)
    return result

def alternatives(pid,conditions,static=False):
    products,_,pairs,similarities=base();results=[]
    if not conditions:return []
    for other in products:
        if other==pid:continue
        matches=[]
        for condition in conditions:
            aid,sid=condition['aspect_id'],condition['status_id']
            target=pairs.get((other,aid,sid))
            positives=[v for (p,a,s),v in pairs.items() if p==other and a==aid and s is not None and s!=sid and v['dominant']=='positive']
            positive=max(positives,key=lambda v:min(1,v['support']/2)*v['positive_wilson'][0],default=None)
            bad=min(1,target['support']/2)*(1 if static else target['negative_wilson'][1]) if target else 0
            good=min(1,positive['support']/2)*positive['positive_wilson'][0] if positive else 0
            matches.append({'aspect':condition['aspect'],'status':condition['status'],'utility':good-bad,
                            'importance':condition.get('importance',1),'undesired':target,'positive_alternative':positive,
                            'has_evidence':bool(target or positive)})
        if not any(m['has_evidence'] for m in matches):continue
        utility=sum(m['utility']*m['importance'] for m in matches)/sum(m['importance'] for m in matches)
        sim=similarities[(pid,other)]
        results.append({'product':products[other],'score':.25*sim+.75*(utility+1)/2,'similarity':sim,'utility':utility,
                        'coverage':sum(m['has_evidence'] for m in matches)/len(matches),'matches':matches})
    return sorted(results,key=lambda r:(-r['score'],-r['utility'],r['product']['name']))[:3]

def generate(pid,review,raw_units):
    products,aspects,pairs,similarities=base()
    if pid not in products:raise ValueError('등록된 상품이 아닙니다.')
    units=normalize(raw_units);groups=defaultdict(list)
    for unit in units:
        if unit['mapping_state']=='mapped_exact':groups[(unit['aspect_id'],unit['status_id'])].append(unit)
    comparisons=[];negative=[]
    for (aid,sid),group in groups.items():
        sentiment=collapse([u['sentiment'] for u in group]);known=pairs.get((pid,aid,sid))
        dominant=known['dominant'] if known else None
        relation='판단 불가'
        if sentiment in ('positive','negative') and dominant in ('positive','negative'):
            relation='일치' if sentiment==dominant else '상충'
        alternative_states=sorted([v for (p,a,s),v in pairs.items() if p==pid and a==aid and s is not None and s!=sid],key=lambda v:-v['support'])[:3]
        first=group[0];comparisons.append({'aspect':first['aspect'],'status':first['status'],'sentiment':sentiment,'relation':relation,'catalog':known,'other_states':alternative_states})
        if sentiment=='negative' and sid:negative.append(first)
    aspect_rows=sorted([v for (p,a),v in aspects.items() if p==pid],key=lambda v:(-v['support'],v['aspect']))
    pair_rows=sorted([v for (p,a,s),v in pairs.items() if p==pid],key=lambda v:(-v['support'],v['aspect']))
    weaknesses=sorted([dict(v,importance=v['counts']['negative']/(v['support']+5)) for v in pair_rows if v['status_id'] and v['support']>=2 and v['counts']['negative']],key=lambda v:-v['importance'])[:10]
    similar=sorted([{'product':p,'similarity':similarities[(pid,other)]} for other,p in products.items() if other!=pid],key=lambda v:-v['similarity'])[:3]
    result={'product':products[pid],'catalog_version':catalog.metadata()['source_data_version'],'review':review,'units':units,
            'comparisons':comparisons,'alternatives':alternatives(pid,negative),
            'overview':{'aspects':aspect_rows[:10],'states':pair_rows[:10],'most_negative':sorted(aspect_rows,key=lambda v:-v['counts']['negative'])[:5],
                        'most_debated':sorted([v for v in aspect_rows if v['counts']['positive'] and v['counts']['negative']],key=lambda v:abs(v['shares']['positive']-v['shares']['negative']))[:5],
                        'similar_products':similar,'weaknesses':weaknesses,'alternatives':alternatives(pid,weaknesses,True)},
            'policy':{'stored':False,'normalization':'exact-match','baseline':'frozen-catalog','reclustering':False}}
    result['markdown']=render(result)
    return result

def render(report):
    def esc(value):return str(value if value is not None else '상태 미기재').replace('|','\\|').replace('\n',' ')
    def pct(x):return '미평가' if x is None else f'{100*x:.1f}%'
    p=report['product'];o=report['overview']
    lines=[f"# {p['name']} 보고서",f"고정 카탈로그 `{report['catalog_version']}` · 기존 리뷰 {p['review_count']:,}개",'입력 리뷰는 저장되거나 기존 통계에 반영되지 않습니다. 새 군집과 유사 표현 후보를 생성하지 않습니다.',
           '## 입력 리뷰', '> '+report['review'].replace('\n','\n> '),'## 추출 및 Exact-match',
           '| 원래 속성 | 원래 상태 | 정규 속성 / 상태 | 감성 | 매핑 |','|---|---|---|---|---|']
    mapping={'mapped_exact':'정확 일치','unresolved_aspect':'속성 미해결','unresolved_status':'상태 미해결','excluded':'비교 제외'}
    for u in report['units']:lines.append(f"| {esc(u['raw_aspect'])} | {esc(u['raw_status'])} | {esc(u['aspect'])} / {esc(u['status'])} | {KO[u['sentiment']]} | {mapping[u['mapping_state']]} |")
    if not report['units']:lines.append('비교할 상품 사용 의견이 추출되지 않았습니다.')
    for u in report['units']:lines.extend([f"- **{esc(u['raw_aspect'])}**: {esc(u['opinion'])}",f"  - 원문: {esc(u['excerpt'])}"])
    lines+=['## 기존 리뷰와의 비교','일치·상충은 같은 속성/상태의 리뷰별 감성 최빈값과 비교합니다. 제품 특성의 참·거짓 판정이 아닙니다.']
    for c in report['comparisons']:
        stats=c['catalog'];lines.append(f"- **{esc(c['aspect'])} / {esc(c['status'])}**: {c['relation']} · 관련 리뷰 {stats['support'] if stats else 0}개")
        if stats:
            lines.append('  - '+', '.join(f'{KO[k]} {v}개' for k,v in stats['counts'].items()))
            for e in stats['evidence'][:3]:lines.append(f"  - 리뷰 #{e['review_id']} · {KO[e['sentiment']]}: {esc(e['excerpt'])}")
        elif c['other_states']:
            lines.append('  - 같은 속성의 다른 상태: '+', '.join(f"{esc(v['status'])} ({v['support']}개)" for v in c['other_states']))
    if not report['comparisons']:lines.append('정확하게 연결된 의견이 없어 통계 비교를 수행하지 않았습니다.')
    def add_alternatives(title,items):
        lines.extend([title,'일부 조건의 근거로 계산한 탐색용 대안입니다. 모든 조건 충족이나 개선 효과를 보장하지 않습니다.'])
        if not items:lines.append('대안 점수를 계산할 비교 근거가 없습니다.')
        for item in items:
            lines.append(f"- **{item['product']['name']}** · 점수 {item['score']:.3f} · 근거 충족 범위 {pct(item['coverage'])}")
            for m in item['matches']:
                pos=m['positive_alternative'];bad=m['undesired']
                lines.append(f"  - {esc(m['aspect'])}: 입력의 부정 상태 관련 리뷰 {bad['support'] if bad else 0}개; 다른 긍정 상태 {esc(pos['status']) if pos else '근거 없음'}")
    add_alternatives('## 입력한 불편에 대한 대안',report['alternatives'])
    lines+=['## 상품의 기존 리뷰 요약','리뷰당 속성 또는 속성/상태별 한 표로 집계합니다. 미상을 포함한 관련 리뷰가 감성 비율의 분모입니다.',
            '| 속성 | 언급 리뷰 | 언급률 | 긍정 | 부정 | 긍정 95% Wilson 구간 |','|---|---:|---:|---:|---:|---|']
    for a in o['aspects']:lines.append(f"| {esc(a['aspect'])} | {a['support']} | {pct(a['mention_rate'])} | {a['counts']['positive']} | {a['counts']['negative']} | {pct(a['positive_wilson'][0])}–{pct(a['positive_wilson'][1])} |")
    lines+=['### 주요 속성 / 상태','| 속성 | 상태 | 관련 리뷰 | 긍정 | 부정 |','|---|---|---:|---:|---:|']
    for a in o['states']:lines.append(f"| {esc(a['aspect'])} | {esc(a['status'])} | {a['support']} | {a['counts']['positive']} | {a['counts']['negative']} |")
    for title,key in [('부정 평가가 많은 속성','most_negative'),('의견이 갈리는 속성','most_debated')]:
        lines+=['### '+title]
        for a in o[key]:lines.append(f"- {a['aspect']}: 긍정 {a['counts']['positive']}개 / 부정 {a['counts']['negative']}개 / 전체 관련 리뷰 {a['support']}개")
        if not o[key]:lines.append('해당 근거가 없습니다.')
    lines+=['### 대표 리뷰 근거']
    for a in o['aspects'][:5]:
        for e in a['evidence'][:2]:lines.append(f"- {a['aspect']} · 리뷰 #{e['review_id']} · {KO[e['sentiment']]}: {esc(e['excerpt'])}")
    lines+=['### 체감 프로필이 비슷한 상품']
    for item in o['similar_products']:lines.append(f"- {item['product']['name']}: {item['similarity']:.3f}")
    add_alternatives('### 기존 리뷰의 약점에 대한 대안',o['alternatives'])
    lines+=['## 해석 범위','- 정확 일치하지 않은 표현은 비교에서 제외합니다. 미해결은 상품이 조건을 충족하지 않는다는 뜻이 아닙니다.',
            '- 유사도는 속성 언급과 감성 분포로 계산합니다. 대안 점수는 유사도 25%와 조건별 효용 75%를 결합합니다.',
            '- 기존 군집의 의미 혼합과 리뷰 표본 편향이 남아 있습니다. 통계는 수집된 리뷰에만 해당합니다.',
            '- 가격·판매 상태는 고정된 과거 자료이며 현재 구매 가능 여부를 보장하지 않습니다.']
    return '\n'.join(lines)
