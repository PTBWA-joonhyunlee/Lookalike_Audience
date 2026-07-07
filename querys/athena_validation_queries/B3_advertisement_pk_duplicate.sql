-- B3. advertisement: adspid 중복 (PK 위반)
-- 기대값: 0 rows
SELECT adspid, count(*) AS dup_cnt
FROM "ptbwa-metadata".addi_advertisement
GROUP BY adspid
HAVING count(*) > 1;
