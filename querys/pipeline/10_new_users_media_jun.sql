-- ============================================================
-- 10_new_users_media_jun.sql
-- 목적: 09_new_users_profile_jun.sql과 짝을 이루는 media_sequence 추론 입력 — 2026-06 신규
--       유저(4~5월 bid log에 없던 유저) 전원의 미디어 방문 이벤트. top500 재필터링 없음
--       (학습 때 fit된 vocab_media.json 재사용), 30분 재방문 세션 dedup은 pool과 동일 적용.
--       샘플링 없음(09번 파일 상단 주석과 같은 이유).
-- media 컬럼은 01/02와 동일하게 app_bundle이 아니라 app_content_genre 대표(첫) 장르 토큰.
-- ============================================================

WITH prior_users AS (
    SELECT DISTINCT req_user_id
    FROM "prod-ptbwa-dw"."addi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')
      AND req_user_id IS NOT NULL AND trim(CAST(req_user_id AS VARCHAR)) <> ''
),
raw_visit AS (
    SELECT
        b.req_id,
        b.req_user_id,
        b.device_ifa,
        NULLIF(SPLIT_PART(CAST(b.app_content_genre AS VARCHAR), ',', 1), '') AS media,
        NULLIF(CAST(b.app_content_genre AS VARCHAR), '') AS content_genre,
        NULLIF(CAST(b.imp_ad_type AS VARCHAR), '')  AS ad_type,
        CAST(NULL AS INTEGER) AS connection_type,  -- addi_bid_log_flatten에는 없는 컬럼 (01/02와 동일 사유)
        CAST(from_iso8601_timestamp(CAST(b.created_at AS VARCHAR)) AT TIME ZONE 'Asia/Seoul' AS timestamp) AS ts,
        b.year
    FROM "prod-ptbwa-dw"."addi_bid_log_flatten" b
    LEFT JOIN prior_users p ON b.req_user_id = p.req_user_id
    WHERE b.year = '2026' AND b.month = '06'
      AND b.req_user_id IS NOT NULL AND trim(CAST(b.req_user_id AS VARCHAR)) <> ''
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
      AND p.req_user_id IS NULL   -- ← 4~5월에 없었던 유저만 (신규 유저 필터)
),
flagged AS (
    SELECT
        t.*,
        LAG(media) OVER (PARTITION BY req_user_id ORDER BY ts, req_id) AS prev_media,
        LAG(ts)    OVER (PARTITION BY req_user_id ORDER BY ts, req_id) AS prev_ts
    FROM raw_visit t
    WHERE media IS NOT NULL
)
SELECT
    req_id,
    req_user_id,
    device_ifa,
    media,
    content_genre,
    ad_type,
    connection_type,
    ts,
    year
FROM flagged
WHERE prev_media IS NULL
   OR prev_media <> media
   OR date_diff('second', prev_ts, ts) >= 1800
;
