-- D4. bid_log_flatten: price가 음수이거나 bidfloor보다 낮은 낙찰가
-- 기대값: 0 rows
SELECT req_id, imp_id, price, imp_bidfloor
FROM "prod-ptbwa-dw".addi_bid_log_flatten
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
  AND (try_cast(price AS DOUBLE) < 0
   OR (try_cast(price AS DOUBLE) IS NOT NULL
       AND try_cast(imp_bidfloor AS DOUBLE) IS NOT NULL
       AND try_cast(price AS DOUBLE) < try_cast(imp_bidfloor AS DOUBLE)));
