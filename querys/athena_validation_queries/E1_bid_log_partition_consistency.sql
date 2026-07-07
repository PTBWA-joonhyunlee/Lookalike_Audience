-- E1. bid_log_flatten: year/month/day/hour 컬럼이 created_at과 불일치
-- 기대값: 0 rows
SELECT req_id, created_at, year, month, day, hour
FROM "prod-ptbwa-dw".addi_bid_log_flatten
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
  AND (year  <> date_format(from_iso8601_timestamp(created_at), '%Y')
   OR month <> date_format(from_iso8601_timestamp(created_at), '%m')
   OR day   <> date_format(from_iso8601_timestamp(created_at), '%d')
   OR hour  <> date_format(from_iso8601_timestamp(created_at), '%H'));
