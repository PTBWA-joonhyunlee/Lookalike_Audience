-- F2. media_id 기준 bid 로그와 postback 로그의 매체 커버리지 차집합
SELECT media_id, 'bid_only' AS source
FROM "prod-ptbwa-dw".addi_bid_log_flatten
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
EXCEPT
SELECT media_id, 'bid_only'
FROM "prod-ptbwa-dw".addi_postback_log
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07';
