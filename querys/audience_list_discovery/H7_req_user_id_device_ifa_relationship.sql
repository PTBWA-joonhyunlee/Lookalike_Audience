-- H7. req_user_id 와 device_ifa 관계 확인 (1:1 인지, 1명이 여러 디바이스를 갖는지)
-- req_user_id가 device_ifa보다 상위 개념(유저/가구 단위) 식별자인지 판단하기 위함

-- H7-1. req_user_id 1개당 연결된 distinct device_ifa 개수 분포
WITH per_user AS (
  SELECT req_user_id, count(DISTINCT device_ifa) AS device_cnt
  FROM "prod-ptbwa-dw".addi_bid_log_flatten
  WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
    AND req_user_id IS NOT NULL AND trim(CAST(req_user_id AS VARCHAR)) <> ''
    AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
  GROUP BY req_user_id
)
SELECT
  count(*) AS distinct_req_user_id,
  avg(device_cnt) AS avg_devices_per_user,
  max(device_cnt) AS max_devices_per_user,
  count_if(device_cnt = 1) AS single_device_users,
  count_if(device_cnt > 1) AS multi_device_users
FROM per_user;

-- H7-2. device_ifa 1개당 연결된 distinct req_user_id 개수 분포 (역방향)
WITH per_device AS (
  SELECT device_ifa, count(DISTINCT req_user_id) AS user_cnt
  FROM "prod-ptbwa-dw".addi_bid_log_flatten
  WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
    AND req_user_id IS NOT NULL AND trim(CAST(req_user_id AS VARCHAR)) <> ''
    AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
  GROUP BY device_ifa
)
SELECT
  count(*) AS distinct_device_ifa,
  avg(user_cnt) AS avg_users_per_device,
  max(user_cnt) AS max_users_per_device,
  count_if(user_cnt = 1) AS single_user_devices,
  count_if(user_cnt > 1) AS multi_user_devices
FROM per_device;

-- H7-3. req_user_id 값 형태 확인 (숫자/UUID/해시 등 어떤 포맷인지)
SELECT DISTINCT req_user_id
FROM "prod-ptbwa-dw".addi_bid_log_flatten
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
  AND req_user_id IS NOT NULL
LIMIT 20;
