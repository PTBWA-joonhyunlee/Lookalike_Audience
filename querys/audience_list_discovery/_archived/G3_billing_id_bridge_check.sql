-- G3. advertisement(adspid) <-> 로그 테이블을 연결하는 브릿지 컬럼 검증
--
-- 초기 샘플 데이터에서 아래와 같은 패턴이 우연히 일치했습니다 (검증 필요):
--   postback_log.g_targetid  ==  advertisement.targetbillingid
--   postback_log.deal_id     이  advertisement.targetdealnogab (콤마로 구분된 목록) 안에 포함
-- 이 가설이 맞다면 postback_log -> advertisement -> businessid 로 캠페인을 특정 광고(adspid)에
-- 매핑할 수 있습니다. bid_log_flatten.ext_billing_id 도 같은 역할을 하는지 함께 확인합니다.

-- G3-1. postback_log.g_targetid 가 advertisement.targetbillingid 와 얼마나 매칭되는지
SELECT
  count(*) AS postback_rows,
  count(DISTINCT p.g_targetid) AS distinct_g_targetid,
  count_if(a.adspid IS NOT NULL) AS matched_rows,
  count(DISTINCT CASE WHEN a.adspid IS NOT NULL THEN p.g_targetid END) AS matched_distinct_g_targetid
FROM "prod-ptbwa-dw".addi_postback_log p
LEFT JOIN "ptbwa-metadata".addi_advertisement a
  ON CAST(p.g_targetid AS VARCHAR) = CAST(a.targetbillingid AS VARCHAR)
WHERE p.year = '2026' AND p.month = '06' AND p.day BETWEEN '01' AND '07'
  AND p.g_targetid IS NOT NULL AND trim(CAST(p.g_targetid AS VARCHAR)) <> '';

-- G3-2. postback_log.deal_id 가 advertisement.targetdealnogab 안에 포함되는 비율
-- targetdealnogab도 ext_billing_id처럼 실제로는 array(varchar)일 가능성이 높아 contains()로 작성.
-- 만약 이 컬럼이 진짜 varchar(콤마 구분 문자열)라면 아래 에러가 납니다:
--   FUNCTION_NOT_FOUND / TYPE_MISMATCH: contains 함수는 array 인자가 필요합니다
-- 그 경우 알려주시면 regexp_like 버전으로 바꿔드리겠습니다.
SELECT
  count(*) AS postback_rows,
  count_if(
    a.targetdealnogab IS NOT NULL
    AND contains(a.targetdealnogab, CAST(p.deal_id AS VARCHAR))
  ) AS matched_rows_via_targetdealnogab
FROM "prod-ptbwa-dw".addi_postback_log p
LEFT JOIN "ptbwa-metadata".addi_advertisement a
  ON CAST(p.g_targetid AS VARCHAR) = CAST(a.targetbillingid AS VARCHAR)
WHERE p.year = '2026' AND p.month = '06' AND p.day BETWEEN '01' AND '07'
  AND p.deal_id IS NOT NULL AND trim(CAST(p.deal_id AS VARCHAR)) <> '';

-- G3-3. bid_log_flatten.ext_billing_id 채움 여부
-- 실제 타입은 array(varchar) (스칼라 아님) - cardinality로 빈 배열 여부 확인
SELECT
  count(*) AS bid_rows,
  count_if(ext_billing_id IS NOT NULL AND cardinality(ext_billing_id) > 0) AS non_empty_ext_billing_id_rows
FROM "prod-ptbwa-dw".addi_bid_log_flatten
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07';

-- G3-4. ext_billing_id 배열 안의 distinct billing id 값 (UNNEST로 풀어서 집계)
WITH bid_billing AS (
  SELECT DISTINCT billing_id
  FROM "prod-ptbwa-dw".addi_bid_log_flatten
  CROSS JOIN UNNEST(ext_billing_id) AS t(billing_id)
  WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
    AND ext_billing_id IS NOT NULL AND cardinality(ext_billing_id) > 0
)
SELECT
  count(*) AS distinct_billing_ids_in_bid_log,
  count_if(a.adspid IS NOT NULL) AS matched_distinct_billing_ids
FROM bid_billing bb
LEFT JOIN "ptbwa-metadata".addi_advertisement a
  ON bb.billing_id = CAST(a.targetbillingid AS VARCHAR);
