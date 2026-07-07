-- D2. advertisement.onoff 는 0/1 외 값이 없어야 함
-- 기대값: 0 rows
SELECT DISTINCT onoff, count(*) AS cnt
FROM "ptbwa-metadata".addi_advertisement
WHERE CAST(onoff AS VARCHAR) NOT IN ('0', '1')
GROUP BY onoff;
