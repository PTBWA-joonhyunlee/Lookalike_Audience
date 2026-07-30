/* ============================================================
   03_create_media_vocab_table.sql (seed, 구 04_create_media_vocab_table.sql)
   목적: 02_user_media.sql(propfit)의 top500 미디어 vocab을 seed/pool 양쪽이 공유하는
   테이블로 한 번만 만든다.

   왜 필요한가: 02_user_media.sql은 조회 대상 population 안에서 top500을 자체 계산한다
   (media_rank CTE). 이걸 seed(93만 명, 특정 브랜드 관심 유저)와 pool(전체 모집단)에서
   각각 따로 계산하면 top500 미디어 목록 자체가 달라질 수 있다 — media_sequence 임베딩
   모델은 하나의 고정 vocab을 학습하므로, seed/pool이 서로 다른 vocab으로 추출되면 한쪽
   데이터의 미디어 값 상당수가 다른 쪽 모델 기준으로는 OOV(미학습 토큰)가 된다. 그래서
   top500은 전체 모집단(seed로 좁히지 않은 전체 bid log) 기준으로 한 번만 계산해 이
   테이블로 고정하고, 05b(seed media)/향후 pool media 쿼리 둘 다 이 테이블을 그대로
   참조한다(자체 재계산 안 함).

   기간/컴플라이언스 필터는 01/02와 동일(2026-04~05, 동의+LMT).
   ============================================================ */

CREATE TABLE propfit_media_top500
WITH (format = 'PARQUET')
AS
WITH raw_visit AS (
    SELECT
        req_id,
        COALESCE(
            NULLIF(CAST(app_bundle AS VARCHAR), ''),
            NULLIF(CAST(site_page AS VARCHAR), '')
        ) AS media
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')
      AND req_user_id IS NOT NULL
      AND trim(CAST(req_user_id AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
)
SELECT
    media,
    COUNT(DISTINCT req_id) AS req_cnt
FROM raw_visit
WHERE media IS NOT NULL
GROUP BY media
ORDER BY req_cnt DESC
LIMIT 500;
