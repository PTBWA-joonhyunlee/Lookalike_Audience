/* ============================================================
   04a_seed_profile.sql (seed, 구 05a_seed_profile.sql)
   01_user_profile.sql(propfit)과 동일 로직, device_ifa를 seed_piellaven_ad_id(02에서
   만든 크로스워크 결과, 진짜 GAID 공간)로 제한. 전수 추출(샘플링 없음).
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
    JOIN seed_piellaven_ad_id sd ON b.device_ifa = sd.device_ifa
    WHERE b.year = '2026' AND b.month IN ('04', '05')
      AND b.device_ifa IS NOT NULL AND trim(CAST(b.device_ifa AS VARCHAR)) <> ''
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
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
