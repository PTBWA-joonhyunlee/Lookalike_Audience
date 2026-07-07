-- ============================================================
-- 04_new_users_top500_media_visit_jun.sql
-- 목적   : 2026-06 스코어링 대상 "신규 유저"의 미디어 방문 이벤트 (media_sequence 추론 입력).
--          "신규 유저" = 2026-04~05 addi_bid_log_flatten에 전혀 등장하지 않다가 2026-06에
--          처음 나타난 req_user_id.
-- 01_top500_media_visit.sql(학습용)과의 차이:
--   1) top500 미디어 재필터링을 하지 않는다 — 학습(04-05) 시점에 fit된 vocab_media.json이
--      이미 있고, 그 vocab에 없는 미디어는 자동으로 <UNK>로 인코딩된다. 추론 단계에서 6월
--      데이터만으로 새로 상위 500개를 뽑으면 학습 때와 다른 media 집합이 되어 vocab과
--      어긋나므로 재필터링하지 않는다 (embedding-spec-top500-media-visit.md §7 로직 참고).
--   2) 대상 기간이 2026-06 전체, req_user_id가 04-05월 bid log에 없는 경우만 포함.
--   30분 재방문 제거(세션 dedup)는 데이터 품질 문제라 학습/추론 동일하게 적용한다.
-- 샘플링 : 01/02와 동일한 이유로(전체 트래픽, 데이터량 과다) 유저 단위 5% 샘플링을 적용했다.
--          지금은 파일럿 단계라 스코어링 대상도 함께 축소 — 실제 후보 리스트를 산출할 때는
--          이 조건을 제거하고 전체 신규 유저로 재실행해야 한다.
-- media 컬럼 재정의 (2026-07-07): 01_top500_media_visit.sql과 동일하게 app_bundle 대신
--          app_content_genre의 대표(첫) 장르 토큰을 쓴다 — 학습 때 fit한 vocab_media.json과
--          같은 값 체계여야 하므로 반드시 01과 동일한 방식으로 맞춘다 (01 상단 주석 참고).
-- ============================================================

WITH prior_users AS (
    -- 04-05월에 이미 등장했던 req_user_id (신규 유저 판정 기준)
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
        CAST(NULL AS INTEGER) AS connection_type,  -- addi_bid_log_flatten에는 없는 컬럼 (01과 동일 사유)
        CAST(from_iso8601_timestamp(CAST(b.created_at AS VARCHAR)) AT TIME ZONE 'Asia/Seoul' AS timestamp) AS ts,
        b.year
    FROM "prod-ptbwa-dw"."addi_bid_log_flatten" b
    LEFT JOIN prior_users p ON b.req_user_id = p.req_user_id
    WHERE b.year = '2026' AND b.month = '06'
      AND b.req_user_id IS NOT NULL AND trim(CAST(b.req_user_id AS VARCHAR)) <> ''
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
      AND p.req_user_id IS NULL   -- ← 04-05월에 없었던 유저만 (신규 유저 필터)
      AND mod(crc32(to_utf8(CAST(b.req_user_id AS VARCHAR))), 100) < 5   -- ← 유저 단위 5% 샘플링 (파일럿 단계, 실제 후보 산출 시 제거)
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
