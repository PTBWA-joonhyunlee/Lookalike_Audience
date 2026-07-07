-- L3. req_user_id 오버랩이 0으로 나온 것을 보고, 더 로우레벨 식별자인 device_ifa 기준으로도
-- addi_bid_log_flatten과 abi_bid_log_flatten이 겹치는 디바이스가 있는지 재확인.
-- (같은 물리 디바이스가 두 파이프라인 모두에서 노출된 적이 있는지 = 크로스 소스 피처 결합 가능성)

WITH addi AS (
  SELECT DISTINCT device_ifa
  FROM "prod-ptbwa-dw".addi_bid_log_flatten
  WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
    AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
    AND regexp_like(CAST(device_ifa AS VARCHAR), '^[0-9a-fA-F-]{36}$')
),
abi AS (
  SELECT DISTINCT device_ifa
  FROM "prod-ptbwa-dw".abi_bid_log_flatten
  WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
    AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
    AND regexp_like(CAST(device_ifa AS VARCHAR), '^[0-9a-fA-F-]{36}$')
)
SELECT
  (SELECT count(*) FROM addi) AS addi_distinct_device_ifa,
  (SELECT count(*) FROM abi) AS abi_distinct_device_ifa,
  (SELECT count(*) FROM addi a JOIN abi b ON a.device_ifa = b.device_ifa) AS overlap_device_ifa;
