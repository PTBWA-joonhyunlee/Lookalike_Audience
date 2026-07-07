-- C1. advertisement.businessid 중 business 테이블에 없는 고아 레코드
-- 기대값: 0 rows
SELECT a.adspid, a.businessid
FROM "ptbwa-metadata".addi_advertisement a
LEFT JOIN "ptbwa-metadata".addi_business b
  ON a.businessid = b.businessid
WHERE b.businessid IS NULL
  AND a.businessid IS NOT NULL AND trim(CAST(a.businessid AS VARCHAR)) <> '';
