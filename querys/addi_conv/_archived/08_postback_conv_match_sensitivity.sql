-- ============================================================
-- 08_postback_conv_match_sensitivity.sql
-- 목적: "make-or-break" 쿼리 — 04~05월 postback 유저(ifa) 중 실제로 raw_conv_web(_imp)와
--       IP 매칭되는 유저가 몇 명/몇 %인지, 조건(시간창, cmp_no 일치 요구 여부)에 따라 어떻게
--       달라지는지 한 번에 본다. 이 결과로 (a) 학습 시드로 쓸 절대 양성 건수가 감당 가능한
--       수준인지, (b) cmp_no까지 요구했을 때 양성이 너무 줄어드는지, (c) 시간창을 얼마나
--       넓게 잡아야 하는지를 정한다.
-- 매칭 키: mall_ip = postback.ip, 방향: 항상 postback(광고 노출/참여) 이후에 mall_datetime이
--       와야 한다고 가정(정상적인 배너→방문 순서). 음수 시간차(전환이 postback보다 먼저 발생)는
--       전부 스킵 — 스퓨리어스 매칭(공유 IP 등)일 가능성이 높은 쪽이라 별도로 세보고 싶으면
--       hours_diff < 0 조건으로 재실행.
-- 컴플라이언스 필터는 적용하지 않음(사전 진단이라 상한선을 보는 목적, 실제 시드 SQL에는 적용 예정).
-- created_at이 timestamp 타입인지 'T' 구분자 varchar(ISO8601)인지 몰라서, 일단 VARCHAR로
-- 캐스팅 후 'T'를 공백으로 치환해서 다시 TIMESTAMP로 캐스팅한다(이미 timestamp 타입이면
-- 이 변환은 아무 영향 없음 — 왕복 실패 위험을 줄이기 위한 방어적 처리).
-- ============================================================

WITH postback_dedup AS (
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
    CAST(mall_datetime AS TIMESTAMP) AS mall_ts
  FROM "prod_addi_conv".raw_conv_web

  UNION ALL

  SELECT
    CAST(mall_ip AS VARCHAR) AS mall_ip,
    CAST(cmp_no AS VARCHAR) AS cmp_no,
    CAST(mall_datetime AS TIMESTAMP) AS mall_ts
  FROM "prod_addi_conv".raw_conv_web_imp
),
joined AS (
  SELECT
    p.ifa,
    (p.cmp_no = c.cmp_no) AS cmp_no_match,
    date_diff('hour', CAST(regexp_replace(CAST(p.first_created_at AS VARCHAR), 'T', ' ') AS TIMESTAMP), c.mall_ts) AS hours_diff
  FROM postback_dedup p
  JOIN conv c ON p.ip = c.mall_ip
  WHERE date_diff('hour', CAST(regexp_replace(CAST(p.first_created_at AS VARCHAR), 'T', ' ') AS TIMESTAMP), c.mall_ts) >= 0
)
SELECT
  (SELECT count(DISTINCT ifa) FROM postback_dedup) AS postback_distinct_ifa,

  count(DISTINCT ifa) AS ip_matched_ifa_any_window_any_cmp,
  count(DISTINCT CASE WHEN hours_diff <= 24  THEN ifa END) AS ip_matched_ifa_24h,
  count(DISTINCT CASE WHEN hours_diff <= 72  THEN ifa END) AS ip_matched_ifa_72h,
  count(DISTINCT CASE WHEN hours_diff <= 168 THEN ifa END) AS ip_matched_ifa_7d,
  count(DISTINCT CASE WHEN hours_diff <= 720 THEN ifa END) AS ip_matched_ifa_30d,

  count(DISTINCT CASE WHEN cmp_no_match THEN ifa END) AS ip_cmp_matched_ifa_any_window,
  count(DISTINCT CASE WHEN cmp_no_match AND hours_diff <= 72  THEN ifa END) AS ip_cmp_matched_ifa_72h,
  count(DISTINCT CASE WHEN cmp_no_match AND hours_diff <= 168 THEN ifa END) AS ip_cmp_matched_ifa_7d,
  count(DISTINCT CASE WHEN cmp_no_match AND hours_diff <= 720 THEN ifa END) AS ip_cmp_matched_ifa_30d
FROM joined;
