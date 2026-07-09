-- ============================================================
-- 11_postback_users_media_visit_jun.sql
-- 목적: 10_postback_users_profile_jun.sql과 짝을 이루는 media_sequence 추론 입력 —
--       2026-06 postback 발생 유저 전원의 미디어 방문 이벤트. 04_new_users_top500_media_visit_
--       jun.sql과 로직은 동일(top500 재필터링 없음 — 학습 때 fit된 vocab_media.json 사용,
--       30분 재방문 세션 dedup 동일 적용)하되, "신규 유저" 제한과 5% 샘플링을 뺐다
--       (10번 파일 상단 주석과 같은 이유).
-- media 컬럼은 01/04와 동일하게 app_bundle이 아니라 app_content_genre 대표(첫) 장르 토큰.
-- ============================================================

WITH postback_ifa AS (
    SELECT DISTINCT ifa AS device_ifa
    FROM "prod-ptbwa-dw"."addi_postback_log"
    WHERE year = '2026' AND month = '06'
      AND ifa IS NOT NULL AND trim(CAST(ifa AS VARCHAR)) <> ''
),
raw_visit AS (
    SELECT
        b.req_id,
        b.req_user_id,
        b.device_ifa,
        NULLIF(SPLIT_PART(CAST(b.app_content_genre AS VARCHAR), ',', 1), '') AS media,
        NULLIF(CAST(b.app_content_genre AS VARCHAR), '') AS content_genre,
        NULLIF(CAST(b.imp_ad_type AS VARCHAR), '')  AS ad_type,
        CAST(NULL AS INTEGER) AS connection_type,  -- addi_bid_log_flatten에는 없는 컬럼 (01/04와 동일 사유)
        CAST(from_iso8601_timestamp(CAST(b.created_at AS VARCHAR)) AT TIME ZONE 'Asia/Seoul' AS timestamp) AS ts,
        b.year
    FROM "prod-ptbwa-dw"."addi_bid_log_flatten" b
    JOIN postback_ifa p ON b.device_ifa = p.device_ifa
    WHERE b.year = '2026' AND b.month = '06'
      AND b.req_user_id IS NOT NULL AND trim(CAST(b.req_user_id AS VARCHAR)) <> ''
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
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
