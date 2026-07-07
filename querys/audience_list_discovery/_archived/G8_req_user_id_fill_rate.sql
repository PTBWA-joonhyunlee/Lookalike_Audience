-- G8. req_user_id 실제 채움 여부 확인
-- 샘플 10건에서는 전부 NULL이었음 - 디바이스ID(device_ifa)보다 안정적인 유저 식별자로 쓸 수 있는지 확인
SELECT
  count(*) AS total_rows,
  count_if(req_user_id IS NOT NULL AND trim(CAST(req_user_id AS VARCHAR)) <> '') AS non_null_req_user_id,
  count(DISTINCT req_user_id) AS distinct_req_user_id
FROM "prod-ptbwa-dw".addi_bid_log_flatten
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07';
