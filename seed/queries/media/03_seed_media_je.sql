/* ============================================================
   media/03_seed_media_je.sql (seed, je 신규 seed — 03_seed_media.sql[피엘라벤]과 동일
   로직, device_ifa만 seed_je_ad_id로 교체)
   배경: 28_seed_je_id_space_check.sql 결과(2026-08-19) — seed_je는 크로스워크 없이 이미
   raw GAID 공간이라 seed_je_ad_id(02_create_seed_ad_id_table_je.sql)를 그대로 조인한다.
   pool/candidate는 기존 것(피엘라벤 트랙에서 이미 뽑아둔 pool_media/candidates_202606_media
   등)을 그대로 재사용하기로 했으므로(je seed 규모가 1,922명뿐이라 pool을 새로 뽑을
   필요가 없다는 판단), 이 파일은 seed 쪽 피처만 새로 뽑는다. top500 미디어 vocab도
   01_create_media_vocab_table.sql로 만든 propfit_media_top500(전체 모집단 기준)을 그대로
   참조— 새로 계산하지 않는다(vocab 불일치 방지). 전수 추출 — pool과 달리 최소 활동량
   조건 없음(seed는 원래 활동량이 충분히 많다고 가정, 모델 레벨 MIN_SEQ_LEN=5로 필터됨).
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
    JOIN seed_je_ad_id sd ON v.device_ifa = sd.device_ifa
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
