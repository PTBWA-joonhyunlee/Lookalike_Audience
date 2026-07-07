-- F1. 일자별 bid 요청 수 vs postback 이벤트 수 추이 비교 (급격한 비율 변화 탐지용)
-- 기간: 2026-06-01 ~ 2026-06-07
WITH bid AS (
  SELECT year, month, day, req_id
  FROM "prod-ptbwa-dw".addi_bid_log_flatten
  WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
),
postback AS (
  SELECT year, month, day, req_id
  FROM "prod-ptbwa-dw".addi_postback_log
  WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
)
SELECT
  coalesce(b.year, p.year)   AS year,
  coalesce(b.month, p.month) AS month,
  coalesce(b.day, p.day)     AS day,
  count(DISTINCT b.req_id) AS bid_req_cnt,
  count(DISTINCT p.req_id) AS postback_req_cnt
FROM bid b
FULL OUTER JOIN postback p
  ON b.req_id = p.req_id AND b.year = p.year AND b.month = p.month AND b.day = p.day
GROUP BY coalesce(b.year, p.year), coalesce(b.month, p.month), coalesce(b.day, p.day)
ORDER BY 1, 2, 3;
