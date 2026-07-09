-- ============================================================
-- 14_conv_matched_users_media_visit_apr_may.sql
-- 목적: 13번과 짝을 이루는 media_sequence 추론 입력 — 12번에서 뽑은 IP+cmp_no 매칭 유저의
--       미디어 방문 이벤트를 5% 샘플링 없이 전수 조회한다. 11_postback_users_media_visit_jun.sql
--       과 로직은 같고(top500 재필터링 없음 — 학습 때 fit된 vocab_media.json 재사용, 30분
--       재방문 세션 dedup 동일 적용) 대상 유저 목록과 기간(4~5월)만 다르다.
-- ============================================================

WITH matched_ifa AS (
  -- 12/13과 동일한 정의(중복 정의) — 12번 결과 CSV의 device_ifa와 같은 집합이어야 한다.
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
raw_visit AS (
    SELECT
        b.req_id,
        b.req_user_id,
        b.device_ifa,
        NULLIF(SPLIT_PART(CAST(b.app_content_genre AS VARCHAR), ',', 1), '') AS media,
        NULLIF(CAST(b.app_content_genre AS VARCHAR), '') AS content_genre,
        NULLIF(CAST(b.imp_ad_type AS VARCHAR), '')  AS ad_type,
        CAST(NULL AS INTEGER) AS connection_type,  -- addi_bid_log_flatten에는 없는 컬럼 (01/04/11과 동일 사유)
        CAST(from_iso8601_timestamp(CAST(b.created_at AS VARCHAR)) AT TIME ZONE 'Asia/Seoul' AS timestamp) AS ts,
        b.year
    FROM "prod-ptbwa-dw"."addi_bid_log_flatten" b
    JOIN matched_ifa m ON b.device_ifa = m.device_ifa
    WHERE b.year = '2026' AND b.month IN ('04', '05')
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
