-- A3. advertisement: 핵심 컬럼 결측률
-- 기대값: null_adspid = 0, null_businessid = 0
-- 마스터 데이터(스냅샷)라 2026-06-01~06-07 기간 필터는 적용하지 않았습니다.
SELECT
  count(*) AS total_rows,
  count_if(adspid     IS NULL OR trim(CAST(adspid AS VARCHAR)) = '')     AS null_adspid,
  count_if(businessid IS NULL OR trim(CAST(businessid AS VARCHAR)) = '') AS null_businessid,
  count_if(startdt    IS NULL OR trim(CAST(startdt AS VARCHAR)) = '')    AS null_startdt,
  count_if(enddt      IS NULL OR trim(CAST(enddt AS VARCHAR)) = '')      AS null_enddt,
  count_if(status     IS NULL OR trim(CAST(status AS VARCHAR)) = '')     AS null_status
FROM "ptbwa-metadata".addi_advertisement;
