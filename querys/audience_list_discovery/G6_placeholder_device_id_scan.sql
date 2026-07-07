-- G6. placeholder/test 성 디바이스 식별자가 전체 기간에 얼마나 있는지 스캔
-- (7일치 샘플 검증에서 {PSID}, test_* 값이 발견됨 -> 전체 규모 파악용)

-- G6-1. bid_log_flatten.device_ifa
SELECT
  count(*) AS total_rows,
  count_if(device_ifa IS NULL OR trim(CAST(device_ifa AS VARCHAR)) = '') AS blank_ifa,
  count_if(device_ifa = '00000000-0000-0000-0000-000000000000') AS all_zero_ifa,
  count_if(regexp_like(CAST(device_ifa AS VARCHAR), '(?i)^\{.*\}$')) AS unresolved_macro_ifa,
  count_if(regexp_like(CAST(device_ifa AS VARCHAR), '(?i)^test')) AS test_prefixed_ifa,
  count_if(
    device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
    AND NOT regexp_like(CAST(device_ifa AS VARCHAR), '^[0-9a-fA-F-]{36}$')
  ) AS non_uuid_ifa_total
FROM "prod-ptbwa-dw".addi_bid_log_flatten
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07';

-- G6-2. postback_log.ifa
SELECT
  count(*) AS total_rows,
  count_if(ifa IS NULL OR trim(CAST(ifa AS VARCHAR)) = '') AS blank_ifa,
  count_if(ifa = '00000000-0000-0000-0000-000000000000') AS all_zero_ifa,
  count_if(regexp_like(CAST(ifa AS VARCHAR), '(?i)^\{.*\}$')) AS unresolved_macro_ifa,
  count_if(regexp_like(CAST(ifa AS VARCHAR), '(?i)^test')) AS test_prefixed_ifa,
  count_if(
    ifa IS NOT NULL AND trim(CAST(ifa AS VARCHAR)) <> ''
    AND NOT regexp_like(CAST(ifa AS VARCHAR), '^[0-9a-fA-F-]{36}$')
  ) AS non_uuid_ifa_total
FROM "prod-ptbwa-dw".addi_postback_log
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07';
