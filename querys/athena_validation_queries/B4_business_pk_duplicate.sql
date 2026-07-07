-- B4. business: businessid 중복 (PK 위반)
-- 기대값: 0 rows
SELECT businessid, count(*) AS dup_cnt
FROM "ptbwa-metadata".addi_business
GROUP BY businessid
HAVING count(*) > 1;
