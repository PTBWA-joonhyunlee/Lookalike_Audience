-- C5. bid_log_flatten.imp_deals_array 안의 id 값이 실제 deal_id 컬럼과 일치하는지 (내부 정합성)
-- imp_deals_array 실제 타입: array(row(id varchar, bidfloorcur varchar, bidfloor double))
-- 기대값: 0 rows
SELECT req_id, imp_id, deal_id, imp_deals_array
FROM "prod-ptbwa-dw".addi_bid_log_flatten
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
  AND deal_id IS NOT NULL AND trim(CAST(deal_id AS VARCHAR)) <> ''
  AND NOT coalesce(
        any_match(imp_deals_array, x -> x.id = CAST(deal_id AS VARCHAR)),
        false
      );
