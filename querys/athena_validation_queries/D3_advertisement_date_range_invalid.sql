-- D3. advertisement: 시작일 > 종료일 (날짜 역전)
-- 기대값: 0 rows
SELECT adspid, startdt, enddt
FROM "ptbwa-metadata".addi_advertisement
WHERE date_parse(startdt, '%Y-%m-%d %H:%i:%s') > date_parse(enddt, '%Y-%m-%d %H:%i:%s');
