# seed/pipeline/generate_seed_queries.py
#
# 신규 seed가 들어왔을 때 자동화 범위 밖(Athena SQL) 단계의 쿼리 파일을 템플릿으로
# 생성한다. 이 repo는 Athena 접근 권한이 없어 실행 자체는 여전히 사용자가 콘솔에서 해야
# 하지만(CLAUDE.md "데이터를 얻는 방법" 참고), je seed(2026-08-19)에서 손으로 반복했던
# 01_create_seed_table_*.sql / id_space_check 쿼리 / 02_create_seed_ad_id_table_*.sql
# (직접/크로스워크 판정 포함) / segment 쿼리 / candidate 제외 조건 추가를 패턴화했다.
#
# 두 단계로 나뉜다 — ID 공간(크로스워크 필요 여부)은 실제 쿼리 실행 결과를 봐야 판정할 수
# 있어 완전 자동화가 불가능하기 때문이다(eda/docs/id_space_crosswalk.md 참고, 매칭 건수만
# 보고 "같은 공간"이라 추론하면 안 된다는 프로젝트 규칙):
#
#   1) register: seed 테이블 등록 DDL + id space 확인 쿼리를 생성한다.
#      -> 사용자가 둘 다 Athena에서 실행하고, id space 쿼리 결과 한 줄(seed_total부터
#         seed_matches_skb_uuid까지 6개 숫자)을 받아온다.
#   2) resolve: 그 6개 숫자를 --matches로 넘기면 직접/크로스워크를 자동 판정해서
#      02_create_seed_ad_id_table_<name>.sql / segment 쿼리를 생성하고,
#      segment/03_create_candidate_table.sql에 이 seed 제외 조건을 자동으로 추가한다
#      (이미 추가돼 있으면 건드리지 않음 - 여러 번 실행해도 안전).
#
# 실행(seed/ 안에서 cd 후):
#   ..\.venv\Scripts\python.exe -m pipeline.generate_seed_queries register \
#     --seed-name yeti --s3-path s3://ptbwa-dw/prod/seed_yeti/ --csv-filename yeti_seed.csv --header
#
#   (Athena에서 01_create_seed_table_yeti.sql, eda/queries/id_space_check/NN_seed_yeti_id_space_check.sql 실행 후)
#
#   ..\.venv\Scripts\python.exe -m pipeline.generate_seed_queries resolve \
#     --seed-name yeti --matches 3000 2800 2600 10 5 0

import argparse
import sys
from datetime import date
from pathlib import Path

from scoring.config import PROJECT_ROOT

# Windows 콘솔(cp949)은 이 파일의 안내 메시지에 쓰는 em dash/화살표 등을 인코딩하지 못해
# print()가 UnicodeEncodeError로 죽는다 — 이미 파일 쓰기(write_text, 항상 UTF-8)는 끝난
# 뒤에 죽는 경우가 있어(patch_candidate_table_exclusion 등) "실패한 것처럼 보이지만 실제로는
# 파일이 이미 바뀐" 혼란스러운 상태를 만든다. stdout을 UTF-8로 강제해 이 크래시를 막는다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SEED_QUERIES_DIR = PROJECT_ROOT / "seed" / "queries"
SEGMENT_QUERIES_DIR = SEED_QUERIES_DIR / "segment"
# 2026-08-26 eda/queries 재정리: id space 확인 쿼리는 eda/queries/id_space_check/ 밑에
# 따로 모은다(seed 보유율/분포 확인용 쿼리는 eda/queries/segment_coverage/로 분리) —
# 번호는 이 하위 폴더 안에서만 이어서 매긴다.
EDA_QUERIES_DIR = PROJECT_ROOT / "eda" / "queries" / "id_space_check"

# segment 쿼리는 세그먼트 taxonomy(gender/age/residence/product/content/etc ID 배열)를
# 그대로 복사해야 해서 손으로 다시 옮기면 사고가 나기 쉽다 — je 버전을 "정본 템플릿"으로
# 읽어서 seed_je_ad_id만 치환한다(je 버전 자체가 이미 taxonomy 변경 없이 피엘라벤 원본을
# 그대로 복사한 것이므로 신뢰 가능).
SEGMENT_TEMPLATE_PATH = SEGMENT_QUERIES_DIR / "02_seed_segment_je.sql"
CANDIDATE_TABLE_PATH = SEGMENT_QUERIES_DIR / "03_create_candidate_table.sql"

BLOCK_COMMENT_END = "   ============================================================ */"

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
    FROM seed_{seed_name}
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
    FROM "propfit"."skp"
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
                  period_months=("04", "05")) -> None:
    num = _next_eda_number()
    id_space_filename = f"{num}_seed_{seed_name}_id_space_check.sql"

    seed_table_path = SEED_QUERIES_DIR / f"01_create_seed_table_{seed_name}.sql"
    id_space_path = EDA_QUERIES_DIR / id_space_filename

    seed_table_path.write_text(
        render_create_seed_table_sql(seed_name, s3_path, csv_filename, has_header, id_space_filename),
        encoding="utf-8",
    )
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

CREATE TABLE seed_{seed_name}_ad_id
WITH (format = 'PARQUET')
AS
SELECT DISTINCT device_ifa
FROM seed_{seed_name}
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

CREATE TABLE seed_{seed_name}_ad_id
WITH (format = 'PARQUET')
AS
WITH seed AS (
    SELECT DISTINCT device_ifa
    FROM seed_{seed_name}
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
    body = body.replace("seed_je_ad_id", f"seed_{seed_name}_ad_id")
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


def patch_candidate_table_exclusion(seed_name: str, candidate_table_path: Path = CANDIDATE_TABLE_PATH) -> bool:
    """candidate 정의(segment/03_create_candidate_table.sql)에 seed_<name>_ad_id 제외 조건을
    추가한다 — je 때 손으로 했던 'LEFT JOIN seed_je_ad_id ... AND sj.device_ifa IS NULL'
    추가를 패턴화했다. 이미 추가돼 있으면 아무것도 하지 않고 False를 반환(여러 번 실행해도
    안전)."""
    text = candidate_table_path.read_text(encoding="utf-8")
    ad_id_table = f"seed_{seed_name}_ad_id"
    if ad_id_table in text:
        print(f"[SKIP] {candidate_table_path.name}에 이미 {ad_id_table} 제외 조건이 있음")
        return False

    lines = text.splitlines(keepends=True)
    join_idx = [i for i, l in enumerate(lines) if l.strip().startswith("LEFT JOIN seed_") and "_ad_id" in l]
    is_null_idx = [i for i, l in enumerate(lines)
                   if l.strip().startswith("AND") and "device_ifa IS NULL" in l]
    if not join_idx or not is_null_idx:
        raise ValueError(
            f"{candidate_table_path}에서 기존 'LEFT JOIN seed_*_ad_id' 또는 "
            f"'AND s*.device_ifa IS NULL' 패턴을 찾지 못함 — 파일 구조가 바뀐 것으로 보임, "
            f"수동으로 확인/추가할 것"
        )

    alias = f"s_{seed_name}"
    lines.insert(join_idx[-1] + 1, f"LEFT JOIN {ad_id_table} {alias} ON b.device_ifa = {alias}.device_ifa\n")
    # 위에서 한 줄 삽입했으니 WHERE 절 인덱스가 하나 밀림
    is_null_idx = [i for i, l in enumerate(lines)
                   if l.strip().startswith("AND") and "device_ifa IS NULL" in l]
    lines.insert(is_null_idx[-1] + 1, f"  AND {alias}.device_ifa IS NULL\n")

    text = "".join(lines)
    note = (
        f"\n   {date.today().isoformat()} 수정(seed_{seed_name} 제외 추가, "
        f"pipeline/generate_seed_queries.py 자동 생성): candidate가 신규 seed({seed_name}) 본인을 "
        f"포함하지 않도록 LEFT JOIN {ad_id_table} + AND {alias}.device_ifa IS NULL을 추가했다.\n"
        f"   **재실행 필요**: 이 파일, segment/04_candidate_segment.sql — candidate 모집단이 바뀌므로.\n"
    )
    idx = text.index(BLOCK_COMMENT_END)
    text = text[:idx] + note + text[idx:]

    candidate_table_path.write_text(text, encoding="utf-8")
    print(f"[OK] {candidate_table_path}에 {ad_id_table} 제외 조건 추가 완료 "
          f"— 리뷰 후 Athena에서 재실행 필요(이 파일 + segment/04_candidate_segment.sql)")
    return True


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

    patch_candidate_table_exclusion(seed_name)

    print("[다음 단계] 위 SQL들을 Athena 콘솔에서 순서대로 실행 -> 결과 CSV를 data/seed/에 "
          f"받은 뒤: python -m pipeline.run_new_seed_pipeline --seed-name {seed_name}")


def main():
    parser = argparse.ArgumentParser(description="신규 seed의 Athena SQL 파일을 템플릿으로 생성")
    sub = parser.add_subparsers(dest="command", required=True)

    p_register = sub.add_parser("register", help="seed 테이블 등록 + id space 확인 쿼리 생성")
    p_register.add_argument("--seed-name", required=True)
    p_register.add_argument("--s3-path", required=True, help="예: s3://ptbwa-dw/prod/seed_yeti/")
    p_register.add_argument("--csv-filename", help="data/seed/ 밑 원본 CSV 파일명(주석용, 선택)")
    p_register.add_argument("--header", action="store_true", help="원본 CSV에 헤더 행이 있으면 켤 것")
    p_register.add_argument("--period-months", nargs=2, default=("04", "05"),
                             metavar=("START", "END"), help="id space 확인 시 bidlog 매칭 기간(기본 04 05)")

    p_resolve = sub.add_parser("resolve", help="id space 결과로 ad_id/segment 쿼리 생성 + candidate 제외 조건 patch")
    p_resolve.add_argument("--seed-name", required=True)
    p_resolve.add_argument("--matches", nargs=6, type=int, required=True,
                            metavar=("SEED_TOTAL", "BIDLOG", "SKP_DIRECT", "SKB_AD_ID", "SKB_PLATFORM_AD_ID", "SKB_UUID"),
                            help="id_space_check 쿼리 결과 한 줄(SELECT 컬럼 순서 그대로)")

    args = parser.parse_args()
    if args.command == "register":
        cmd_register(args.seed_name, args.s3_path, args.csv_filename, args.header, tuple(args.period_months))
    elif args.command == "resolve":
        cmd_resolve(args.seed_name, args.matches)


if __name__ == "__main__":
    main()
