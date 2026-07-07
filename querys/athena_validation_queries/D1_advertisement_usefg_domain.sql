-- D1. advertisement.usefg 는 'Y'/'N' 외 값이 없어야 함
-- 기대값: 0 rows
SELECT DISTINCT usefg, count(*) AS cnt
FROM "ptbwa-metadata".addi_advertisement
WHERE usefg NOT IN ('Y', 'N')
GROUP BY usefg;
