/* ============================================================
   07a_candidate_profile.sql (seed, 구 08a_candidate_profile.sql)
   01_user_profile.sql(propfit)과 동일 로직, device_ifa를 candidates_202606(06)로
   제한, 기간은 2026-06(후보 정의 기간과 일치). 전수 추출(샘플링 없음 — 07에서 이미
   기간으로 규모를 좁혔음).

   2026-08-03 수정(region=KR/OS=Android 필터 추가): 04a_seed_profile.sql 헤더 참고.
   06에서 이미 region=KR/OS=Android로 후보를 제한했지만, 이 쿼리도 독립적으로 같은
   조건을 명시해 다른 candidate 테이블에 재사용될 때도 안전하게 한다.
   ============================================================ */

WITH bidlog_latest AS (
    SELECT
        b.device_ifa,
        b.req_user_id,
        b.device_osv AS device_os_version,
        b.device_geo_region AS region,
        b.app_bundle,
        b.device_carrier AS carrier,
        ROW_NUMBER() OVER (
            PARTITION BY b.device_ifa
            ORDER BY b.created_at DESC
        ) AS rn
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten" b
    JOIN candidates_202606 c ON b.device_ifa = c.device_ifa
    WHERE b.year = '2026' AND b.month = '06'
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
      AND CAST(b.device_geo_region AS VARCHAR) LIKE 'KR%'
      AND regexp_like(CAST(b.device_osv AS VARCHAR), '^[0-9]+$')
)
SELECT
    req_user_id,
    device_ifa,
    device_os_version,
    region,
    app_bundle,
    carrier,
    current_date AS update_dt
FROM bidlog_latest
WHERE rn = 1;
