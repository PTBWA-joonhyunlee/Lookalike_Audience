# lookalike/pipeline/athena_queries.py
#
# Athena를 직접 실행하는 파이프라인(run_seed_scenario1.py)이 쓰는 쿼리 렌더러. 테이블을 영구
# 생성하지 않는다 — seed 목록은 S3 폴더 위의 임시 외부 테이블(메타데이터만, 끝나면 DROP)로
# 읽고, 결과는 UNLOAD로 S3에 내보낸 뒤 내려받는다.
#
# segment 피처 로직은 queries/templates/segment_features.sql(taxonomy 단일 출처)을 읽어 쓴다.
#   - seed segment: 앞에 seed_ad_id CTE를 붙인다
#   - candidate: 기존 seed 제외 조인 없이 기간별로 한 번만 뽑는다(제외는 스코어링 직전 로컬에서)
#   - 실행 SQL에서 `--` 줄 주석을 제거한다(CLAUDE.md: 줄바꿈이 사라지면 뒤 SQL을 삼킴)

import re
from typing import List, Tuple

from .paths import PROJECT_ROOT, SCRATCH_DB

SEGMENT_TEMPLATE_PATH = PROJECT_ROOT / "lookalike" / "queries" / "templates" / "segment_features.sql"
BLOCK_COMMENT_END = "   ============================================================ */"

# propfit.skp가 propfit.ptbwa_skp로 바뀌었다(2026-09-28 Athena TABLE_NOT_FOUND로 확인).
SKP_TABLE = '"propfit"."ptbwa_skp"'

# "수십 % 이상이면 같은 공간" 휴리스틱을 10%로 수치화했다 - je(60.2%)/피엘라벤 크로스워크
# (0.0% -> 61.0%)/madid(67.6%) 모두 이 임계값으로 명확히 갈린다(eda/docs/id_space_crosswalk.md).
DIRECT_THRESHOLD = 0.10
CROSSWALK_THRESHOLD = 0.10

UUID_RE = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"

# segment 쿼리 최종 SELECT 컬럼(02_seed_segment_*.sql 출력과 동일) — UNLOAD TEXTFILE은 헤더가
# 없어서 다운로드 후 로컬에서 이 헤더를 붙인다.
SEGMENT_COLUMNS = [
    "device_ifa", "gender_score", "age_bracket_ids", "residence_ids",
    "product_interest_ids", "content_interest_ids", "etc_segment_ids",
]
SEGMENT_HEADER = ",".join(SEGMENT_COLUMNS)

# ---------- 기간 조건 ----------

def _render_period_predicate(period_start: str, period_end: str) -> str:
    """abi_bid_log_flatten의 year/month/day 파티션 필터 WHERE 조각. 같은 연도 안에서만, 시작은 그 달
    1일만 지원한다(일 단위 상한은 마지막 달에만 건다) - 위반하면 ValueError."""
    sy, sm, sd_ = period_start.split("-")
    ey, em, ed_ = period_end.split("-")
    if sy != ey:
        raise ValueError(f"기간이 연도를 걸칩니다({period_start}~{period_end}) - 연도별로 나눠 --period를 반복하세요")
    if sd_ != "01":
        raise ValueError(f"period_start({period_start})가 그 달의 1일이 아닙니다 - 시작월 전체(1일부터)만 지원합니다")
    months = [f"{m:02d}" for m in range(int(sm), int(em) + 1)]
    if len(months) == 1:
        month_clause = f"b.month = '{months[0]}' AND CAST(b.day AS INTEGER) <= {int(ed_)}"
    else:
        full_list = ", ".join(f"'{m}'" for m in months[:-1])
        month_clause = f"(b.month IN ({full_list}) OR (b.month = '{months[-1]}' AND CAST(b.day AS INTEGER) <= {int(ed_)}))"
    return f"b.year = '{sy}'\n      AND {month_clause}"


def _render_multi_period_predicate(periods: list) -> str:
    if len(periods) == 1:
        return _render_period_predicate(*periods[0])
    parts = [f"(\n      {_render_period_predicate(a, b)}\n      )" for a, b in periods]
    return "(" + "\n      OR ".join(parts) + ")"


# ---------- id space 판정 ----------

def decide_id_space(seed_total: int, matches_bidlog: int, matches_skp_direct: int, matches_skb_ad_id: int,
                     matches_skb_platform_ad_id: int, matches_skb_uuid: int) -> dict:
    def rate(n):
        return n / seed_total if seed_total else 0.0

    rates = {
        "bidlog": rate(matches_bidlog),
        "skp_direct": rate(matches_skp_direct),
        "skb_ad_id": rate(matches_skb_ad_id),
        "skb_platform_ad_id": rate(matches_skb_platform_ad_id),
        "skb_uuid": rate(matches_skb_uuid),
    }
    direct_rate = max(rates["skp_direct"], rates["skb_ad_id"])
    crosswalk_candidates = {"platform_ad_id": rates["skb_platform_ad_id"], "uuid": rates["skb_uuid"]}
    best_crosswalk_col = max(crosswalk_candidates, key=crosswalk_candidates.get)
    crosswalk_rate = crosswalk_candidates[best_crosswalk_col]

    direct_ok = direct_rate >= DIRECT_THRESHOLD
    crosswalk_ok = crosswalk_rate >= CROSSWALK_THRESHOLD
    if direct_ok and not crosswalk_ok:
        mode = "direct"
    elif crosswalk_ok and not direct_ok:
        mode = "crosswalk"
    else:
        mode = "ambiguous"  # 둘 다 임계값 미만이거나 둘 다 이상 -> 사람이 봐야 함

    return {
        "mode": mode, "rates": rates,
        "crosswalk_col": best_crosswalk_col, "crosswalk_rate": crosswalk_rate, "direct_rate": direct_rate,
        "seed_total": seed_total,
    }


_LINE_COMMENT_RE = re.compile(r"[ \t]*--[^\n]*")


def strip_line_comments(sql: str) -> str:
    return _LINE_COMMENT_RE.sub("", sql)


def fq(table: str) -> str:
    """Trino(SELECT)용 DB.table 표기 — 큰따옴표. (DDL은 Hive 문법이라 백틱 — render_temp_table_ddl)"""
    return f'"{SCRATCH_DB}"."{table}"'


# ---------- 임시 외부 테이블 ----------

def render_temp_table_ddl(table: str, s3_location: str, has_header: bool) -> str:
    tblprops = "\nTBLPROPERTIES ('skip.header.line.count' = '1')" if has_header else ""
    return (
        f"CREATE EXTERNAL TABLE `{SCRATCH_DB}`.`{table}` (device_ifa string)\n"
        "ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'\n"
        "WITH SERDEPROPERTIES ('separatorChar' = ',')\n"
        f"LOCATION '{s3_location}'{tblprops}"
    )


def render_drop_temp_table(table: str) -> str:
    return f"DROP TABLE IF EXISTS `{SCRATCH_DB}`.`{table}`"


# ---------- id space check ----------

def render_id_space_check(temp_table: str, period_months=("04", "05")) -> str:
    """seed의 device_ifa가 어떤 ID 공간(raw GAID 직접 / ptbwa_skb 크로스워크)에 있는지 6개 숫자로 센다.
    매칭 건수만으로 "같은 공간"이라 추론하지 않고 직접/크로스워크 후보를 모두 카운트한다
    (eda/docs/id_space_crosswalk.md). bidlog 매칭은 학습 기간(기본 2026년 04~05월)으로 본다."""
    months_sql = ", ".join(f"'{m}'" for m in period_months)
    return f"""WITH seed AS (
    SELECT DISTINCT device_ifa
    FROM {fq(temp_table)}
    WHERE device_ifa IS NOT NULL
      AND regexp_like(device_ifa, '{UUID_RE}')
),
bidlog AS (
    SELECT DISTINCT device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten"
    WHERE year = '2026' AND month IN ({months_sql})
      AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
),
skp_direct AS (
    SELECT DISTINCT ad_id AS device_ifa
    FROM {SKP_TABLE}
    WHERE NOT (year = '2024' AND month = '12' AND day = '31')
      AND CAST(id_type AS VARCHAR) = '2'
      AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
),
skb_ad_id AS (
    SELECT DISTINCT CAST(ad_id AS VARCHAR) AS v FROM "propfit"."ptbwa_skb" WHERE ad_id IS NOT NULL
),
skb_platform_ad_id AS (
    SELECT DISTINCT CAST(platform_ad_id AS VARCHAR) AS v FROM "propfit"."ptbwa_skb" WHERE platform_ad_id IS NOT NULL
),
skb_uuid AS (
    SELECT DISTINCT CAST(uuid AS VARCHAR) AS v FROM "propfit"."ptbwa_skb" WHERE uuid IS NOT NULL
)
SELECT
    (SELECT count(*) FROM seed) AS seed_total,
    (SELECT count(*) FROM seed sd JOIN bidlog b ON sd.device_ifa = b.device_ifa) AS seed_matches_bidlog,
    (SELECT count(*) FROM seed sd JOIN skp_direct s ON sd.device_ifa = s.device_ifa) AS seed_matches_skp_direct,
    (SELECT count(*) FROM seed sd JOIN skb_ad_id k ON sd.device_ifa = k.v) AS seed_matches_skb_ad_id,
    (SELECT count(*) FROM seed sd JOIN skb_platform_ad_id k ON sd.device_ifa = k.v) AS seed_matches_skb_platform_ad_id,
    (SELECT count(*) FROM seed sd JOIN skb_uuid k ON sd.device_ifa = k.v) AS seed_matches_skb_uuid"""


# ---------- seed segment ----------

def render_seed_ad_id_cte(temp_table: str, mode: str, crosswalk_col: str = None) -> str:
    if mode == "direct":
        return (
            "seed_ad_id AS (\n"
            "    SELECT DISTINCT device_ifa\n"
            f"    FROM {fq(temp_table)}\n"
            "    WHERE device_ifa IS NOT NULL\n"
            f"      AND regexp_like(device_ifa, '{UUID_RE}')\n"
            ")"
        )
    if mode == "crosswalk":
        if crosswalk_col not in ("platform_ad_id", "uuid"):
            raise ValueError(f"crosswalk_col 값이 올바르지 않습니다: {crosswalk_col!r}")
        return (
            "seed_ad_id AS (\n"
            "    SELECT DISTINCT k.ad_id AS device_ifa\n"
            f"    FROM (SELECT DISTINCT device_ifa FROM {fq(temp_table)}\n"
            "          WHERE device_ifa IS NOT NULL\n"
            f"            AND regexp_like(device_ifa, '{UUID_RE}')) sd\n"
            "    JOIN (SELECT DISTINCT\n"
            f"              CAST({crosswalk_col} AS VARCHAR) AS {crosswalk_col},\n"
            "              CAST(ad_id AS VARCHAR) AS ad_id\n"
            '          FROM "propfit"."ptbwa_skb"\n'
            f"          WHERE {crosswalk_col} IS NOT NULL AND ad_id IS NOT NULL) k\n"
            f"      ON sd.device_ifa = k.{crosswalk_col}\n"
            ")"
        )
    raise ValueError(f"mode는 direct/crosswalk만 가능합니다: {mode!r}")


def _template_body() -> str:
    text = SEGMENT_TEMPLATE_PATH.read_text(encoding="utf-8")
    return text.split(BLOCK_COMMENT_END, 1)[1].lstrip("\n")


def render_seed_segment_query(temp_table: str, mode: str, crosswalk_col: str = None) -> str:
    body = _template_body()
    n_join = body.count("JOIN seed_ad_id sd")
    n_with = body.count("WITH segments_latest AS (")
    if n_join != 1 or n_with != 1:
        raise RuntimeError(
            f"segment_features.sql 템플릿 구조가 바뀌었습니다(JOIN {n_join}개, WITH {n_with}개) - 렌더러를 확인하세요"
        )
    cte = render_seed_ad_id_cte(temp_table, mode, crosswalk_col)
    body = body.replace("WITH segments_latest AS (", f"WITH {cte},\nsegments_latest AS (", 1)
    return strip_line_comments(body).strip().rstrip(";")


# ---------- candidate segment ----------

def render_candidate_segment_query(periods: List[Tuple[str, str]]) -> str:
    """candidate 정의(bid log 기간 + region=KR/OS=Android + skp 세그먼트 보유 + 컴플라이언스) +
    세그먼트 피처 추출. 기존 seed 제외는 하지 않는다 — 후보를 기간별 캐시로 재사용하고,
    seed 제외는 스코어링 직전에 로컬에서 한다(그래서 이 결과는 seed가 늘어도 그대로 유효하다)."""
    period_where = _render_multi_period_predicate(list(periods))
    candidates_block = f"""WITH segments_latest AS (
    SELECT
        ad_id AS device_ifa,
        CAST(segments AS VARCHAR) AS segments,
        ROW_NUMBER() OVER (
            PARTITION BY ad_id
            ORDER BY year DESC, month DESC, day DESC
        ) AS rn
    FROM {SKP_TABLE}
    WHERE NOT (year = '2024' AND month = '12' AND day = '31')
      AND CAST(id_type AS VARCHAR) = '2'
      AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
),
segments_latest1 AS (
    SELECT device_ifa, segments FROM segments_latest WHERE rn = 1
),
candidates AS (
    SELECT DISTINCT b.device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten" b
    JOIN segments_latest1 seg ON b.device_ifa = seg.device_ifa
    WHERE {period_where}
      AND b.device_ifa IS NOT NULL AND trim(CAST(b.device_ifa AS VARCHAR)) <> ''
      AND regexp_like(CAST(b.device_ifa AS VARCHAR), '{UUID_RE}')
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
      AND CAST(b.device_geo_region AS VARCHAR) LIKE 'KR%'
      AND regexp_like(CAST(b.device_osv AS VARCHAR), '^[0-9]+$')
),
seg1 AS (
    SELECT c.device_ifa, split(sl.segments, ';') AS segment_ids
    FROM candidates c
    JOIN segments_latest1 sl ON c.device_ifa = sl.device_ifa
),
"""
    body = _template_body()
    matched_onward = body[body.index("matched AS ("):]
    return strip_line_comments(candidates_block + matched_onward).strip().rstrip(";")


# ---------- UNLOAD ----------

def render_unload(select_sql: str, s3_prefix: str) -> str:
    """UNLOAD는 대상 prefix가 비어 있어야 한다(athena.delete_prefix로 먼저 비움). TEXTFILE은
    헤더가 없고 값에 쉼표/따옴표가 없는 컬럼(UUID, 숫자, ';' 구분 ID)만 내보내므로 안전하다."""
    if not s3_prefix.endswith("/"):
        raise ValueError("s3_prefix는 /로 끝나야 합니다")
    return (
        f"UNLOAD (\n{select_sql}\n)\n"
        f"TO '{s3_prefix}'\n"
        "WITH (format = 'TEXTFILE', field_delimiter = ',', compression = 'GZIP')"
    )
