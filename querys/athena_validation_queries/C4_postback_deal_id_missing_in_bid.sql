-- C4. postback_log에는 있는데 bid_log_flatten에는 없는 deal_id
-- (전환 로그가 입찰 로그보다 보관기간이 짧을 수 있음 - 참고용)
SELECT DISTINCT p.deal_id
FROM "prod-ptbwa-dw".addi_postback_log p
LEFT JOIN "prod-ptbwa-dw".addi_bid_log_flatten b
  ON p.deal_id = b.deal_id
  AND b.year = '2026' AND b.month = '06' AND b.day BETWEEN '01' AND '07'
WHERE p.year = '2026' AND p.month = '06' AND p.day BETWEEN '01' AND '07'
  AND b.deal_id IS NULL
  AND p.deal_id IS NOT NULL AND trim(CAST(p.deal_id AS VARCHAR)) <> ''
LIMIT 100;
