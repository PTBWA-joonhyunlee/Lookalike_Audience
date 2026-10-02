# seed/pipeline/generate_seed_queries.py
#
# 신규 seed가 들어왔을 때 자동화 범위 밖(Athena SQL) 단계의 쿼리 파일을 템플릿으로
# 생성한다. 이 repo는 Athena 접근 권한이 없어 실행 자체는 여전히 사용자가 콘솔에서 해야
# 하지만(CLAUDE.md "데이터를 얻는 방법" 참고), je seed(2026-08-19)에서 손으로 반복했던
# 01_create_seed_table_*.sql / id_space_check 쿼리 / 02_create_seed_ad_id_table_*.sql
# (직접/크로스워크 판정 포함) / segment 쿼리 / candidate 정의+피처 추출 쿼리를 패턴화했다.
#
# 세 단계로 나뉜다 — ID 공간(크로스워크 필요 여부)은 실제 쿼리 실행 결과를 봐야 판정할 수
# 있어 완전 자동화가 불가능하기 때문이다(eda/docs/id_space_crosswalk.md 참고, 매칭 건수만
# 보고 "같은 공간"이라 추론하면 안 된다는 프로젝트 규칙):
#
#   1) register: seed 테이블 등록 DDL + id space 확인 쿼리를 생성한다.
#      -> 사용자가 둘 다 Athena에서 실행하고, id space 쿼리 결과 한 줄(seed_total부터
#         seed_matches_skb_uuid까지 6개 숫자)을 받아온다.
#   2) resolve: 그 6개 숫자를 --matches로 넘기면 직접/크로스워크를 자동 판정해서
#      02_create_seed_ad_id_table_<name>.sql / segment 쿼리를 생성한다.
#   3) candidate: candidate 정의(bid log 기간 + region/OS + skp 세그먼트 보유 + 기존
#      seed 전부 제외) + 세그먼트 피처 추출을 CREATE TABLE 없이 SELECT 하나로 합쳐 생성한다
#      (2026-08-26부터 — 그 전엔 03_create_candidate_table.sql로 후보 테이블을 만들고
#      04_candidate_segment.sql로 다시 피처를 뽑는 2단계였다. 옛 파일들은 이미 실행된 seed의
#      provenance라 건드리지 않고 그대로 둔다). 제외할 기존 seed 목록은
#      seed/queries/02_create_seed_ad_id_table*.sql을 스캔해 자동으로 구한다 — 새 seed가
#      생길 때마다 이 목록도 자동으로 늘어난다.
#
# 실행(seed/ 안에서 cd 후):
#   ..\.venv\Scripts\python.exe -m pipeline.generate_seed_queries register \
#     --seed-name yeti --s3-path s3://ptbwa-dw/prod/seed_yeti/ --csv-filename yeti_seed.csv --header
#
#   (Athena에서 01_create_seed_table_yeti.sql, eda/queries/id_space_check/NN_seed_yeti_id_space_check.sql 실행 후)
#
#   ..\.venv\Scripts\python.exe -m pipeline.generate_seed_queries resolve \
#     --seed-name yeti --matches 3000 2800 2600 10 5 0
#
#   (Athena에서 02_create_seed_ad_id_table_yeti.sql, segment/02_seed_segment_yeti.sql 실행 후)
#
#   ..\.venv\Scripts\python.exe -m pipeline.generate_seed_queries candidate \
#     --seed-name yeti --period-start 2026-06-01 --period-end 2026-08-24

import argparse
import re
import sys
from pathlib import Path

from scoring.config import PROJECT_ROOT

# Windows 콘솔(cp949)은 이 파일의 안내 메시지에 쓰는 em dash/화살표 등을 인코딩하지 못해
# print()가 UnicodeEncodeError로 죽는다 — 이미 파일 쓰기(write_text, 항상 UTF-8)는 끝난
# 뒤에 죽는 경우가 있어 "실패한 것처럼 보이지만 실제로는 파일이 이미 바뀐" 혼란스러운
# 상태를 만든다. stdout을 UTF-8로 강제해 이 크래시를 막는다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 생성하는 모든 seed_* 테이블/뷰는 이 DB로 한정해서 쓴다 — 콘솔에서 선택된 DB가 달라도
# (2026-09-30 dev-ptbwa-da 선택 상태에서 TABLE_NOT_FOUND 발생) 동작하게 한다. 이미 실행된
# 옛 seed 쿼리(DB 접두사 없음)는 provenance라 그대로 둔다.
SEED_DB = '"prod-ptbwa-dw"'

SEED_QUERIES_DIR = PROJECT_ROOT / "seed" / "queries"
SEGMENT_QUERIES_DIR = SEED_QUERIES_DIR / "segment"
# 2026-08-26 eda/queries 재정리: id space 확인 쿼리는 eda/queries/id_space_check/ 밑에
# 따로 모은다(seed 보유율/분포 확인용 쿼리는 eda/queries/segment_coverage/로 분리) —
# 번호는 이 하위 폴더 안에서만 이어서 매긴다.
EDA_QUERIES_DIR = PROJECT_ROOT / "eda" / "queries" / "id_space_check"

# segment/candidate 쿼리는 세그먼트 taxonomy(gender/age/residence/product/content/etc ID
# 배열)를 그대로 복사해야 해서 손으로 다시 옮기면 사고가 나기 쉽다 — je 버전을 "정본
# 템플릿"으로 읽어서 필요한 부분만 치환한다(je 버전 자체가 이미 taxonomy 변경 없이
# 피엘라벤 원본을 그대로 복사한 것이므로 신뢰 가능).
SEGMENT_TEMPLATE_PATH = SEGMENT_QUERIES_DIR / "02_seed_segment_je.sql"

BLOCK_COMMENT_END = "   ============================================================ */"

# propfit.skp가 propfit.ptbwa_skp로 바뀌었다(2026-09-28 Athena TABLE_NOT_FOUND로 확인).
# je 템플릿(02_seed_segment_je.sql)은 이미 실행된 쿼리의 provenance라 옛 이름 그대로 두고,
# 생성 시점에 치환한다.
LEGACY_SKP_TABLE = '"propfit"."skp"'
SKP_TABLE = '"propfit"."ptbwa_skp"'

# "수십 % 이상이면 같은 공간" 휴리스틱(eda/queries/id_space_check/14_seed_je_id_space_check.sql
# 판정 기준 문서화 그대로)을 10%로 수치화했다 - je(60.2%)/피엘라벤 크로스워크(0.0% -> 61.0%) 둘 다
# 이 임계값으로 명확히 갈린다. 애매하면(둘 다 임계값 미만, 또는 둘 다 이상) 자동 판정을
# 멈추고 사람이 보게 한다.
DIRECT_THRESHOLD = 0.10
CROSSWALK_THRESHOLD = 0.10


def _next_eda_number() -> str:
    existing = sorted(EDA_QUERIES_DIR.glob("[0-9][0-9]_*.sql"))
    nums = [int(p.name[:2]) for p in existing]
    return f"{(max(nums) + 1) if nums else 1:02d}"


# ---------- 1) register ----------

def render_create_seed_table_sql(seed_name: str, s3_path: str, csv_filename: str = None,
                                  has_header: bool = True, id_space_check_filename: str = None) -> str:
    csv_note = f"data/seed/{csv_filename}" if csv_filename else "신규 seed CSV"
    header_note = "헤더가 있어 skip.header.line.count로 건너뛴다" if has_header else "헤더가 없다고 가정한다(있다면 --header 옵션을 켤 것)"
    next_step = f"eda/queries/id_space_check/{id_space_check_filename}" if id_space_check_filename else "eda/queries/id_space_check/의 id_space_check 쿼리"
    tblproperties = "\nTBLPROPERTIES ('skip.header.line.count' = '1');" if has_header else ";"

    return f"""/* ============================================================
   01_create_seed_table_{seed_name}.sql (seed, {seed_name} 신규 seed 등록 —
   pipeline/generate_seed_queries.py가 01_create_seed_table_je.sql을 템플릿 삼아 자동 생성)
   목적: {csv_note}를 Athena에서 조인 가능하게 외부 테이블로 등록한다. {header_note}.

   실행 순서(사용자가 Athena 콘솔/S3 콘솔에서 직접 수행 — 이 repo는 Athena 접근 권한 없음):
     1) {csv_note}를 S3에 업로드한다: {s3_path}
        (경로가 다르면 아래 LOCATION만 그에 맞게 수정)
     2) 아래 DDL을 Athena 콘솔에서 실행한다.
     3) {next_step}로 이 seed의 device_ifa가 어떤 ID 공간에 있는지 확인한다(raw GAID인지,
        크로스워크가 필요한지) — 이 확인 전에는 02_create_seed_ad_id_table_{seed_name}.sql을
        작성/실행하지 말 것. 결과 한 줄을 받으면
        `pipeline.generate_seed_queries resolve --seed-name {seed_name} --matches ...`로
        넘겨 이후 쿼리를 자동 생성한다.

   주의: 이 파일은 CREATE 문 앞에 안내를 붙이는 블록 주석(／＊ ＊／)을 쓴다 — 줄(--) 주석은
   줄바꿈이 사라진 채로 실행되면(콘솔 붙여넣기/스크립트 실행 방식에 따라 발생 가능) 뒤에
   오는 CREATE TABLE 문 전체를 주석으로 삼켜버려 "cannot recognize input near '<EOF>'"
   에러가 난다(2026-07-29 seed_piellaven 등록 때 실제 발생).
   ============================================================ */

CREATE EXTERNAL TABLE seed_{seed_name} (
    device_ifa string
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
    'separatorChar' = ','
)
LOCATION '{s3_path}'{tblproperties}
"""


def render_create_seed_view_sql(seed_name: str, source_table: str, source_column: str,
                                 id_space_check_filename: str = None) -> str:
    next_step = f"eda/queries/id_space_check/{id_space_check_filename}" if id_space_check_filename else "eda/queries/id_space_check/의 id_space_check 쿼리"
    return f"""/* ============================================================
   01_create_seed_table_{seed_name}.sql (seed, {seed_name} 신규 seed 등록 —
   pipeline/generate_seed_queries.py register --source-table로 자동 생성)
   목적: S3 CSV가 아니라 이미 Glue/Athena에 있는 테이블 {source_table}({source_column} 컬럼)을
   이후 쿼리가 기대하는 seed_{seed_name}(device_ifa string) 이름으로 노출하는 뷰를 만든다 —
   데이터를 복사하지 않는다. 이 뷰를 만든 뒤 {next_step}를 실행해 ID 공간을 확인할 것.
   ============================================================ */

CREATE OR REPLACE VIEW {SEED_DB}.seed_{seed_name} AS
SELECT CAST({source_column} AS VARCHAR) AS device_ifa
FROM {source_table};
"""


def render_id_space_check_sql(seed_name: str, num: str, period_months=("04", "05")) -> str:
    months_sql = ", ".join(f"'{m}'" for m in period_months)
    return f"""/* ============================================================
   {num}_seed_{seed_name}_id_space_check.sql (eda, {seed_name} 신규 seed —
   pipeline/generate_seed_queries.py가 28_seed_je_id_space_check.sql을 템플릿 삼아 자동 생성)
   목적: seed_{seed_name}(seed/queries/01_create_seed_table_{seed_name}.sql로 등록)의
   device_ifa가 어떤 ID 공간에 있는지 확인한다 — 매칭 건수만으로 "같은 공간"이라 추론하지
   않고 직접/크로스워크 후보를 모두 카운트해서 비교한다(피엘라벤 seed가 겉보기엔 UUID였지만
   실제로는 ptbwa_skb.platform_ad_id 공간이었던 전례 때문 — eda/docs/id_space_crosswalk.md).

   판정 기준(pipeline generate_seed_queries.py resolve 단계가 이 결과를 받아 자동 적용,
   임계값 {DIRECT_THRESHOLD:.0%}):
   - seed_matches_skp_direct 또는 seed_matches_skb_ad_id 비율이 임계값 이상이면 → 이미 raw
     GAID 공간 → 크로스워크 불필요, 02_create_seed_ad_id_table_{seed_name}.sql은 정규식
     필터 + DISTINCT만 하는 단순 버전.
   - 위는 낮은데 seed_matches_skb_platform_ad_id 또는 seed_matches_skb_uuid 비율이 임계값
     이상이면 → skb를 경유한 크로스워크 필요, 매칭률이 더 높은 컬럼을 사용.
   - 전부 낮거나 애매하면(direct/crosswalk 후보가 둘 다 임계값 미만 또는 둘 다 이상) →
     자동 판정을 멈춘다 — 이 seed의 device_ifa가 이 프로젝트 로그 체계와 무관한 값일 수
     있으니 값 샘플/포맷을 직접 확인할 것.

   기간: bidlog 매칭은 기본으로 pool/seed 학습 기간(2026년 {period_months[0]}~{period_months[1]}월)로
   본다 — 매칭률이 비정상적으로 낮으면 기간을 넓혀 재확인할 것(이 seed 유저가 이 기간에
   활동이 없었을 수 있음).
   ============================================================ */

WITH seed AS (
    SELECT DISTINCT device_ifa
    FROM {SEED_DB}.seed_{seed_name}
    WHERE device_ifa IS NOT NULL
      AND regexp_like(device_ifa, '^[0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{12}}$')
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
    WHERE NOT (year = '2024' AND month = '12' AND day = '31')   /* 깨진 .tmp 파티션 제외 */
      AND CAST(id_type AS VARCHAR) = '2'
      AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
),
skb_ad_id AS (
    SELECT DISTINCT CAST(ad_id AS VARCHAR) AS v
    FROM "propfit"."ptbwa_skb"
    WHERE ad_id IS NOT NULL
),
skb_platform_ad_id AS (
    SELECT DISTINCT CAST(platform_ad_id AS VARCHAR) AS v
    FROM "propfit"."ptbwa_skb"
    WHERE platform_ad_id IS NOT NULL
),
skb_uuid AS (
    SELECT DISTINCT CAST(uuid AS VARCHAR) AS v
    FROM "propfit"."ptbwa_skb"
    WHERE uuid IS NOT NULL
)
SELECT
    (SELECT count(*) FROM seed) AS seed_total,
    (SELECT count(*) FROM seed sd JOIN bidlog b ON sd.device_ifa = b.device_ifa) AS seed_matches_bidlog,
    (SELECT count(*) FROM seed sd JOIN skp_direct s ON sd.device_ifa = s.device_ifa) AS seed_matches_skp_direct,
    (SELECT count(*) FROM seed sd JOIN skb_ad_id k ON sd.device_ifa = k.v) AS seed_matches_skb_ad_id,
    (SELECT count(*) FROM seed sd JOIN skb_platform_ad_id k ON sd.device_ifa = k.v) AS seed_matches_skb_platform_ad_id,
    (SELECT count(*) FROM seed sd JOIN skb_uuid k ON sd.device_ifa = k.v) AS seed_matches_skb_uuid;
"""


def cmd_register(seed_name: str, s3_path: str, csv_filename: str = None, has_header: bool = True,
                  period_months=("04", "05"), source_table: str = None, source_column: str = "device_ifa") -> None:
    num = _next_eda_number()
    id_space_filename = f"{num}_seed_{seed_name}_id_space_check.sql"

    seed_table_path = SEED_QUERIES_DIR / f"01_create_seed_table_{seed_name}.sql"
    id_space_path = EDA_QUERIES_DIR / id_space_filename

    if source_table:
        seed_sql = render_create_seed_view_sql(seed_name, source_table, source_column, id_space_filename)
    else:
        seed_sql = render_create_seed_table_sql(seed_name, s3_path, csv_filename, has_header, id_space_filename)
    seed_table_path.write_text(seed_sql, encoding="utf-8")
    id_space_path.write_text(render_id_space_check_sql(seed_name, num, period_months), encoding="utf-8")

    print(f"[OK] {seed_table_path}")
    print(f"[OK] {id_space_path}")
    print("[다음 단계] 둘 다 Athena 콘솔에서 실행 -> id_space_check 결과 한 줄(6개 숫자)을 받아서:")
    print(f"  ..\\.venv\\Scripts\\python.exe -m pipeline.generate_seed_queries resolve "
          f"--seed-name {seed_name} --matches <seed_total> <bidlog> <skp_direct> <skb_ad_id> <skb_platform_ad_id> <skb_uuid>")


# ---------- 2) resolve ----------

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


def render_ad_id_table_direct(seed_name: str, decision: dict) -> str:
    return f"""/* ============================================================
   02_create_seed_ad_id_table_{seed_name}.sql (seed, {seed_name} 신규 seed — 크로스워크
   불필요, pipeline/generate_seed_queries.py가 id space 판정 결과로 자동 생성)
   판정 근거(eda/queries id_space_check 결과, seed_total={decision['seed_total']}):
   direct 매칭률(skp_direct/skb_ad_id 중 최댓값)={decision['direct_rate']:.1%} — 임계값
   {DIRECT_THRESHOLD:.0%} 이상이라 이미 raw GAID(device_ifa) 공간으로 판정, skb 크로스워크
   없이 정규식 필터 + DISTINCT만 쓴다.

   이후 모든 seed 피처 추출(segment)과 "신규 후보(pool - seed)" 판정은 이 쿼리로 만든
   seed_{seed_name}_ad_id 테이블을 device_ifa 키로 그대로 조인해서 쓴다.
   ============================================================ */

CREATE TABLE {SEED_DB}.seed_{seed_name}_ad_id
WITH (format = 'PARQUET')
AS
SELECT DISTINCT device_ifa
FROM {SEED_DB}.seed_{seed_name}
WHERE device_ifa IS NOT NULL
  AND regexp_like(device_ifa, '^[0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{12}}$');
"""


def render_ad_id_table_crosswalk(seed_name: str, decision: dict) -> str:
    col = decision["crosswalk_col"]
    return f"""/* ============================================================
   02_create_seed_ad_id_table_{seed_name}.sql (seed, {seed_name} 신규 seed —
   ptbwa_skb.{col} 크로스워크 필요, pipeline/generate_seed_queries.py가 id space 판정
   결과로 자동 생성)
   판정 근거(eda/queries id_space_check 결과, seed_total={decision['seed_total']}): direct
   매칭률(skp_direct/skb_ad_id 중 최댓값)={decision['direct_rate']:.1%}(임계값 {DIRECT_THRESHOLD:.0%}
   미만) vs skb.{col} 매칭률={decision['crosswalk_rate']:.1%}(임계값 이상) — 피엘라벤 seed와
   동일 패턴, ptbwa_skb.{col}를 경유해 raw GAID(ad_id)로 크로스워크해야 한다.

   규모 주의: 크로스워크가 1:N일 수 있어(하나의 {col}가 여러 ad_id로 매핑) 이 테이블의
   행 수가 원본 seed_total보다 클 수 있다 — 실제 중복 유저 수가 아니라 같은 유저의 서로
   다른 시점 GAID(리셋 이력 등)일 수 있음(피엘라벤 사례 참고, 그대로 두는 게 이 프로젝트의
   device_ifa/ad_id 그레인과 일관적이라 그대로 둠).

   이후 모든 seed 피처 추출(segment)과 "신규 후보(pool - seed)" 판정은 이 쿼리로 만든
   seed_{seed_name}_ad_id 테이블(진짜 GAID 공간)을 device_ifa 키로 그대로 조인해서 쓴다.
   ============================================================ */

CREATE TABLE {SEED_DB}.seed_{seed_name}_ad_id
WITH (format = 'PARQUET')
AS
WITH seed AS (
    SELECT DISTINCT device_ifa
    FROM {SEED_DB}.seed_{seed_name}
    WHERE device_ifa IS NOT NULL
      AND regexp_like(device_ifa, '^[0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{12}}$')
),
skb AS (
    SELECT DISTINCT
        CAST({col} AS VARCHAR) AS {col},
        CAST(ad_id AS VARCHAR) AS ad_id
    FROM "propfit"."ptbwa_skb"
    WHERE {col} IS NOT NULL AND ad_id IS NOT NULL
)
SELECT DISTINCT k.ad_id AS device_ifa
FROM seed sd
JOIN skb k ON sd.device_ifa = k.{col};
"""


def _render_from_template(template_path: Path, seed_name: str, header: str) -> str:
    text = template_path.read_text(encoding="utf-8")
    body = text.split(BLOCK_COMMENT_END, 1)[1].lstrip("\n")
    body = body.replace("seed_je_ad_id", f"{SEED_DB}.seed_{seed_name}_ad_id")
    body = body.replace(LEGACY_SKP_TABLE, SKP_TABLE)
    return header + "\n\n" + body


def render_segment_query(seed_name: str) -> str:
    header = f"""/* ============================================================
   segment/02_seed_segment_{seed_name}.sql (seed, {seed_name} 신규 seed —
   pipeline/generate_seed_queries.py가 segment/02_seed_segment_je.sql을 템플릿 삼아 자동
   생성, device_ifa만 seed_{seed_name}_ad_id로 교체). pool/candidate는 기존 것을 그대로
   재사용한다는 전제 — 새 seed 규모가 크거나 기존 pool과 겹치는 게 걱정되면 pool을 따로
   뽑아 scoring 단계에서 --pool-ids-csv로 넘길 것. taxonomy(segment ID 배열)는
   02_seed_segment_je.sql과 동일 — taxonomy가 바뀌면 전부 같이 갱신할 것.
   ============================================================ */"""
    return _render_from_template(SEGMENT_TEMPLATE_PATH, seed_name, header)


def cmd_resolve(seed_name: str, matches: list) -> None:
    decision = decide_id_space(*matches)
    print(f"[판정] mode={decision['mode']} direct_rate={decision['direct_rate']:.1%} "
          f"crosswalk_rate={decision['crosswalk_rate']:.1%}(col={decision['crosswalk_col']})")

    if decision["mode"] == "ambiguous":
        print("[중단] 자동 판정 불가 — direct/crosswalk 매칭률이 임계값 기준으로 애매합니다. "
              "eda/queries/id_space_check/의 id_space_check 결과를 직접 보고 02_create_seed_ad_id_table_"
              f"{seed_name}.sql을 수동으로 작성하세요(je/피엘라벤 버전을 참고).")
        return

    ad_id_path = SEED_QUERIES_DIR / f"02_create_seed_ad_id_table_{seed_name}.sql"
    if decision["mode"] == "direct":
        ad_id_path.write_text(render_ad_id_table_direct(seed_name, decision), encoding="utf-8")
    else:
        ad_id_path.write_text(render_ad_id_table_crosswalk(seed_name, decision), encoding="utf-8")
    print(f"[OK] {ad_id_path}")

    segment_path = SEGMENT_QUERIES_DIR / f"02_seed_segment_{seed_name}.sql"
    segment_path.write_text(render_segment_query(seed_name), encoding="utf-8")
    print(f"[OK] {segment_path}")

    print("[다음 단계] 위 SQL 둘을 Athena 콘솔에서 순서대로 실행 -> 결과 CSV(seed_segment_"
          f"{seed_name}.csv)를 data/seed/에 받은 뒤, candidate 정의+피처 추출 쿼리를 생성:")
    print(f"  ..\\.venv\\Scripts\\python.exe -m pipeline.generate_seed_queries candidate "
          f"--seed-name {seed_name} --period-start <YYYY-MM-01> --period-end <YYYY-MM-DD>")


# ---------- 3) candidate ----------

_SEED_AD_ID_TABLE_RE = re.compile(r"CREATE TABLE\s+(?:\"[^\"]+\"\.)?(seed_\w+_ad_id)", re.IGNORECASE)


def _discover_seed_exclusions() -> list:
    """seed/queries/02_create_seed_ad_id_table*.sql(피엘라벤의 접미사 없는 버전 포함)을 전부
    스캔해 실제 CREATE TABLE 문에 쓰인 seed_<name>_ad_id 테이블명을 뽑는다 — candidate가
    "seed 전부에 없는 신규 유저"가 되려면 이 목록 전체를 제외해야 하므로, 새 seed가 생길
    때마다 하드코딩을 갱신할 필요 없이 이 목록도 같이 늘어나게 한다."""
    found = []
    for path in sorted(SEED_QUERIES_DIR.glob("02_create_seed_ad_id_table*.sql")):
        m = _SEED_AD_ID_TABLE_RE.search(path.read_text(encoding="utf-8"))
        if m and m.group(1) not in found:
            found.append(m.group(1))
    return found


def _render_period_predicate(period_start: str, period_end: str) -> str:
    """period_start/period_end: 'YYYY-MM-DD'. abi_bid_log_flatten의 year/month/day 파티션
    필터 WHERE 절 조각을 만든다.

    지원 범위(둘 다 위반하면 ValueError — 자동 생성 대신 03_create_candidate_table.sql
    2026-08-25 수정 내역을 참고해 수동으로 작성할 것):
    - 같은 연도 안에서만 지원한다(쿼리가 year='YYYY' 하나로 고정되므로 연도를 걸치는
      기간은 지원 안 함).
    - period_start는 항상 그 달의 1일이어야 한다(시작월 전체를 포함한다고 가정) — 일
      단위 상한은 period_end(마지막 달)에만 건다(03의 04/01~08/24 패턴과 동일)."""
    sy, sm, sd_ = period_start.split("-")
    ey, em, ed_ = period_end.split("-")
    if sy != ey:
        raise ValueError(
            f"기간이 연도를 걸칩니다({period_start}~{period_end}) — 이 쿼리는 year='{sy}' "
            f"하나로 고정되므로 자동 생성 불가, 수동으로 작성할 것"
        )
    if sd_ != "01":
        raise ValueError(
            f"period_start({period_start})가 그 달의 1일이 아닙니다 — 이 생성기는 "
            f"'시작월 전체(1일부터)'만 지원한다, 수동으로 작성할 것"
        )
    months = [f"{m:02d}" for m in range(int(sm), int(em) + 1)]
    if len(months) == 1:
        month_clause = f"b.month = '{months[0]}' AND CAST(b.day AS INTEGER) <= {int(ed_)}"
    else:
        full_list = ", ".join(f"'{m}'" for m in months[:-1])
        month_clause = f"(b.month IN ({full_list}) OR (b.month = '{months[-1]}' AND CAST(b.day AS INTEGER) <= {int(ed_)}))"
    return f"b.year = '{sy}'\n      AND {month_clause}"


def _render_multi_period_predicate(periods: list) -> str:
    """periods: [(start, end), ...] 여러 기간을 OR로 묶는다. 각 기간은
    _render_period_predicate의 제약(같은 연도, 시작은 월 1일)을 그대로 따른다."""
    if len(periods) == 1:
        return _render_period_predicate(*periods[0])
    parts = [f"(\n      {_render_period_predicate(a, b)}\n      )" for a, b in periods]
    return "(" + "\n      OR ".join(parts) + ")"


def render_candidate_segment_query(seed_name: str, period_start: str, period_end: str, periods: list = None) -> str:
    """candidate 정의(bid log 기간 + region=KR/OS=Android + skp 세그먼트 보유 + 기존 seed
    전부 제외) + 세그먼트 피처 추출을 CREATE TABLE 없이 SELECT 하나로 합친다 —
    03_create_candidate_table.sql(CTAS로 candidates_* 테이블 생성) + 04_candidate_segment.sql
    (그 테이블을 다시 조회해 피처 추출) 2단계였던 걸 하나로 줄였다. skp 최신 레코드
    (segments_latest1)를 "세그먼트 보유 여부 체크"와 "피처 추출" 양쪽에 재사용한다 — 단,
    Trino/Athena가 두 번 참조되는 CTE를 한 번만 계산한다는 보장은 없어 스캔 비용 절감은
    확정적이지 않다(확실한 이득은 Athena 실행 1회, candidates_* 테이블 생성/DROP 관리
    불필요, "재실행 필요: 이 파일 + 04" 같은 이력 관리 부담이 없어진다는 것).

    출력 컬럼은 04_candidate_segment.sql과 동일하다 — 결과를 그대로
    data/seed/candidate_segment.csv로 받으면 기존 scoring 파이프라인과 호환된다."""
    exclusions = _discover_seed_exclusions()
    self_table = f"seed_{seed_name}_ad_id"
    if self_table not in exclusions:
        raise ValueError(
            f"{self_table}이 seed/queries/02_create_seed_ad_id_table*.sql 중에 없습니다 — "
            f"먼저 resolve로 02_create_seed_ad_id_table_{seed_name}.sql을 생성하고 Athena에서 "
            f"실행했는지 확인할 것"
        )

    periods = periods or [(period_start, period_end)]
    period_where = _render_multi_period_predicate(periods)
    period_label = ", ".join(f"{a} ~ {b}" for a, b in periods)

    join_lines, null_lines = [], []
    for tbl in exclusions:
        alias = f"s_{tbl[len('seed_'):-len('_ad_id')]}"
        join_lines.append(f"    LEFT JOIN {SEED_DB}.{tbl} {alias} ON b.device_ifa = {alias}.device_ifa")
        null_lines.append(f"      AND {alias}.device_ifa IS NULL")
    joins_sql = "\n".join(join_lines)
    nulls_sql = "\n".join(null_lines)
    excluded_note = ", ".join(exclusions)

    header = f"""/* ============================================================
   segment/04_candidate_segment_{seed_name}.sql (seed, {seed_name} candidate 정의+세그먼트
   피처 추출 통합 쿼리 — pipeline/generate_seed_queries.py candidate 명령으로 자동 생성)

   PARAMETERS
     SEED_NAME       = {seed_name}
     PERIOD          = {period_label} (각 기간은 같은 연도 내에서만 지원, 시작일은
                        항상 시작월 1일부터로 가정 — 다르면 수동으로 고칠 것)
     EXCLUDED_SEEDS  = {excluded_note}
                        (seed/queries/02_create_seed_ad_id_table*.sql 전체를 스캔해 자동
                        도출 — 새 seed가 생기면 다음 생성 때 자동으로 포함된다)
     FILTERS         = region=KR, OS=Android(device_osv 숫자), skp 세그먼트 보유,
                        컴플라이언스(collect=1, lmt!=1), device_ifa UUID 형식

   CREATE TABLE 없이 SELECT 하나로 candidate 정의와 세그먼트 피처 추출을 동시에 한다
   (03_create_candidate_table.sql + 04_candidate_segment.sql을 합친 버전 — 그 두 파일은
   이미 실행된 seed의 provenance 기록이라 건드리지 않고 그대로 둔다). ID 목록/taxonomy는
   02_seed_segment_je.sql과 동일 — taxonomy가 바뀌면 전부 같이 갱신할 것.
   ============================================================ */"""

    candidates_block = f"""
WITH segments_latest AS (
    SELECT
        ad_id AS device_ifa,
        CAST(segments AS VARCHAR) AS segments,
        ROW_NUMBER() OVER (
            PARTITION BY ad_id
            ORDER BY year DESC, month DESC, day DESC
        ) AS rn
    FROM {SKP_TABLE}
    WHERE NOT (year = '2024' AND month = '12' AND day = '31')   /* 깨진 .tmp 파티션만 제외 */
      AND CAST(id_type AS VARCHAR) = '2'
      AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
),
segments_latest1 AS (
    SELECT device_ifa, segments FROM segments_latest WHERE rn = 1
),
candidates AS (
    SELECT DISTINCT b.device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten" b
{joins_sql}
    JOIN segments_latest1 seg ON b.device_ifa = seg.device_ifa
    WHERE {period_where}
      AND b.device_ifa IS NOT NULL AND trim(CAST(b.device_ifa AS VARCHAR)) <> ''
      AND regexp_like(CAST(b.device_ifa AS VARCHAR), '^[0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{12}}$')
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
{nulls_sql}
      AND CAST(b.device_geo_region AS VARCHAR) LIKE 'KR%'
      AND regexp_like(CAST(b.device_osv AS VARCHAR), '^[0-9]+$')
),
seg1 AS (
    SELECT c.device_ifa, split(sl.segments, ';') AS segment_ids
    FROM candidates c
    JOIN segments_latest1 sl ON c.device_ifa = sl.device_ifa
),
"""

    template_text = SEGMENT_TEMPLATE_PATH.read_text(encoding="utf-8")
    template_body = template_text.split(BLOCK_COMMENT_END, 1)[1]
    matched_onward = template_body[template_body.index("matched AS ("):].strip()

    return header + "\n" + candidates_block + matched_onward + "\n"


def cmd_candidate(seed_name: str, period_start: str, period_end: str, periods: list = None) -> None:
    text = render_candidate_segment_query(seed_name, period_start, period_end, periods)
    path = SEGMENT_QUERIES_DIR / f"04_candidate_segment_{seed_name}.sql"
    path.write_text(text, encoding="utf-8")
    print(f"[OK] {path}")
    print("[다음 단계] Athena 콘솔에서 실행(CREATE TABLE 없이 바로 결과 다운로드) -> "
          "data/seed/candidate_segment.csv로 받은 뒤:")
    print(f"  ..\\.venv\\Scripts\\python.exe -m pipeline.run_new_seed_pipeline --seed-name {seed_name}")


def main():
    parser = argparse.ArgumentParser(description="신규 seed의 Athena SQL 파일을 템플릿으로 생성")
    sub = parser.add_subparsers(dest="command", required=True)

    p_register = sub.add_parser("register", help="seed 테이블 등록 + id space 확인 쿼리 생성")
    p_register.add_argument("--seed-name", required=True)
    p_register.add_argument("--s3-path", help="예: s3://ptbwa-dw/prod/seed_yeti/ (--source-table 없을 때 필수)")
    p_register.add_argument("--source-table", help="이미 Athena에 있는 seed 테이블(예: '\"dev-ptbwa-da\".\"db_m_adid\"') — 주면 S3 CSV 대신 뷰를 만든다")
    p_register.add_argument("--source-column", default="device_ifa", help="--source-table의 광고 ID 컬럼명")
    p_register.add_argument("--csv-filename", help="data/seed/ 밑 원본 CSV 파일명(주석용, 선택)")
    p_register.add_argument("--header", action="store_true", help="원본 CSV에 헤더 행이 있으면 켤 것")
    p_register.add_argument("--period-months", nargs=2, default=("04", "05"),
                             metavar=("START", "END"), help="id space 확인 시 bidlog 매칭 기간(기본 04 05)")

    p_resolve = sub.add_parser("resolve", help="id space 결과로 ad_id/segment 쿼리 생성")
    p_resolve.add_argument("--seed-name", required=True)
    p_resolve.add_argument("--matches", nargs=6, type=int, required=True,
                            metavar=("SEED_TOTAL", "BIDLOG", "SKP_DIRECT", "SKB_AD_ID", "SKB_PLATFORM_AD_ID", "SKB_UUID"),
                            help="id_space_check 쿼리 결과 한 줄(SELECT 컬럼 순서 그대로)")

    p_candidate = sub.add_parser("candidate", help="candidate 정의+segment 피처 추출 쿼리 생성(CREATE TABLE 없음)")
    p_candidate.add_argument("--seed-name", required=True)
    p_candidate.add_argument("--period-start", metavar="YYYY-MM-01",
                              help="candidate 기간 시작 — 반드시 그 달의 1일")
    p_candidate.add_argument("--period-end", metavar="YYYY-MM-DD",
                              help="candidate 기간 끝(같은 연도) — 그 날짜까지 포함")
    p_candidate.add_argument("--period", action="append", metavar="YYYY-MM-01:YYYY-MM-DD",
                              help="여러 기간을 줄 때 반복 지정(예: --period 2026-01-01:2026-03-31 --period 2026-06-01:2026-09-30)")

    args = parser.parse_args()
    if args.command == "register":
        if not args.source_table and not args.s3_path:
            parser.error("register: --s3-path 또는 --source-table 중 하나는 필요")
        cmd_register(args.seed_name, args.s3_path, args.csv_filename, args.header, tuple(args.period_months),
                     args.source_table, args.source_column)
    elif args.command == "resolve":
        cmd_resolve(args.seed_name, args.matches)
    elif args.command == "candidate":
        if args.period:
            periods = [tuple(x.split(":")) for x in args.period]
            cmd_candidate(args.seed_name, periods[0][0], periods[-1][1], periods)
        elif args.period_start and args.period_end:
            cmd_candidate(args.seed_name, args.period_start, args.period_end)
        else:
            parser.error("candidate: --period(반복) 또는 --period-start/--period-end 필요")


if __name__ == "__main__":
    main()
