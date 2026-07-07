-- A4. business: 핵심 컬럼 결측률
-- 기대값: null_businessid/businessnum/businessnm = 0
-- 마스터 데이터(스냅샷)라 2026-06-01~06-07 기간 필터는 적용하지 않았습니다.
SELECT
  count(*) AS total_rows,
  count_if(businessid  IS NULL OR trim(CAST(businessid AS VARCHAR)) = '')  AS null_businessid,
  count_if(businessnum IS NULL OR trim(CAST(businessnum AS VARCHAR)) = '') AS null_businessnum,
  count_if(businessnm  IS NULL OR trim(CAST(businessnm AS VARCHAR)) = '')  AS null_businessnm
FROM "ptbwa-metadata".addi_business;
