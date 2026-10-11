"""모니터 검색 엔진 (MCP 와 무관한 순수 로직, 표준 라이브러리만 사용).

- products.sqlite 를 읽기 전용으로 연다.
- 모든 필터는 3값 논리(True / False / None=문서 미기재로 판정 불가)로 평가한다.
- 결과 0건일 때 어떤 조건을 제거/완화하면 되는지 계산한다.
"""
from __future__ import annotations

import itertools
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from policy import ANSWER_REQUIREMENTS, POLICY_MD
from condition_display import item, objective_conditions, objective_sort

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("MONITOR_DB_PATH", ROOT / "products.sqlite"))
DOC_DIR = Path(os.environ.get("MONITOR_DOC_DIR", ROOT))

PRICE_BASIS_LABEL = {
    "list_price": "출시가",
    "lowest_listed": "가격비교 최저가",
    "street_range_mid": "실구매 범위 중간값",
}
AVAILABILITY_LABEL = {
    "on_sale": "판매중",
    "temporarily_out_of_stock": "일시 품절",
    "discontinued": "단종",
    None: "판매상태 미기재",
}
AVAILABILITY_KEYS = ["on_sale", "temporarily_out_of_stock", "discontinued", "unknown"]

RESOLUTION_PIXELS = {"FHD": 1920 * 1080, "QHD": 2560 * 1440, "UWQHD": 3440 * 1440, "UHD": 3840 * 2160}
RESOLUTION_DESC = {"FHD": "1920x1080", "QHD": "2560x1440", "UWQHD": "3440x1440", "UHD": "3840x2160"}
RESOLUTION_ALIASES = {
    "FHD": "FHD", "풀HD": "FHD", "FULLHD": "FHD", "1080P": "FHD", "1920X1080": "FHD",
    "QHD": "QHD", "WQHD": "QHD", "1440P": "QHD", "2K": "QHD", "2560X1440": "QHD",
    "UWQHD": "UWQHD", "ULTRAWQHD": "UWQHD", "울트라WQHD": "UWQHD", "3440X1440": "UWQHD",
    "UHD": "UHD", "4K": "UHD", "4KUHD": "UHD", "2160P": "UHD", "3840X2160": "UHD",
}
BRAND_ALIASES = {
    "samsung": "Samsung", "삼성": "Samsung", "삼성전자": "Samsung", "오디세이": "Samsung", "odyssey": "Samsung",
    "lg": "LG", "엘지": "LG", "lg전자": "LG",
    "benq": "BenQ", "벤큐": "BenQ",
    "aoc": "AOC", "에이오씨": "AOC", "알파스캔": "AOC",
}
SYNC_KEYS = {
    "freesync": "AMD FreeSync 계열(FreeSync 또는 FreeSync Premium)",
    "freesync_premium": "AMD FreeSync Premium",
    "gsync_compatible": "NVIDIA G-SYNC Compatible (문서에 명시된 경우만)",
}
SYNC_ALIASES = {
    "freesync": "freesync", "프리싱크": "freesync", "amdfreesync": "freesync",
    "freesync_premium": "freesync_premium", "freesyncpremium": "freesync_premium", "프리싱크프리미엄": "freesync_premium",
    "gsync_compatible": "gsync_compatible", "gsync": "gsync_compatible", "g-sync": "gsync_compatible",
    "지싱크": "gsync_compatible", "gsynccompatible": "gsync_compatible",
}

# sort_by -> (한글명, 값 getter, 기본 방향, asc 표현, desc 표현)
SORTS: dict[str, tuple[str, Callable[[dict], Any], str, str, str]] = {
    "price": ("대표가", lambda p: p["price_krw"], "asc", "가격 낮은 순", "가격 높은 순"),
    "refresh_rate": ("최대 주사율", lambda p: p["refresh_hz"], "desc", "주사율 낮은 순", "주사율 높은 순"),
    "resolution": ("해상도(화소 수)", lambda p: p["resolution_w"] * p["resolution_h"], "desc", "해상도 낮은 순", "해상도 높은 순"),
    "size": ("화면 크기", lambda p: p["size_inch"], "desc", "크기 작은 순", "크기 큰 순"),
    "weight": ("무게(스탠드 포함)", lambda p: p["weight_kg"], "asc", "가벼운 순", "무거운 순"),
    "ppi": ("화소 밀도(PPI)", lambda p: p["ppi"], "desc", "PPI 낮은 순", "PPI 높은 순"),
    "brightness": ("표준 밝기", lambda p: p["brightness_nits"], "desc", "밝기 낮은 순", "밝기 높은 순"),
    "contrast": ("정적 명암비", lambda p: p["contrast_ratio"], "desc", "명암비 낮은 순", "명암비 높은 순"),
    "release": ("출시 시점", lambda p: p["release_ym"], "desc", "오래된 순", "최신 순"),
    "response_gtg": ("GTG 응답속도", lambda p: p["response_gtg_ms"], "asc", "GTG 응답속도 빠른 순", "GTG 응답속도 느린 순"),
    "response_mprt": ("MPRT 응답속도", lambda p: p["response_mprt_ms"], "asc", "MPRT 응답속도 빠른 순", "MPRT 응답속도 느린 순"),
    "price_per_megapixel": ("메가픽셀당 가격", lambda p: p["price_per_megapixel"], "asc", "메가픽셀당 가격 낮은 순", "메가픽셀당 가격 높은 순"),
    "power": ("최대 소비전력", lambda p: p["power_max_w"], "asc", "소비전력 낮은 순", "소비전력 높은 순"),
}


# ---------------------------------------------------------------------------
# 데이터 로딩
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_data() -> tuple[list[dict], dict[str, dict]]:
    """(상품 리스트, 기능 카탈로그) 를 읽는다. 상품마다 features={key: 'yes'|'no'} 가 붙는다."""
    con = _connect()
    try:
        products = [dict(r) for r in con.execute("SELECT * FROM products ORDER BY product_id")]
        catalog = {r["feature_key"]: dict(r) for r in con.execute("SELECT * FROM feature_catalog")}
        feats: dict[str, dict[str, dict]] = {}
        for r in con.execute("SELECT * FROM product_features"):
            feats.setdefault(r["product_id"], {})[r["feature_key"]] = {"status": r["status"], "evidence": r["evidence"]}
    finally:
        con.close()
    for p in products:
        p["features"] = feats.get(p["product_id"], {})
        mp = p["resolution_w"] * p["resolution_h"] / 1_000_000
        p["megapixels"] = round(mp, 2)
        p["price_per_megapixel"] = round(p["price_krw"] / mp) if p["price_krw"] else None
        p["release_year"] = int(p["release_ym"][:4]) if p["release_ym"] else None
        p["caveat_list"] = p["caveats"].split(" | ") if p["caveats"] else []
    return products, catalog


def _compact(s: str) -> str:
    return re.sub(r"[\s_\-]+", "", s).lower()


def resolve_product(token: str, products: list[dict]) -> dict:
    """product_id / 모델명 / 이름 일부로 상품 하나를 찾는다."""
    t = _compact(str(token))
    if not t:
        raise ValueError("빈 상품 식별자입니다.")
    for p in products:
        if t in (_compact(p["product_id"]), _compact(p["model"])):
            return p
    hits = [p for p in products if t in _compact(p["product_id"]) or t in _compact(p["model"]) or t in _compact(p["name"])]
    if len(hits) == 1:
        return hits[0]
    ids = ", ".join(f"{p['product_id']}({p['model']})" for p in (hits or products))
    if not hits:
        raise ValueError(f"'{token}'에 해당하는 상품이 없습니다. 등록된 상품: {ids}")
    raise ValueError(f"'{token}'이 여러 상품과 일치합니다: {ids}. product_id 로 지정하세요.")


# ---------------------------------------------------------------------------
# 표기 헬퍼
# ---------------------------------------------------------------------------

def fnum(x: Any) -> str:
    if x is None:
        return "문서 미기재"
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    if isinstance(x, int):
        return f"{x:,}"
    return str(round(x, 2)) if isinstance(x, float) else str(x)


def won(x: Optional[int]) -> str:
    return "문서 미기재" if x is None else f"{x:,}원"


def response_text(p: dict) -> str:
    parts = []
    if p["response_gtg_ms"] is not None:
        parts.append(f"{fnum(p['response_gtg_ms'])}ms (GTG)")
    if p["response_mprt_ms"] is not None:
        parts.append(f"{fnum(p['response_mprt_ms'])}ms (MPRT)")
    return " / ".join(parts) or "문서 미기재"


def price_text(p: dict) -> str:
    if p["price_krw"] is None:
        return "문서 미기재"
    s = f"{won(p['price_krw'])} ({PRICE_BASIS_LABEL.get(p['price_basis'], '기준 미기재')})"
    if p["price_low_krw"] and p["price_high_krw"] and p["price_low_krw"] != p["price_high_krw"]:
        s += f", 문서상 범위 {won(p['price_low_krw'])}~{won(p['price_high_krw'])}"
    return s


def ports_text(p: dict) -> str:
    out = [f"HDMI {p['hdmi_count']}개(최고 v{fnum(p['hdmi_version'])})"]
    out.append(f"DP {p['dp_count']}개" + (f"(v{fnum(p['dp_version'])})" if p["dp_count"] and p["dp_version"] else ""))
    if p["has_dsub"]:
        out.append("D-Sub")
    if p["has_headphone_out"]:
        out.append("헤드폰 출력")
    return ", ".join(out)


def size_text(p: dict) -> str:
    return f"{p['size_class']}형 (실측 {p['size_inch']}인치)"


def panel_text(p: dict) -> str:
    s = f"{p['panel_type']} {'평면' if p['panel_shape'] == 'flat' else '커브드'}"
    if p["curvature_r"]:
        s += f" {p['curvature_r']}R"
    return s


def fmt_label_num(x: Any) -> str:
    return fnum(x)


# ---------------------------------------------------------------------------
# 제약(필터) 모델
# ---------------------------------------------------------------------------

@dataclass
class Constraint:
    key: str                              # 파라미터 이름
    label: str                            # 사람이 읽는 조건 문장
    field_label: str                      # 조건이 걸린 속성 이름
    kind: str                             # max | min | set | flag
    test: Callable[[dict], Optional[bool]]  # True 충족 / False 불충족 / None 판정 불가
    getter: Optional[Callable[[dict], Any]] = None
    value: Any = None
    unit: str = ""
    unknown_reason: str = "문서 미기재"


def _num_constraint(key, field_label, getter, value, op, unit="", unknown_reason=None, shown=None) -> Constraint:
    shown_value = shown if shown is not None else fnum(value)
    word = "이하" if op == "max" else "이상"

    def test(p, g=getter):
        v = g(p)
        if v is None:
            return None
        return v <= value if op == "max" else v >= value

    return Constraint(
        key=key, label=f"{field_label}: {shown_value}{unit} {word}", field_label=field_label, kind=op, test=test,
        getter=getter, value=value, unit=unit, unknown_reason=unknown_reason or f"{field_label} 문서 미기재",
    )


def _set_constraint(key, field_label, getter, values, display=lambda v: str(v), none_token=None, unit="") -> Constraint:
    vs = set(values)

    def test(p):
        v = getter(p)
        if v is None:
            v = none_token
            if v is None:
                return None
        return v in vs

    shown = " / ".join(display(v) for v in values)
    return Constraint(key=key, label=f"{field_label}: {shown}", field_label=field_label, kind="set", test=test,
                      getter=lambda p: (getter(p) if getter(p) is not None else none_token), value=list(values),
                      unit=unit, unknown_reason=f"{field_label} 문서 미기재")


def _flag_constraint(key, label, test, field_label=None, unknown_reason="문서 미기재") -> Constraint:
    return Constraint(key=key, label=label, field_label=field_label or label, kind="flag", test=test,
                      unknown_reason=unknown_reason)


def _as_list(x) -> list:
    if x is None:
        return []
    return list(x) if isinstance(x, (list, tuple, set)) else [x]


def build_constraints(params: dict, catalog: dict[str, dict]) -> tuple[list[Constraint], dict]:
    """파라미터를 검증·정규화하고 Constraint 리스트와 echo 용 정규화 파라미터를 돌려준다."""
    cs: list[Constraint] = []
    echo: dict[str, Any] = {}
    g = params.get

    # --- 브랜드 / 이름
    if g("brands"):
        vals = []
        for b in _as_list(g("brands")):
            c = BRAND_ALIASES.get(_compact(str(b)))
            if not c:
                raise ValueError(f"알 수 없는 브랜드 '{b}'. 가능한 값: AOC, BenQ, LG, Samsung (삼성/오디세이 포함)")
            if c not in vals:
                vals.append(c)
        echo["brands"] = vals
        cs.append(_set_constraint("brands", "브랜드", lambda p: p["brand"], vals))
    if g("name_contains"):
        q = _compact(str(g("name_contains")))
        echo["name_contains"] = g("name_contains")
        cs.append(_flag_constraint(
            "name_contains", f"이름/모델 포함: '{g('name_contains')}'",
            lambda p: q in _compact(p["name"] + p["model"] + (p["series"] or "") + p["brand"]), field_label="이름/모델"))

    # --- 크기 (판매 분류 기준)
    if g("size_classes"):
        vals = sorted({int(v) for v in _as_list(g("size_classes"))})
        echo["size_classes"] = vals
        cs.append(_set_constraint("size_classes", "화면 크기(판매 분류)", lambda p: p["size_class"], vals, display=lambda v: f"{v}형"))
    if g("min_size_class") is not None:
        echo["min_size_class"] = g("min_size_class")
        cs.append(_num_constraint("min_size_class", "화면 크기(판매 분류)", lambda p: p["size_class"], g("min_size_class"), "min", unit="형"))
    if g("max_size_class") is not None:
        echo["max_size_class"] = g("max_size_class")
        cs.append(_num_constraint("max_size_class", "화면 크기(판매 분류)", lambda p: p["size_class"], g("max_size_class"), "max", unit="형"))

    # --- 가격 / 판매상태
    if g("min_price_krw") is not None:
        echo["min_price_krw"] = g("min_price_krw")
        cs.append(_num_constraint("min_price_krw", "대표가", lambda p: p["price_krw"], g("min_price_krw"), "min", unit="원"))
    if g("max_price_krw") is not None:
        echo["max_price_krw"] = g("max_price_krw")
        cs.append(_num_constraint("max_price_krw", "대표가", lambda p: p["price_krw"], g("max_price_krw"), "max", unit="원"))
    if g("availability"):
        vals = []
        for a in _as_list(g("availability")):
            a = str(a).strip().lower()
            if a not in AVAILABILITY_KEYS:
                raise ValueError(f"알 수 없는 availability '{a}'. 가능한 값: {AVAILABILITY_KEYS}")
            vals.append(a)
        echo["availability"] = vals
        cs.append(_set_constraint("availability", "판매상태", lambda p: p["availability"], vals,
                                  display=lambda v: "판매상태 미기재" if v == "unknown" else AVAILABILITY_LABEL[v], none_token="unknown"))

    # --- 해상도 / 비율 / 패널
    def norm_res(v):
        r = RESOLUTION_ALIASES.get(re.sub(r"[\s\-_]", "", str(v)).upper())
        if not r:
            raise ValueError(f"알 수 없는 해상도 '{v}'. 가능한 값: {', '.join(f'{k}({d})' for k, d in RESOLUTION_DESC.items())}")
        return r

    if g("resolution_classes"):
        vals = []
        for v in _as_list(g("resolution_classes")):
            r = norm_res(v)
            if r not in vals:
                vals.append(r)
        echo["resolution_classes"] = vals
        cs.append(_set_constraint("resolution_classes", "해상도", lambda p: p["resolution_class"], vals,
                                  display=lambda v: f"{v}({RESOLUTION_DESC[v]})"))
    if g("min_resolution"):
        r = norm_res(g("min_resolution"))
        echo["min_resolution"] = r
        cs.append(_num_constraint("min_resolution", "해상도(화소 수)", lambda p: p["resolution_w"] * p["resolution_h"], RESOLUTION_PIXELS[r], "min",
                                  shown=f"{r}({RESOLUTION_DESC[r]})", unit=""))
    if g("aspect_ratio"):
        a = str(g("aspect_ratio")).strip().lower()
        a = {"울트라와이드": "21:9", "ultrawide": "21:9", "와이드": "16:9", "wide": "16:9"}.get(a, a)
        if a not in ("16:9", "21:9"):
            raise ValueError("aspect_ratio 는 '16:9' 또는 '21:9'(울트라와이드)만 가능합니다.")
        echo["aspect_ratio"] = a
        cs.append(_set_constraint("aspect_ratio", "화면 비율", lambda p: p["aspect_ratio"], [a]))
    if g("panel_types"):
        vals = []
        for v in _as_list(g("panel_types")):
            v = str(v).strip().upper()
            if v not in vals:
                vals.append(v)
        echo["panel_types"] = vals
        cs.append(_set_constraint("panel_types", "패널 종류", lambda p: p["panel_type"], vals))
    if g("panel_shape"):
        s = {"flat": "flat", "평면": "flat", "curved": "curved", "커브드": "curved", "곡면": "curved"}.get(str(g("panel_shape")).strip().lower())
        if not s:
            raise ValueError("panel_shape 는 'flat'(평면) 또는 'curved'(커브드)만 가능합니다.")
        echo["panel_shape"] = s
        cs.append(_set_constraint("panel_shape", "패널 형태", lambda p: p["panel_shape"], [s], display=lambda v: "평면" if v == "flat" else "커브드"))

    # --- 성능
    if g("min_refresh_hz") is not None:
        echo["min_refresh_hz"] = g("min_refresh_hz")
        cs.append(_num_constraint("min_refresh_hz", "최대 주사율", lambda p: p["refresh_hz"], g("min_refresh_hz"), "min", unit="Hz"))
    if g("max_response_ms") is not None:
        method = (str(g("response_method") or "")).strip().upper()
        if method not in ("GTG", "MPRT"):
            raise ValueError("max_response_ms 를 쓰려면 response_method 를 'GTG' 또는 'MPRT'로 반드시 지정해야 합니다. (두 방식은 서로 비교할 수 없음)")
        echo["max_response_ms"] = g("max_response_ms")
        echo["response_method"] = method
        col = "response_gtg_ms" if method == "GTG" else "response_mprt_ms"
        other = "MPRT" if method == "GTG" else "GTG"
        cs.append(_num_constraint("max_response_ms", f"응답속도({method} 기준)", lambda p, c=col: p[c], g("max_response_ms"), "max", unit="ms",
                                  unknown_reason=f"{method} 기준 응답속도가 문서에 없음({other} 기준만 기재되어 있어 비교 불가)"))
    elif g("response_method"):
        raise ValueError("response_method 는 max_response_ms 와 함께만 사용합니다.")
    if g("min_brightness_nits") is not None:
        echo["min_brightness_nits"] = g("min_brightness_nits")
        cs.append(_num_constraint("min_brightness_nits", "표준 밝기", lambda p: p["brightness_nits"], g("min_brightness_nits"), "min", unit="nits(cd/㎡)"))
    if g("min_contrast_ratio") is not None:
        echo["min_contrast_ratio"] = g("min_contrast_ratio")
        cs.append(_num_constraint("min_contrast_ratio", "정적 명암비", lambda p: p["contrast_ratio"], g("min_contrast_ratio"), "min", unit=":1"))
    if g("min_color_bit_depth") is not None:
        echo["min_color_bit_depth"] = g("min_color_bit_depth")
        cs.append(_num_constraint("min_color_bit_depth", "색 심도", lambda p: p["color_bit_depth"], g("min_color_bit_depth"), "min", unit="bit"))
    if g("sync"):
        key = SYNC_ALIASES.get(_compact(str(g("sync"))).replace("-", ""))
        if not key:
            raise ValueError(f"알 수 없는 sync '{g('sync')}'. 가능한 값: {list(SYNC_KEYS)}")
        echo["sync"] = key

        def sync_test(p, k=key):
            tier = p["freesync_tier"]
            if k == "freesync":
                return None if tier is None else True
            if k == "freesync_premium":
                return None if tier is None else tier == "FreeSync Premium"
            st = p["features"].get("gsync_compatible")
            return True if st and st["status"] == "yes" else None

        cs.append(_flag_constraint("sync", f"가변 주사율: {SYNC_KEYS[key]}", sync_test, field_label="가변 주사율",
                                   unknown_reason="가변 주사율 기술이 문서에 기재되지 않음"))

    # --- 단자
    if g("min_hdmi_count") is not None:
        echo["min_hdmi_count"] = g("min_hdmi_count")
        cs.append(_num_constraint("min_hdmi_count", "HDMI 포트 수", lambda p: p["hdmi_count"], g("min_hdmi_count"), "min", unit="개"))
    if g("min_hdmi_version") is not None:
        echo["min_hdmi_version"] = g("min_hdmi_version")
        cs.append(_num_constraint("min_hdmi_version", "HDMI 최고 버전", lambda p: p["hdmi_version"], g("min_hdmi_version"), "min", unit=""))
    if g("min_dp_count") is not None:
        echo["min_dp_count"] = g("min_dp_count")
        cs.append(_num_constraint("min_dp_count", "DisplayPort 포트 수", lambda p: p["dp_count"], g("min_dp_count"), "min", unit="개"))
    if g("require_dsub"):
        echo["require_dsub"] = True
        cs.append(_flag_constraint("require_dsub", "D-Sub(VGA) 단자 있음", lambda p: bool(p["has_dsub"])))
    if g("require_headphone_out"):
        echo["require_headphone_out"] = True
        cs.append(_flag_constraint("require_headphone_out", "헤드폰 출력 단자 있음", lambda p: bool(p["has_headphone_out"])))

    # --- 물리
    for key, label, col, unit in [
        ("max_weight_kg", "무게(스탠드 포함)", "weight_kg", "kg"),
        ("max_width_mm", "폭(스탠드 포함)", "width_mm", "mm"),
        ("max_height_mm", "높이(스탠드 포함, 최저 높이)", "height_mm", "mm"),
        ("max_depth_mm", "깊이(스탠드 포함)", "depth_mm", "mm"),
        ("max_power_w", "최대 소비전력", "power_max_w", "W"),
    ]:
        if g(key) is not None:
            echo[key] = g(key)
            cs.append(_num_constraint(key, label, lambda p, c=col: p[c], g(key), "max", unit=unit))
    if g("vesa_mm"):
        vals = sorted({int(v) for v in _as_list(g("vesa_mm"))})
        echo["vesa_mm"] = vals
        cs.append(_set_constraint("vesa_mm", "VESA 규격", lambda p: p["vesa_mm"], vals, display=lambda v: f"{v}x{v}mm"))
    if g("min_release_year") is not None:
        echo["min_release_year"] = g("min_release_year")
        cs.append(_num_constraint("min_release_year", "출시 연도", lambda p: p["release_year"], g("min_release_year"), "min", unit="년"))
    if g("max_release_year") is not None:
        echo["max_release_year"] = g("max_release_year")
        cs.append(_num_constraint("max_release_year", "출시 연도", lambda p: p["release_year"], g("max_release_year"), "max", unit="년"))

    # --- 기능 태그
    if g("require_features"):
        by_label = {_compact(v["label_ko"]): k for k, v in catalog.items()}
        vals = []
        for f in _as_list(g("require_features")):
            k = str(f).strip()
            if k not in catalog:
                k = by_label.get(_compact(k))
            if not k:
                raise ValueError(f"알 수 없는 기능 '{f}'. 가능한 값: {', '.join(catalog)}")
            if k not in vals:
                vals.append(k)
        echo["require_features"] = vals
        for k in vals:
            def ftest(p, kk=k):
                st = p["features"].get(kk)
                return None if st is None else st["status"] == "yes"
            cs.append(_flag_constraint(f"feature:{k}", f"기능 필요: {catalog[k]['label_ko']}", ftest, field_label=catalog[k]["label_ko"],
                                       unknown_reason=f"'{catalog[k]['label_ko']}' 지원 여부가 문서에 기재되지 않음"))
    return cs, echo


# ---------------------------------------------------------------------------
# 평가 / 완화 제안
# ---------------------------------------------------------------------------

def evaluate(products: list[dict], cs: list[Constraint]) -> dict[str, dict[str, Optional[bool]]]:
    return {p["product_id"]: {c.key: c.test(p) for c in cs} for p in products}


def _brief(p: dict) -> dict:
    return {"product_id": p["product_id"], "name": p["name"]}


def _show_value(c: Constraint, v: Any) -> str:
    if c.key == "min_resolution":
        return next((k for k, px in RESOLUTION_PIXELS.items() if px == v), fnum(v)) + f"({RESOLUTION_DESC.get(next((k for k, px in RESOLUTION_PIXELS.items() if px == v), ''), '')})"
    return f"{fnum(v)}{c.unit}"


def _relax_one(c: Constraint, pool: list[dict]) -> Optional[dict]:
    """pool: c 를 제외한 나머지 조건을 모두 통과한 상품들. c 를 어떻게 바꾸면 pool 에서 몇 개가 풀리는지."""
    fails = [p for p in pool if c.test(p) is False]
    unknown = [p for p in pool if c.test(p) is None]
    if not fails and not unknown:
        return None
    sug: dict[str, Any] = {"condition": c.label, "constraint": c.key}
    steps = []
    if c.kind in ("max", "min") and fails:
        vals = sorted({c.getter(p) for p in fails}, reverse=(c.kind == "min"))
        for v in vals[:3]:
            ok = [p for p in fails if (c.getter(p) <= v if c.kind == "max" else c.getter(p) >= v)]
            word = "상한" if c.kind == "max" else "하한"
            steps.append({"action": f"{c.field_label} {word} 완화: {_show_value(c, c.value)} -> {_show_value(c, v)}",
                          "new_value": v, "unlocks": [_brief(p) for p in ok]})
        sug["type"] = "relax_threshold"
    elif c.kind == "set" and fails:
        by_val: dict[Any, list[dict]] = {}
        for p in fails:
            by_val.setdefault(c.getter(p), []).append(p)
        for v, ps in sorted(by_val.items(), key=lambda kv: -len(kv[1]))[:4]:
            steps.append({"action": f"{c.field_label}에 '{v}' 추가 허용", "new_value": v, "unlocks": [_brief(p) for p in ps]})
        sug["type"] = "add_allowed_value"
    elif fails:
        steps.append({"action": f"'{c.label}' 조건 제거", "unlocks": [_brief(p) for p in fails]})
        sug["type"] = "remove_condition"
    sug["steps"] = steps
    if unknown:
        sug["unverifiable_products"] = [{**_brief(p), "reason": c.unknown_reason} for p in unknown]
    sug["unlock_count"] = max((len(s["unlocks"]) for s in steps), default=0)
    return sug


def relaxation_suggestions(products: list[dict], cs: list[Constraint], ev: dict) -> dict:
    """0건일 때 호출. 단일 조건 완화 → 두 조건 동시 제거 → 근접 후보 순으로 계산한다."""
    out: dict[str, Any] = {}
    singles = []
    for c in cs:
        pool = [p for p in products if all(ev[p["product_id"]][o.key] is True for o in cs if o is not c)]
        s = _relax_one(c, pool)
        if s:
            singles.append(s)
    singles.sort(key=lambda s: (-s["unlock_count"], -len(s.get("unverifiable_products", []))))
    out["single_condition"] = singles
    if not any(s["unlock_count"] for s in singles) and len(cs) >= 2:
        pairs = []
        for c1, c2 in itertools.combinations(cs, 2):
            rest = [o for o in cs if o is not c1 and o is not c2]
            ok = [p for p in products if all(ev[p["product_id"]][o.key] is True for o in rest)
                  and ev[p["product_id"]][c1.key] is not None and ev[p["product_id"]][c2.key] is not None]
            if ok:
                pairs.append({"remove_both": [c1.label, c2.label], "unlocks": [_brief(p) for p in ok]})
        pairs.sort(key=lambda x: -len(x["unlocks"]))
        out["two_conditions"] = pairs[:4]
    # 근접 후보
    near = []
    for p in products:
        e = ev[p["product_id"]]
        failed = [c.label for c in cs if e[c.key] is False]
        unk = [f"{c.label} ({c.unknown_reason})" for c in cs if e[c.key] is None]
        near.append((len(failed), len(unk), p, failed, unk))
    near.sort(key=lambda t: (t[0], t[1], t[2]["price_krw"] or 0))
    out["near_misses"] = [{**_brief(p), "failed_conditions": failed, "unverifiable_conditions": unk, "label": "조건 불충족 근접 후보 (일치 결과 아님)"}
                          for nf, nu, p, failed, unk in near[:3]]
    return out


# ---------------------------------------------------------------------------
# 결과 표현
# ---------------------------------------------------------------------------

def present_product(p: dict, catalog: dict[str, dict], detail: bool = False) -> dict:
    yes = [catalog[k]["label_ko"] for k, v in p["features"].items() if v["status"] == "yes"]
    no = [catalog[k]["label_ko"] for k, v in p["features"].items() if v["status"] == "no"]
    unknown = [v["label_ko"] for k, v in catalog.items() if k not in p["features"]]
    d = {
        "product_id": p["product_id"],
        "name": p["name"],
        "brand": p["brand"],
        "model": p["model"],
        "price_krw": p["price_krw"],
        "price_text": price_text(p),
        "price_basis": p["price_basis"],
        "price_basis_label": PRICE_BASIS_LABEL.get(p["price_basis"]),
        "availability": p["availability"] or "unknown",
        "availability_label": AVAILABILITY_LABEL[p["availability"]],
        "release_ym": p["release_ym"],
        "size": size_text(p),
        "resolution": f"{p['resolution_w']}x{p['resolution_h']} ({p['resolution_class']})",
        "aspect_ratio": p["aspect_ratio"],
        "ppi": p["ppi"],
        "panel": panel_text(p),
        "refresh_hz": p["refresh_hz"],
        "response_time": response_text(p),
        "brightness_nits": p["brightness_nits"],
        "contrast_ratio": f"{p['contrast_ratio']:,}:1" if p["contrast_ratio"] else None,
        "color_bit_depth": p["color_bit_depth"],
        "adaptive_sync": p["freesync_tier"] or "문서 미기재",
        "ports": ports_text(p),
        "dimensions_mm_with_stand": f"{fnum(p['width_mm'])}(W) x {fnum(p['height_mm'])}(H) x {fnum(p['depth_mm'])}(D)",
        "weight_kg": p["weight_kg"],
        "vesa": f"{p['vesa_mm']}x{p['vesa_mm']}mm" if p["vesa_mm"] else None,
        "power_max_w": p["power_max_w"],
        "price_per_megapixel_krw": p["price_per_megapixel"],
        "features_supported": yes,
        "features_not_supported": no,
        "features_unconfirmed_count": len(unknown),
        "caveats": p["caveat_list"],
        "detail_document": p["source_file"],
    }
    if detail:
        d["features_unconfirmed"] = unknown
        d["feature_evidence"] = {catalog[k]["label_ko"]: f"{v['status']}: {v['evidence']}" for k, v in p["features"].items()}
        d["price_range_krw"] = [p["price_low_krw"], p["price_high_krw"]]
        d["series"] = p["series"]
    return d


def markdown_table(products: list[dict]) -> str:
    head = "| 상품 | 대표가 (기준) | 판매상태 | 크기 | 해상도 | 패널 | 주사율 | 응답속도 | 무게 |\n|---|---|---|---|---|---|---|---|---|"
    rows = []
    for p in products:
        rows.append("| {} | {} ({}) | {} | {}형 | {} | {} | {}Hz | {} | {}kg |".format(
            f"{p['brand']} {p['model']}", won(p["price_krw"]), PRICE_BASIS_LABEL.get(p["price_basis"], "기준 미기재"),
            AVAILABILITY_LABEL[p["availability"]], p["size_class"], p["resolution_class"], panel_text(p),
            p["refresh_hz"], response_text(p), fnum(p["weight_kg"])))
    return head + "\n" + "\n".join(rows) if rows else "(일치 상품 없음)"


def applied_filters_markdown(cs: list[Constraint], echo: dict, sort_label: str, limit: int, total: int, matched: int,
                             user_request: Optional[str], notes: list[str]) -> str:
    L = ["### 적용된 검색 조건"]
    if user_request:
        L.append(f"- 사용자 요청: \"{user_request}\"")
    if notes:
        for n in notes:
            L.append(f"- 해석 가정: {n}")
    if cs:
        for c in cs:
            L.append(f"- {c.label}")
    else:
        L.append("- 필터 없음 (등록된 전체 상품)")
    L.append(f"- 정렬: {sort_label}" + (f" / 상위 {limit}개 표시" if limit < matched else ""))
    L.append(f"- 검색 범위: 등록된 {total}개 상품 (외부 검색 없음, 가격은 문서 기록 스냅샷)")
    L.append(f"- **결과: {total}개 중 {matched}개 일치**")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def search(params: dict) -> dict:
    products, catalog = load_data()
    cs, echo = build_constraints(params, catalog)

    sort_key = params.get("sort_by") or "price"
    if sort_key not in SORTS:
        raise ValueError(f"알 수 없는 sort_by '{sort_key}'. 가능한 값: {list(SORTS)}")
    name, getter, default_order, asc_t, desc_t = SORTS[sort_key]
    order = (params.get("sort_order") or default_order).lower()
    if order not in ("asc", "desc"):
        raise ValueError("sort_order 는 'asc' 또는 'desc' 입니다.")
    limit = int(params.get("limit") or len(products))
    limit = max(1, min(limit, len(products)))
    echo["sort_by"], echo["sort_order"] = sort_key, order
    sort_label = asc_t if order == "asc" else desc_t

    ev = evaluate(products, cs)
    matched = [p for p in products if all(v is True for v in ev[p["product_id"]].values())]

    def sort_val(p):
        v = getter(p)
        return (v is None, (v if order == "asc" else _neg(v)) if v is not None else 0)

    matched.sort(key=sort_val)
    shown = matched[:limit]

    unknown_only = []
    for p in products:
        e = ev[p["product_id"]]
        if e and not any(v is False for v in e.values()) and any(v is None for v in e.values()):
            unknown_only.append({**_brief(p), "unverifiable_conditions": [f"{c.label} -> {c.unknown_reason}" for c in cs if e[c.key] is None]})

    notes = [str(n) for n in _as_list(params.get("interpretation_notes"))]
    user_request = params.get("user_request")
    if notes:
        echo["interpretation_notes"] = notes
    if user_request:
        echo["user_request"] = user_request

    per_cond = []
    if len(cs) > 1:
        for c in cs:
            per_cond.append({"condition": c.label, "matches_alone": sum(1 for p in products if c.test(p) is True),
                             "unknown_alone": sum(1 for p in products if c.test(p) is None)})

    res: dict[str, Any] = {
        "applied_conditions": objective_conditions(cs) + [objective_sort(sort_key, sort_label)],
        "applied_filters_markdown": applied_filters_markdown(cs, echo, sort_label, limit, len(products), len(matched), user_request, notes),
        "applied_filters": echo,
        "total_products": len(products),
        "matched_count": len(matched),
        "products": [present_product(p, catalog) for p in shown],
        "table_markdown": markdown_table(shown),
    }
    if per_cond:
        res["per_condition_matches"] = per_cond
    if unknown_only:
        res["excluded_due_to_unknown_data"] = unknown_only
    if not matched:
        res["message"] = "조건에 부합하는 상품이 없습니다."
        res["relaxation_suggestions"] = relaxation_suggestions(products, cs, ev)
        res["near_misses"] = res["relaxation_suggestions"].pop("near_misses")
    res["answer_requirements"] = ANSWER_REQUIREMENTS
    return res


def _neg(v):
    if isinstance(v, (int, float)):
        return -v
    # 문자열(release_ym 등): 사전 역순
    return tuple(-ord(ch) for ch in v)


def _feature_cell(p: dict, key: str) -> str:
    st = p["features"].get(key)
    return "문서 미기재" if st is None else ("지원" if st["status"] == "yes" else "미지원")


def compare(tokens: list[str]) -> dict:
    products, catalog = load_data()
    if len(tokens) < 2:
        raise ValueError("비교하려면 상품을 2개 이상 지정하세요.")
    chosen: list[dict] = []
    for t in tokens:
        p = resolve_product(t, products)
        if p not in chosen:
            chosen.append(p)
    if len(chosen) < 2:
        raise ValueError("서로 다른 상품 2개 이상이 필요합니다.")

    rows: list[tuple[str, str, Callable[[dict], str]]] = [
        ("가격", "대표가", lambda p: won(p["price_krw"])),
        ("가격", "가격 기준", lambda p: PRICE_BASIS_LABEL.get(p["price_basis"], "기준 미기재")),
        ("가격", "문서상 가격 범위", lambda p: f"{won(p['price_low_krw'])}~{won(p['price_high_krw'])}" if p["price_low_krw"] != p["price_high_krw"] else "단일 값"),
        ("가격", "판매상태", lambda p: AVAILABILITY_LABEL[p["availability"]]),
        ("가격", "출시", lambda p: p["release_ym"] or "문서 미기재"),
        ("화면", "크기", size_text),
        ("화면", "해상도", lambda p: f"{p['resolution_w']}x{p['resolution_h']} ({p['resolution_class']})"),
        ("화면", "PPI", lambda p: fnum(p["ppi"])),
        ("화면", "비율", lambda p: p["aspect_ratio"]),
        ("화면", "패널", panel_text),
        ("성능", "최대 주사율", lambda p: f"{p['refresh_hz']}Hz"),
        ("성능", "응답속도", response_text),
        ("성능", "표준 밝기", lambda p: f"{fnum(p['brightness_nits'])}nits"),
        ("성능", "정적 명암비", lambda p: f"{fnum(p['contrast_ratio'])}:1"),
        ("성능", "색 심도", lambda p: f"{p['color_bit_depth']}bit"),
        ("성능", "가변 주사율", lambda p: p["freesync_tier"] or "문서 미기재"),
        ("단자", "HDMI/DP/기타", ports_text),
        ("물리", "치수(스탠드 포함) mm", lambda p: f"{fnum(p['width_mm'])} x {fnum(p['height_mm'])} x {fnum(p['depth_mm'])}"),
        ("물리", "무게(스탠드 포함)", lambda p: f"{fnum(p['weight_kg'])}kg"),
        ("물리", "VESA", lambda p: f"{p['vesa_mm']}x{p['vesa_mm']}mm"),
        ("물리", "최대 소비전력", lambda p: f"{fnum(p['power_max_w'])}W" if p["power_max_w"] is not None else "문서 미기재"),
    ]
    for k, v in catalog.items():
        rows.append(("기능", v["label_ko"], lambda p, kk=k: _feature_cell(p, kk)))

    table = []
    for group, label, fn in rows:
        vals = [fn(p) for p in chosen]
        table.append({"group": group, "attribute": label, "values": dict(zip([p["product_id"] for p in chosen], vals)),
                      "differs": len(set(vals)) > 1})

    heads = ["항목"] + [f"{p['brand']} {p['model']}" for p in chosen]
    md = ["| " + " | ".join(heads) + " |", "|" + "---|" * len(heads)]
    for r in table:
        mark = "" if r["differs"] else " (동일)"
        md.append(f"| {r['group']} / {r['attribute']}{mark} | " + " | ".join(r["values"].values()) + " |")

    def ext(label, fn, best):
        vals = [(fn(p), p) for p in chosen if fn(p) is not None]
        if not vals:
            return None
        target = (min if best == "min" else max)(v for v, _ in vals)
        win = [f"{p['brand']} {p['model']}" for v, p in vals if v == target]
        return {"attribute": label, "best": ("가장 낮음" if best == "min" else "가장 높음"), "value": target, "products": win}

    extremes = [e for e in [
        ext("대표가(기준이 서로 다를 수 있음)", lambda p: p["price_krw"], "min"),
        ext("최대 주사율(Hz)", lambda p: p["refresh_hz"], "max"),
        ext("해상도(화소 수)", lambda p: p["resolution_w"] * p["resolution_h"], "max"),
        ext("PPI", lambda p: p["ppi"], "max"),
        ext("무게(kg)", lambda p: p["weight_kg"], "min"),
        ext("표준 밝기(nits)", lambda p: p["brightness_nits"], "max"),
        ext("정적 명암비", lambda p: p["contrast_ratio"], "max"),
    ] if e]

    notes = []
    if len({PRICE_BASIS_LABEL.get(p["price_basis"]) for p in chosen}) > 1:
        notes.append("대표가의 기준(출시가/최저가/실구매 범위 중간값)이 상품마다 달라 가격 차이를 정확한 시세 차이로 해석하면 안 됩니다.")
    methods = {m for p in chosen for m, c in (("GTG", p["response_gtg_ms"]), ("MPRT", p["response_mprt_ms"])) if c is not None}
    if len(methods) > 1:
        notes.append("응답속도는 GTG와 MPRT가 섞여 있습니다. 서로 직접 비교하지 마세요.")
    for p in chosen:
        for cv in p["caveat_list"]:
            notes.append(f"[{p['brand']} {p['model']}] {cv}")
        if p["availability"] in ("discontinued", "temporarily_out_of_stock"):
            notes.append(f"[{p['brand']} {p['model']}] 판매상태: {AVAILABILITY_LABEL[p['availability']]}")

    applied = ["### 비교 대상", *[f"- {p['name']} (`{p['product_id']}`)" for p in chosen],
               f"- 비교 범위: 등록된 {len(products)}개 상품 데이터(외부 검색 없음, 가격은 문서 기록 스냅샷)"]
    return {
        "applied_filters_markdown": "\n".join(applied),
        "applied_conditions": [item("객관", "비교 대상", ", ".join(p["model"] for p in chosen))],
        "compared_products": [_brief(p) for p in chosen],
        "comparison_table": table,
        "table_markdown": "\n".join(md),
        "extremes_among_compared": extremes,
        "notes": notes,
        "answer_requirements": ANSWER_REQUIREMENTS,
    }


def details(token: str) -> dict:
    products, catalog = load_data()
    p = resolve_product(token, products)
    from demo.tools import document
    doc = document(p)
    return {
        "applied_filters_markdown": f"### 조회 대상\n- {p['name']} (`{p['product_id']}`)\n- 조회 범위: 등록 데이터(DB 핵심 속성 + 상세 문서)",
        "applied_conditions": [item("객관", "조회 대상", p["model"])],
        "product": present_product(p, catalog, detail=True),
        "detail_document_path": p["source_file"],
        "detail_document_markdown": doc,
        "answer_requirements": ANSWER_REQUIREMENTS,
    }


def search_docs(query: str, product_tokens: Optional[list[str]] = None, max_results: int = 15) -> dict:
    products, _ = load_data()
    targets = [resolve_product(t, products) for t in product_tokens] if product_tokens else products
    terms = [t for t in re.split(r"[\s,]+", query.strip()) if t]
    if not terms:
        raise ValueError("검색어(query)가 비었습니다.")
    low_terms = [t.lower() for t in terms]
    hits = []
    for p in targets:
        from demo.tools import document
        section = ""
        for i, line in enumerate(document(p).splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                section = s.lstrip("# ").strip()
            elif line and not line.startswith((" ", "-", "<", ">")) and s.endswith(":"):
                section = s.rstrip(":")
            ll = line.lower()
            score = sum(1 for t in low_terms if t in ll)
            if score:
                hits.append({"score": score, "product_id": p["product_id"], "name": p["name"], "line_no": i, "section": section, "text": s})
    if hits:
        best = max(h["score"] for h in hits)
        hits = [h for h in hits if h["score"] == best]
    hits = hits[:max_results]
    scope = ", ".join(p["model"] for p in targets)
    return {
        "applied_filters_markdown": f"### 적용된 문서 검색 조건\n- 검색어: {' / '.join(terms)} (줄 단위, 가장 많은 검색어가 포함된 줄만)\n- 대상 문서: {scope}\n"
                                    f"- **결과: {len(hits)}건**" + ("" if hits else " (문서에 해당 기재 없음)"),
        "applied_conditions": [item("객관", "문서 검색", " / ".join(terms)), item("객관", "대상 상품", scope)],
        "match_count": len(hits),
        "matches": [{k: v for k, v in h.items() if k != "score"} for h in hits],
        "answer_requirements": ANSWER_REQUIREMENTS,
    }


def guide() -> dict:
    products, catalog = load_data()

    def dist(col):
        out: dict[Any, int] = {}
        for p in products:
            out[p[col]] = out.get(p[col], 0) + 1
        return out

    def rng(col):
        vals = [p[col] for p in products if p[col] is not None]
        return {"min": min(vals), "max": max(vals), "unknown_count": len(products) - len(vals)} if vals else None

    return {
        "overview": f"등록된 모니터 {len(products)}개를 객관 속성으로 검색/비교한다. 외부 검색 없음. 서버는 상태가 없으므로 조건은 매 호출마다 전부 전달한다.",
        "tools": {
            "search_products": "조건 검색(필터+정렬). 결과에 적용 조건/제외 사유/완화 제안 포함",
            "compare_products": "상품 2개 이상을 속성별 표로 비교",
            "get_product_details": "상품 1개의 DB 속성 + 상세 문서(markdown) 전문",
            "search_product_docs": "상세 문서에서 키워드 검색(시야각, 보증, 구성품, 색재현율 등 DB에 없는 세부 항목)",
        },
        "products": [{"product_id": p["product_id"], "name": p["name"], "brand": p["brand"], "model": p["model"],
                      "size_class": p["size_class"], "resolution_class": p["resolution_class"], "price_krw": p["price_krw"],
                      "availability": AVAILABILITY_LABEL[p["availability"]]} for p in products],
        "filters": {
            "brands": "AOC | BenQ | LG | Samsung (삼성/오디세이/엘지/벤큐 등 별칭 허용)",
            "name_contains": "이름/모델/시리즈 부분 일치 (예: 'G5')",
            "size_classes / min_size_class / max_size_class": "판매 분류 크기(형). 24/27/32/34. 31.5형과 32형은 모두 32로 분류. 실측 대각선은 size_inch(예: 26.9~27.2)",
            "min_price_krw / max_price_krw": "대표가(원). 기준은 price_basis 로 상품마다 다름",
            "availability": "on_sale | temporarily_out_of_stock | discontinued | unknown(판매상태 미기재)",
            "resolution_classes / min_resolution": "FHD(1920x1080) < QHD(2560x1440) < UWQHD(3440x1440) < UHD(3840x2160). min_resolution 은 화소 수 기준 이상",
            "aspect_ratio": "16:9 | 21:9(울트라와이드)",
            "panel_types / panel_shape": "IPS | VA / flat | curved",
            "min_refresh_hz": "최대 주사율 하한(Hz). 입력 조건은 caveats 참고",
            "max_response_ms + response_method": "응답속도 상한(ms). response_method(GTG|MPRT) 필수. 두 방식은 비교 불가",
            "min_brightness_nits / min_contrast_ratio / min_color_bit_depth": "표준 밝기 / 정적 명암비 / 색 심도(8|10)",
            "sync": "freesync | freesync_premium | gsync_compatible",
            "min_hdmi_count / min_hdmi_version / min_dp_count / require_dsub / require_headphone_out": "단자 조건",
            "max_weight_kg / max_width_mm / max_height_mm / max_depth_mm": "스탠드 포함 물리 크기 상한",
            "vesa_mm": "75 | 100",
            "max_power_w": "최대 소비전력 상한(W). 문서 미기재 상품은 판정 불가로 분리",
            "min_release_year / max_release_year": "출시 연도",
            "require_features": {k: v["label_ko"] for k, v in catalog.items()},
            "sort_by": {k: (f"{v[3]} / {v[4]}", f"기본 {'오름' if v[2] == 'asc' else '내림'}차순") for k, v in SORTS.items()},
            "user_request / interpretation_notes": "사용자 요청 원문 / 모호한 표현을 수치로 해석한 가정(조건 블록에 표시됨)",
        },
        "data_coverage": {
            "brand": dist("brand"), "size_class": dist("size_class"), "resolution_class": dist("resolution_class"),
            "panel_type": dist("panel_type"), "panel_shape": dist("panel_shape"), "aspect_ratio": dist("aspect_ratio"),
            "availability": {AVAILABILITY_LABEL[k]: v for k, v in dist("availability").items()},
            "price_krw": rng("price_krw"), "refresh_hz": rng("refresh_hz"), "weight_kg": rng("weight_kg"),
            "brightness_nits": rng("brightness_nits"), "contrast_ratio": rng("contrast_ratio"), "power_max_w": rng("power_max_w"),
            "feature_documented_counts": {
                v["label_ko"]: {"yes": sum(1 for p in products if p["features"].get(k, {}).get("status") == "yes"),
                                "no": sum(1 for p in products if p["features"].get(k, {}).get("status") == "no"),
                                "문서 미기재": sum(1 for p in products if k not in p["features"])}
                for k, v in catalog.items()},
        },
        "attribute_notes": [
            "NULL/문서 미기재는 미지원이 아니다. 기능은 문서에 명시된 경우에만 지원/미지원이 기록된다.",
            "response_gtg_ms 와 response_mprt_ms 는 별개 컬럼이다. GTG 기준 필터는 MPRT만 기재된 상품을 판정 불가로 분리한다.",
            "price_krw 는 상품마다 기준이 다른 스냅샷(출시가/가격비교 최저가/실구매 범위 중간값)이다.",
            "단자 개수는 문서의 입력 단자 목록을 전수 목록으로 보고 집계했다(목록에 없으면 0).",
            "색재현율, 시야각, 베젤, 스탠드 각도, 구성품, 인증번호, 보증 등 세부 항목은 상세 문서(markdown)에 있다. search_product_docs 사용.",
        ],
        "answer_policy": POLICY_MD,
        "answer_requirements": ANSWER_REQUIREMENTS,
    }
