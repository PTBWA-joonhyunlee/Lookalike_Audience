/* ============================================================
   25_candidate_202603_media_top30_excl_skb_adui_no_threshold.sql (eda, 2026-08-04)
   목적: 24번(skb.adui 제외 + 5+ 문턱)이 결과 없음(0명)으로 나온 게 "3월엔 skb.adui 외
   다른 top500 미디어 로그 자체가 희박해서"인지, "방문자는 있는데 1인당 5회를 못
   채워서(문턱이 너무 엄격해서)"인지 구분한다 — 문턱 없이 방문자 1회 이상 기준으로만
   top30 media를 집계한다(dedup 여부는 "방문했는지 여부"에 영향 없으므로 flagged/
   deduped 단계를 생략해 더 가볍다).

   base_n(3월 KR+Android+seed제외 전체 모집단)과 any_top500_excl_skb_n(그중 skb.adui를
   뺀 top500 미디어를 1개라도 방문한 사람 수)을 같이 반환해, "그나마 방문자가 있긴
   한지"를 표 전체가 텅 비었을 때와 구분할 수 있게 한다.

   전제: propfit_media_top500, seed_piellaven_ad_id가 이미 있어야 함.
   ============================================================ */

WITH base AS (
    SELECT DISTINCT b.device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten" b
    LEFT JOIN seed_piellaven_ad_id sd ON b.device_ifa = sd.device_ifa
    WHERE b.year = '2026' AND b.month = '03'
      AND b.device_ifa IS NOT NULL AND trim(CAST(b.device_ifa AS VARCHAR)) <> ''
      AND regexp_like(CAST(b.device_ifa AS VARCHAR), '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
      AND sd.device_ifa IS NULL
      AND CAST(b.device_geo_region AS VARCHAR) LIKE 'KR%'
      AND regexp_like(CAST(b.device_osv AS VARCHAR), '^[0-9]+$')
),
raw_visit AS (
    SELECT DISTINCT
        v.device_ifa,
        COALESCE(
            NULLIF(CAST(v.app_bundle AS VARCHAR), ''),
            NULLIF(CAST(v.site_page AS VARCHAR), '')
        ) AS media
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten" v
    JOIN base ON v.device_ifa = base.device_ifa
    JOIN propfit_media_top500 r
      ON COALESCE(NULLIF(CAST(v.app_bundle AS VARCHAR), ''), NULLIF(CAST(v.site_page AS VARCHAR), '')) = r.media
     AND r.media <> 'com.skb.adui'
    WHERE v.year = '2026' AND v.month = '03'
      AND v.req_user_id IS NOT NULL AND trim(CAST(v.req_user_id AS VARCHAR)) <> ''
      AND CAST(v.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (v.device_lmt IS NULL OR CAST(v.device_lmt AS VARCHAR) <> '1')
),
base_n AS (
    SELECT COUNT(*) AS n FROM base
),
any_media_n AS (
    SELECT COUNT(DISTINCT device_ifa) AS n FROM raw_visit
)
SELECT
    rv.media,
    COUNT(DISTINCT rv.device_ifa) AS visitors,
    (SELECT n FROM base_n) AS base_n,
    (SELECT n FROM any_media_n) AS any_top500_excl_skb_n,
    ROUND(CAST(COUNT(DISTINCT rv.device_ifa) AS DOUBLE) / (SELECT n FROM base_n) * 100, 4) AS pct_of_base
FROM raw_visit rv
GROUP BY rv.media
ORDER BY visitors DESC
LIMIT 30;
