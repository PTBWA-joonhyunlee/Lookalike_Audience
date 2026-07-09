-- ============================================================
-- 04_seed_profile_apr_may.sql
-- 목적: 03에서 뽑은 시드 유저(양성 후보, ~412명)의 프로필을 5% 샘플링 없이 전수 조회한다
--       (01_pool_profile_apr_may.sql과 컬럼 계약 동일). 07_scoring_target_profile_jun.sql과
--       로직은 같고 대상 유저 목록과 기간(4~5월)만 다르다.
-- 다음 단계: 이 CSV로 inference.user_profile을 돌려 임베딩을 뽑고,
--       scoring.build_stratified_pool로 pool_profile.csv(5% 샘플)에 병합한다.
-- ============================================================

WITH matched_ifa AS (
  -- 03_seed_users_apr_may.sql 결과를 그대로 다시 씀(별도 테이블로 안 쌓아두므로 중복
  -- 정의) — 03번 쿼리 결과 CSV의 device_ifa 컬럼과 동일한 집합이어야 한다.
  SELECT DISTINCT ifa AS device_ifa
  FROM (
    WITH postback_ip AS (
      SELECT
        ifa,
        CAST(ip AS VARCHAR) AS ip,
        CAST(cmp_no AS VARCHAR) AS cmp_no,
        min(created_at) AS first_created_at
      FROM "prod-ptbwa-dw".addi_postback_log
      WHERE year = '2026' AND month IN ('04', '05')
        AND ip IS NOT NULL AND trim(CAST(ip AS VARCHAR)) <> ''
      GROUP BY ifa, CAST(ip AS VARCHAR), CAST(cmp_no AS VARCHAR)
    ),
    conv AS (
      SELECT
        CAST(mall_ip AS VARCHAR) AS mall_ip,
        CAST(cmp_no AS VARCHAR) AS cmp_no,
        CAST(regexp_replace(CAST(mall_datetime AS VARCHAR), 'T', ' ') AS TIMESTAMP) AS mall_ts
      FROM "prod_addi_conv".raw_conv_web
      UNION ALL
      SELECT
        CAST(mall_ip AS VARCHAR) AS mall_ip,
        CAST(cmp_no AS VARCHAR) AS cmp_no,
        CAST(regexp_replace(CAST(mall_datetime AS VARCHAR), 'T', ' ') AS TIMESTAMP) AS mall_ts
      FROM "prod_addi_conv".raw_conv_web_imp
    )
    SELECT p.ifa
    FROM postback_ip p
    JOIN conv c ON p.ip = c.mall_ip AND p.cmp_no = c.cmp_no
    WHERE date_diff(
        'hour',
        CAST(regexp_replace(CAST(p.first_created_at AS VARCHAR), 'T', ' ') AS TIMESTAMP),
        c.mall_ts
      ) >= 0
  )
),
latest_log AS (
    SELECT
        b.device_ifa,
        b.req_user_id,
        b.device_osv AS device_os_version,
        b.device_geo_region AS region,
        b.app_bundle,
        ROW_NUMBER() OVER (
            PARTITION BY b.device_ifa
            ORDER BY b.created_at DESC
        ) AS rn
    FROM "prod-ptbwa-dw"."addi_bid_log_flatten" b
    JOIN matched_ifa m ON b.device_ifa = m.device_ifa
    WHERE b.year = '2026' AND b.month IN ('04', '05')
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
      AND b.req_user_id IS NOT NULL AND trim(CAST(b.req_user_id AS VARCHAR)) <> ''
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
