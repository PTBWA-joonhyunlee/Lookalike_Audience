-- ============================================================
-- 04_conv_web_row_counts.sql
-- 목적: raw_conv_web / raw_conv_web_imp 전체 row 수 + distinct mall_ip 수 확인 — 두 테이블의
--       규모를 가늠하고(파티션 없이 전체 스캔이라 비용이 크면 이후 쿼리에 기간 필터 추가 필요),
--       mall_ip 하나에 몰리는 이벤트 수(대형 쇼핑몰 서버 IP 등 아웃라이어)를 미리 확인한다.
-- 주의: 01에서 파티션 컬럼(year/month/day 등)이 확인되면, 이 쿼리도 기간 필터를 추가해 재실행할 것.
-- ============================================================

SELECT
  'raw_conv_web' AS table_name,
  count(*) AS total_rows,
  count(DISTINCT mall_ip) AS distinct_mall_ip,
  count_if(mall_ip IS NULL OR trim(CAST(mall_ip AS VARCHAR)) = '') AS null_mall_ip
FROM "prod_addi_conv".raw_conv_web

UNION ALL

SELECT
  'raw_conv_web_imp' AS table_name,
  count(*) AS total_rows,
  count(DISTINCT mall_ip) AS distinct_mall_ip,
  count_if(mall_ip IS NULL OR trim(CAST(mall_ip AS VARCHAR)) = '') AS null_mall_ip
FROM "prod_addi_conv".raw_conv_web_imp;
