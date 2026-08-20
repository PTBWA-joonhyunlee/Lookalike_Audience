/* ============================================================
   09_seed_coverage_check.sql (eda, 구 propfit/seed_lookalike/01_seed_coverage_check.sql)
   목적: 피엘라벤 seed(150만 device_ifa, 외부 소스)가 실제로 이 프로젝트의 피처 소스
   (abi_bid_log_flatten → 01/02, propfit.skp → 11)에서 얼마나 매칭되는지 확인한다.
   매칭률이 너무 낮으면(예전 ptbwa_tg 사례처럼 한 자릿수 % 이하) 이 소스로는 학습이
   사실상 불가능하다는 신호이므로, 다음 단계(피처 추출/학습)로 넘어가기 전에 반드시 먼저 본다.

   device_ifa 정규식 필터: 로컬에서 이미 UUID 아닌 3행을 정제했지만(00_create_seed_table.sql
   참고), S3에 다른 배치로 재업로드될 가능성에 대비해 방어적으로 한 번 더 건다.

   기간: bid log는 기존 01/02와 동일하게 2026-04~05를 기본으로 본다. 매칭률이 낮게 나오면
   기간을 넓혀(예: 최근 6개월) 재확인할 것 — seed 유저가 이 기간에만 없고 다른 시점엔
   활동했을 수 있다.

   주의: 줄(--) 주석 대신 블록 주석(／＊ ＊／)을 쓴다 — 00_create_seed_table.sql에서 줄바꿈이
   사라진 채 실행되며 -- 주석이 뒤의 SQL 전체를 삼켜 파싱 에러가 난 적이 있어(2026-07-29),
   이 파일도 동일한 문제를 막기 위해 미리 블록 주석으로 통일했다.
   ============================================================ */

WITH seed AS (
    SELECT DISTINCT device_ifa
    FROM seed_piellaven
    WHERE device_ifa IS NOT NULL
      AND regexp_like(device_ifa, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
),
bidlog AS (
    SELECT DISTINCT device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')
      AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
),
segments AS (
    SELECT DISTINCT ad_id AS device_ifa
    FROM "propfit"."skp"
    WHERE NOT (year = '2024' AND month = '12' AND day = '31')   /* 깨진 .tmp 파티션 제외 */
      AND CAST(id_type AS VARCHAR) = '2'
      AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
)
SELECT
    (SELECT count(*) FROM seed)                                              AS seed_total,
    count(b.device_ifa)                                                      AS seed_in_bidlog,
    count(s.device_ifa)                                                      AS seed_in_segments,
    count(b.device_ifa) FILTER (WHERE s.device_ifa IS NOT NULL)              AS seed_in_bidlog_and_segments,
    round(100.0 * count(b.device_ifa) / (SELECT count(*) FROM seed), 2)      AS pct_in_bidlog,
    round(100.0 * count(s.device_ifa) / (SELECT count(*) FROM seed), 2)      AS pct_in_segments
FROM seed sd
LEFT JOIN bidlog  b ON sd.device_ifa = b.device_ifa
LEFT JOIN segments s ON sd.device_ifa = s.device_ifa;
