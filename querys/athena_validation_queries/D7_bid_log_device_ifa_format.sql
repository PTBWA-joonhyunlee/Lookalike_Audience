-- D7. bid_log_flatten.device_ifa 가 UUID 형식이 아닌 값 (값이 있는 행 기준)
-- 기대값: 0 rows
SELECT req_id, device_ifa
FROM "prod-ptbwa-dw".addi_bid_log_flatten
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
  AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
  AND NOT regexp_like(CAST(device_ifa AS VARCHAR), '^[0-9a-fA-F-]{36}$');
