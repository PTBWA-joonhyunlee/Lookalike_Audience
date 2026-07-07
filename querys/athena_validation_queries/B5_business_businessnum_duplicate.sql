-- B5. business: businessnum(사업자등록번호) 중복 - 동일 사업자가 여러 businessid로 등록됐는지
SELECT businessnum, count(DISTINCT businessid) AS distinct_businessid_cnt, count(*) AS row_cnt
FROM "ptbwa-metadata".addi_business
GROUP BY businessnum
HAVING count(DISTINCT businessid) > 1;
