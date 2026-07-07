-- L2. addi_bid_log_flatten과 abi_bid_log_flatten이 req_user_id로 실제 매핑되는지 확인
-- 주의: abi_bid_log_flatten의 컬럼명이 req_user_id/device_ifa와 다르게 나올 수 있습니다.
-- L1 결과에서 실제 컬럼명이 다르면 아래 컬럼명만 그에 맞게 바꿔서 재실행하세요.
-- 파티션 컬럼명(year/month/day 여부)도 L1 DESCRIBE 결과를 보고 필요시 수정하세요.

WITH addi AS (
  SELECT DISTINCT req_user_id
  FROM "prod-ptbwa-dw".addi_bid_log_flatten
  WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
    AND req_user_id IS NOT NULL AND trim(CAST(req_user_id AS VARCHAR)) <> ''
),
abi AS (
  SELECT DISTINCT req_user_id
  FROM "prod-ptbwa-dw".abi_bid_log_flatten
  WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
    AND req_user_id IS NOT NULL AND trim(CAST(req_user_id AS VARCHAR)) <> ''
)
SELECT
  (SELECT count(*) FROM addi) AS addi_distinct_req_user_id,
  (SELECT count(*) FROM abi) AS abi_distinct_req_user_id,
  (SELECT count(*) FROM addi a JOIN abi b ON a.req_user_id = b.req_user_id) AS overlap_req_user_id;
