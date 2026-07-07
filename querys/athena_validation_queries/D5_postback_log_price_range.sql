-- D5. postback_log: price/base_price 음수값
-- 기대값: 0 rows
SELECT req_id, price, base_price
FROM "prod-ptbwa-dw".addi_postback_log
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
  AND (try_cast(price AS DOUBLE) < 0
   OR try_cast(base_price AS DOUBLE) < 0);
