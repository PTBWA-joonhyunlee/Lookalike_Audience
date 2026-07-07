-- I3. adgroup.targetbillingid <-> addi_advertisement.targetbillingid 매칭 확인
-- I1/I2에서 실제 cmp_no/ag_no가 adcampaign/adgroup에 없더라도,
-- targetbillingid 컬럼이 두 테이블 모두에 있으니 이 경로로 연결될 가능성을 별도로 확인합니다.
SELECT
  count(*) AS adgroup_rows,
  count_if(g.targetbillingid IS NOT NULL AND trim(CAST(g.targetbillingid AS VARCHAR)) <> '') AS non_null_targetbillingid,
  count(DISTINCT g.targetbillingid) AS distinct_targetbillingid,
  count(DISTINCT a.adspid) AS matched_distinct_adspid
FROM "ptbwa-metadata".adgroup g
LEFT JOIN "ptbwa-metadata".addi_advertisement a
  ON CAST(g.targetbillingid AS VARCHAR) = CAST(a.targetbillingid AS VARCHAR)
WHERE g.targetbillingid IS NOT NULL AND trim(CAST(g.targetbillingid AS VARCHAR)) <> '';
