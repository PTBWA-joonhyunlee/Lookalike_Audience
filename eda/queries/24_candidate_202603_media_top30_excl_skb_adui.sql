/* ============================================================
   24_candidate_202603_media_top30_excl_skb_adui.sql (eda, 2026-08-04)
   목적: 23_candidate_202603_media_top30.sql에서 `com.skb.adui` 하나가 3월 후보
   정의(5+ dedup 이벤트)를 100% 채워버린 것으로 확인됐다 — 이 항목을 top500 매칭
   단계에서부터 제외하면 "그 뒤에 숨어 있던" 실제 media 분포/후보 규모가 어떻게
   드러나는지 확인한다(5-1절 액션 아이템: "skb.adui를 top500/후보 조건에서 제외하고
   재실행").

   23번과 동일하되 raw_visit JOIN 조건에 `r.media <> 'com.skb.adui'`만 추가했다 —
   제외가 5+ 문턱 통과 여부 자체에도 영향을 주도록(문턱을 넘긴 후 결과만 필터링하는
   게 아니라, 애초에 skb.adui 이벤트를 집계에서 빼고 그 나머지로 5+ 문턱을 다시 판정).

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
    SELECT
        v.req_id,
        v.req_user_id,
        v.device_ifa,
        COALESCE(
            NULLIF(CAST(v.app_bundle AS VARCHAR), ''),
            NULLIF(CAST(v.site_page AS VARCHAR), '')
        ) AS media,
        CAST(from_iso8601_timestamp(CAST(v.created_at AS VARCHAR)) AT TIME ZONE 'Asia/Seoul' AS timestamp) AS ts
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
flagged AS (
    SELECT
        device_ifa,
        media,
        ts,
        req_id,
        LAG(media) OVER (PARTITION BY req_user_id ORDER BY ts, req_id) AS prev_media,
        LAG(ts)    OVER (PARTITION BY req_user_id ORDER BY ts, req_id) AS prev_ts
    FROM raw_visit
),
deduped AS (
    SELECT device_ifa, media
    FROM flagged
    WHERE prev_media IS NULL
       OR prev_media <> media
       OR date_diff('second', prev_ts, ts) >= 1800
),
qualified AS (
    SELECT device_ifa
    FROM deduped
    GROUP BY device_ifa
    HAVING COUNT(*) >= 5
),
qualified_visits AS (
    SELECT DISTINCT d.device_ifa, d.media
    FROM deduped d
    JOIN qualified q ON d.device_ifa = q.device_ifa
),
total AS (
    SELECT COUNT(*) AS n FROM qualified
)
SELECT
    qv.media,
    COUNT(DISTINCT qv.device_ifa) AS visitors,
    (SELECT n FROM total) AS candidate_n,
    ROUND(CAST(COUNT(DISTINCT qv.device_ifa) AS DOUBLE) / (SELECT n FROM total) * 100, 2) AS visitor_pct
FROM qualified_visits qv
GROUP BY qv.media
ORDER BY visitors DESC
LIMIT 30;
