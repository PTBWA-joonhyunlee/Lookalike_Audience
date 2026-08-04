/* ============================================================
   media/03_seed_media.sql (seed, 2026-08-04 segment/media 트랙 분리 — 구 04b_seed_media.sql)
   lib/02_user_media.sql(propfit)과 동일 로직, device_ifa를 seed_piellaven_ad_id로
   제한하고, top500 미디어 vocab은 자체 계산하지 않고 01_create_media_vocab_table.sql로
   만든 propfit_media_top500(전체 모집단 기준, seed/pool/candidate 공유)을 그대로
   참조한다(vocab 불일치 방지 이유). 전수 추출 — pool(02_pool_media.sql)과 달리 최소
   활동량 조건은 없다(seed는 원래 활동량이 충분히 많아 필요성이 낮다고 판단, 모델
   레벨 MIN_SEQ_LEN=5로 이미 걸러짐).

   2026-08-03 수정(region=KR/OS=Android 필터 추가): pool/candidate의 해외·iOS 트래픽이
   media 신호를 희석시킨다는 가설을 검증하기 위해 모집단 자체를 region=KR AND
   OS=Android로 제한한다.
   ============================================================ */

WITH raw_visit AS (
    SELECT
        v.req_id,
        v.req_user_id,
        v.device_ifa,
        COALESCE(
            NULLIF(CAST(v.app_bundle AS VARCHAR), ''),
            NULLIF(CAST(v.site_page AS VARCHAR), '')
        ) AS media,
        CASE
            WHEN NULLIF(CAST(v.app_bundle AS VARCHAR), '') IS NOT NULL THEN 'app'
            WHEN NULLIF(CAST(v.site_page AS VARCHAR), '') IS NOT NULL THEN 'site'
            ELSE NULL
        END AS inventory_type,
        NULLIF(CAST(v.imp_ad_type AS VARCHAR), '') AS ad_type,
        NULLIF(CAST(v.device_connectiontype AS VARCHAR), '') AS connection_type,
        CAST(from_iso8601_timestamp(CAST(v.created_at AS VARCHAR)) AT TIME ZONE 'Asia/Seoul' AS timestamp) AS ts,
        v.year
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten" v
    JOIN seed_piellaven_ad_id sd ON v.device_ifa = sd.device_ifa
    WHERE v.year = '2026' AND v.month IN ('04', '05')
      AND v.req_user_id IS NOT NULL
      AND trim(CAST(v.req_user_id AS VARCHAR)) <> ''
      AND CAST(v.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (v.device_lmt IS NULL OR CAST(v.device_lmt AS VARCHAR) <> '1')
      AND CAST(v.device_geo_region AS VARCHAR) LIKE 'KR%'
      AND regexp_like(CAST(v.device_osv AS VARCHAR), '^[0-9]+$')
),
top500 AS (
    SELECT
        v.req_id,
        v.req_user_id,
        v.device_ifa,
        v.media,
        v.inventory_type,
        v.ad_type,
        v.connection_type,
        v.ts,
        v.year
    FROM raw_visit v
    JOIN propfit_media_top500 r ON v.media = r.media
),
flagged AS (
    SELECT
        t.*,
        LAG(media) OVER (PARTITION BY req_user_id ORDER BY ts, req_id) AS prev_media,
        LAG(ts)    OVER (PARTITION BY req_user_id ORDER BY ts, req_id) AS prev_ts
    FROM top500 t
)
SELECT
    req_id,
    req_user_id,
    device_ifa,
    media,
    inventory_type,
    ad_type,
    connection_type,
    ts,
    year
FROM flagged
WHERE prev_media IS NULL
   OR prev_media <> media
   OR date_diff('second', prev_ts, ts) >= 1800
;
