-- G4. bid_log_flatten.device_ifa 와 postback_log.ifa 가 같은 식별자 체계인지(조인 가능한지) 검증
-- 기대: overlapping_ifa 가 postback_distinct_ifa 대비 높은 비율로 나와야 두 컬럼을 조인 키로 신뢰 가능
SELECT
  (SELECT count(DISTINCT device_ifa) FROM "prod-ptbwa-dw".addi_bid_log_flatten
     WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
       AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> '') AS bid_distinct_ifa,
  (SELECT count(DISTINCT ifa) FROM "prod-ptbwa-dw".addi_postback_log
     WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
       AND ifa IS NOT NULL AND trim(CAST(ifa AS VARCHAR)) <> '') AS postback_distinct_ifa,
  (SELECT count(DISTINCT b.device_ifa)
     FROM "prod-ptbwa-dw".addi_bid_log_flatten b
     JOIN "prod-ptbwa-dw".addi_postback_log p ON CAST(b.device_ifa AS VARCHAR) = CAST(p.ifa AS VARCHAR)
     WHERE b.year = '2026' AND b.month = '06' AND b.day BETWEEN '01' AND '07'
       AND p.year = '2026' AND p.month = '06' AND p.day BETWEEN '01' AND '07'
  ) AS overlapping_ifa;
