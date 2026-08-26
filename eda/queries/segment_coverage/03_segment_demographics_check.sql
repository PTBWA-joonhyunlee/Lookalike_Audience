-- ============================================================
-- 05_segment_demographics_check.sql (propfit)
-- 목적: 이전 버전(2026-07-24 이전)은 rn=1 dedup 없이 skp를 통째로 count(*)해서
--   1,815,170,636행(=디바이스 수가 아니라 유저당 ~34개 스냅샷이 겹친 raw 행 수, 03/04에서
--   확인한 distinct 디바이스 수 53,341,243과 비교하면 확연히 다름)이 나왔다. gender/age
--   같은 안정적 속성은 프로파일링된 유저일수록 스냅샷마다 반복 등장해서 행 기준 비율이
--   실제 디바이스 커버리지보다 부풀려질 수 있다 — 그래서 03_user_segments.sql과 동일하게
--   ad_id별 최신 스냅샷 1건으로 dedup한 뒤, bid log 모집단과 교집합까지 낸 디바이스 단위
--   숫자로 다시 잰다. ptbwa_tg 경로의 2,500명(04_coverage_check.sql (A))과 바로 비교 가능한
--   단위로 맞췄다 — bid_gender가 그 비교 대상.
-- 검산용 기대치: seg_devices ≈ 53,341,243(03_user_segments.sql과 같은 로직), in_bid ≈
--   15,552,864(04_coverage_check.sql (B)의 overlap_devices와 같은 로직) — 이 두 숫자가
--   크게 어긋나면 쿼리 자체가 잘못된 것.
-- ============================================================

WITH seg AS (
    SELECT
        ad_id,
        segments,
        ROW_NUMBER() OVER (
            PARTITION BY ad_id
            ORDER BY year DESC, month DESC, day DESC
        ) AS rn
    FROM "propfit"."skp"
    WHERE NOT (year = '2024' AND month = '12' AND day = '31')
      AND CAST(id_type AS VARCHAR) = '2'
      AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
),
seg1 AS (
    SELECT ad_id, segments FROM seg WHERE rn = 1
),
bid AS (
    SELECT DISTINCT device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')
      AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
)
SELECT
    count(*)                                                                                                             AS seg_devices,   -- 검산: ≈ 53,341,243
    count_if(regexp_like(CAST(s.segments AS VARCHAR), '(^|;)(26455|26456|26457|26458)(;|$)'))                            AS dev_gender,
    count_if(regexp_like(CAST(s.segments AS VARCHAR), '(^|;)1000[3-9](;|$)'))                                            AS dev_age,
    count(b.device_ifa)                                                                                                  AS in_bid,        -- 검산: ≈ 15,552,864
    count_if(b.device_ifa IS NOT NULL AND regexp_like(CAST(s.segments AS VARCHAR), '(^|;)(26455|26456|26457|26458)(;|$)')) AS bid_gender
FROM seg1 s
LEFT JOIN bid b ON s.ad_id = b.device_ifa;
