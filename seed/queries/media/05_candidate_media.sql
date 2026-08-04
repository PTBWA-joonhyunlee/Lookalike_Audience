/* ============================================================
   media/05_candidate_media.sql (seed, 2026-08-04 segment/media 트랙 분리 — 구
   07d_media_candidate_media.sql)
   02_pool_media.sql/03_seed_media.sql과 동일 로직, device_ifa를
   candidates_202606_media_sample(04_create_candidate_table_media.sql, media 활동
   기준으로 뽑은 후보 — 현재는 표본 추출 없이 필터 후 전체 804,606명)로 제한한다.
   propfit_media_top500(01, 학습 때와 같은 vocab)을 그대로 참조 — 자체 top500 재계산
   금지(학습 모델과 다른 vocab이 되면 전부 OOV로 깨짐). 기간은 2026-06, 전수 추출.

   이 후보군은 segment 스코어링은 하지 않는다(media 단독 트랙 전용) — media 단독
   임베딩/스코어링에만 쓴다.

   2026-08-03 수정(region=KR/OS=Android 필터 추가): 04에서 이미 region=KR/OS=Android로
   후보(candidates_202606_media_sample)를 제한했지만, 이 쿼리도 독립적으로 같은 조건을
   명시해 다른 candidate 테이블에 재사용될 때도 안전하게 한다.
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
    JOIN candidates_202606_media_sample c ON v.device_ifa = c.device_ifa
    WHERE v.year = '2026' AND v.month = '06'
      AND v.req_user_id IS NOT NULL AND trim(CAST(v.req_user_id AS VARCHAR)) <> ''
      AND CAST(v.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (v.device_lmt IS NULL OR CAST(v.device_lmt AS VARCHAR) <> '1')
      AND CAST(v.device_geo_region AS VARCHAR) LIKE 'KR%'
      AND regexp_like(CAST(v.device_osv AS VARCHAR), '^[0-9]+$')
),
top500 AS (
    SELECT
        v.req_id, v.req_user_id, v.device_ifa, v.media,
        v.inventory_type, v.ad_type, v.connection_type, v.ts, v.year
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
    req_id, req_user_id, device_ifa, media, inventory_type, ad_type, connection_type, ts, year
FROM flagged
WHERE prev_media IS NULL
   OR prev_media <> media
   OR date_diff('second', prev_ts, ts) >= 1800
;
