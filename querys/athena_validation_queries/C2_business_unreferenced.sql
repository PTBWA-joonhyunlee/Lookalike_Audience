-- C2. 어떤 advertisement에서도 참조되지 않는 사업자 (정상일 수 있음 - 참고용)
SELECT b.businessid, b.businessnm
FROM "ptbwa-metadata".addi_business b
LEFT JOIN "ptbwa-metadata".addi_advertisement a
  ON a.businessid = b.businessid
WHERE a.businessid IS NULL;
