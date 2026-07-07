-- B2. postback_log: 완전 동일 이벤트 중복 (같은 이벤트가 두 번 적재됐는지)
-- 기대값: 0 rows
SELECT req_id, log_type, created_at, count(*) AS dup_cnt
FROM "prod-ptbwa-dw".addi_postback_log
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
GROUP BY req_id, log_type, created_at
HAVING count(*) > 1
ORDER BY dup_cnt DESC
LIMIT 100;
