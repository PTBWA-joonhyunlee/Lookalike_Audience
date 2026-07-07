-- B1. bid_log_flatten: (req_id, imp_id) 중복 행
-- 기대값: 0 rows
SELECT req_id, imp_id, count(*) AS dup_cnt
FROM "prod-ptbwa-dw".addi_bid_log_flatten
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
GROUP BY req_id, imp_id
HAVING count(*) > 1
ORDER BY dup_cnt DESC
LIMIT 100;
