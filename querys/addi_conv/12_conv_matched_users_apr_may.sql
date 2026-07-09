-- ============================================================
-- 12_conv_matched_users_apr_may.sql
-- 목적: 재학습용 "층화 pool" 조립의 첫 단계 — 4~5월 postback 유저 중 IP+cmp_no 매칭된 유저
--       (양성 후보)의 req_user_id/device_ifa 목록. 08_postback_conv_match_sensitivity.sql은
--       개수만 셌는데(412명, IP+cmp_no, 무제한 시간창), 이번엔 실제 유저 목록이 필요하다 —
--       이 목록으로 13/14(전수 프로필/미디어 방문)를 뽑고, scoring.build_stratified_pool로
--       기존 5% 샘플 pool에 병합한다.
-- 매칭 정의: mall_ip=postback.ip AND cmp_no 일치, 시간창 제한 없음(08번 사전진단에서 확인된
--       조건 중 "IP+cmp_no, 무제한 시간창" — 학습 라벨은 백테스트보다 정밀도가 더 중요해서
--       cmp_no를 요구하되, 표본이 워낙 작아 시간창은 제한하지 않는다. 09/README §2-5와 같은
--       원칙).
-- 이 쿼리의 결과가 곧 03_seed_interested_users_apr_may.sql을 대체할 새 시드 후보다(아직 03
--       파일 자체는 안 바꿨음 — 검토 후 별도로 교체 예정).
-- ============================================================

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
),
matched_ifa AS (
  SELECT DISTINCT p.ifa
  FROM postback_ip p
  JOIN conv c
    ON p.ip = c.mall_ip
   AND p.cmp_no = c.cmp_no
  WHERE date_diff(
      'hour',
      CAST(regexp_replace(CAST(p.first_created_at AS VARCHAR), 'T', ' ') AS TIMESTAMP),
      c.mall_ts
    ) >= 0
)
SELECT DISTINCT
  b.req_user_id,
  m.ifa AS device_ifa
FROM matched_ifa m
JOIN "prod-ptbwa-dw".addi_bid_log_flatten b ON b.device_ifa = m.ifa
WHERE b.year = '2026' AND b.month IN ('04', '05')
  AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
  AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
  AND b.req_user_id IS NOT NULL AND trim(CAST(b.req_user_id AS VARCHAR)) <> '';
