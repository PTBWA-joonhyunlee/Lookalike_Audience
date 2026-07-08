-- ============================================================
-- 05_new_users_user_profile_jun.sql
-- 목적   : 2026-06 스코어링 대상 "신규 유저"의 인구통계/디바이스 프로필 (user_profile 추론 입력).
--          "신규 유저" 정의는 04_new_users_top500_media_visit_jun.sql과 동일 — 2026-04~05
--          addi_bid_log_flatten에 없던 req_user_id만. 02_user_profile.sql과 컬럼 계약은 동일,
--          기간과 신규 유저 필터만 다르다.
-- 샘플링 : 04_new_users_top500_media_visit_jun.sql과 반드시 동일한 유저 단위 5% 샘플링 조건을
--          쓴다(같은 유저 집합을 가리켜야 함). 파일럿 단계용 — 실제 후보 리스트 산출 시 제거.
-- 컬럼 축소(2026-07-08): 02_user_profile.sql과 동일 이유로 컬럼을 줄였다 — 자세한 사유는
--          02_user_profile.sql 주석 참고. 02와 컬럼 계약은 계속 동일하게 맞춘다.
-- ============================================================

WITH prior_users AS (
    SELECT DISTINCT req_user_id
    FROM "prod-ptbwa-dw"."addi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')
      AND req_user_id IS NOT NULL AND trim(CAST(req_user_id AS VARCHAR)) <> ''
),
latest_log AS (
    SELECT
        b.req_user_id,
        b.device_ifa,
        b.device_osv AS device_os_version,
        b.device_geo_region AS region,
        b.app_bundle,
        b.created_at,
        ROW_NUMBER() OVER (
            PARTITION BY b.req_user_id
            ORDER BY b.created_at DESC
        ) AS rn
    FROM "prod-ptbwa-dw"."addi_bid_log_flatten" b
    LEFT JOIN prior_users p ON b.req_user_id = p.req_user_id
    WHERE b.year = '2026' AND b.month = '06'
      AND b.req_user_id IS NOT NULL AND trim(CAST(b.req_user_id AS VARCHAR)) <> ''
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
      AND p.req_user_id IS NULL   -- ← 04-05월에 없었던 유저만 (신규 유저 필터)
      AND mod(crc32(to_utf8(CAST(b.req_user_id AS VARCHAR))), 100) < 5   -- ← 유저 단위 5% 샘플링 (04와 동일 조건)
)
SELECT
    req_user_id,
    device_ifa,
    device_os_version,
    region,
    app_bundle,
    current_date AS update_dt
FROM latest_log
WHERE rn = 1;
