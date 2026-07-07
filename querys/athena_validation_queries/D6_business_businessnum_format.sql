-- D6. business.businessnum 형식 체크 (숫자 10자리, 하이픈 없이 저장된다는 가정)
-- 기대값: 0 rows
SELECT businessid, businessnum
FROM "ptbwa-metadata".addi_business
WHERE NOT regexp_like(CAST(businessnum AS VARCHAR), '^[0-9]{10}$');
