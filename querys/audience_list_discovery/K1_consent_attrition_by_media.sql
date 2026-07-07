-- K1. "완료(T4)" 유저가 컴플라이언스 필터에서 유독 많이 탈락하는 이유 진단
-- 대상 캠페인(cmp_no)을 원하는 값으로 교체하세요. 기본값: 10115

-- K1-1. 전체 completed 디바이스 중 bid_log에서 아예 안 잡히는 비율 (구조적 누락 여부)
WITH completed_devices AS (
  SELECT DISTINCT p.ifa AS device_ifa
  FROM "prod-ptbwa-dw".addi_postback_log p
  WHERE p.year = '2026' AND p.month = '06' AND p.day BETWEEN '01' AND '07'
    AND CAST(p.cmp_no AS VARCHAR) IN ('10115')  -- << 여기 교체
    AND p.log_type = 'v_complete'
    AND p.ifa IS NOT NULL AND trim(CAST(p.ifa AS VARCHAR)) <> ''
),
bid_rows AS (
  SELECT DISTINCT b.device_ifa
  FROM "prod-ptbwa-dw".addi_bid_log_flatten b
  JOIN completed_devices c ON b.device_ifa = c.device_ifa
  WHERE b.year = '2026' AND b.month = '06' AND b.day BETWEEN '01' AND '07'
    AND CAST(b.cmp_no AS VARCHAR) IN ('10115')  -- << 여기도 동일하게 교체
)
SELECT
  (SELECT count(*) FROM completed_devices) AS total_completed_devices,
  (SELECT count(*) FROM bid_rows) AS completed_devices_found_in_bid_log;

-- K1-2. media_id/app_bundle별 completed 디바이스의 동의 플래그 분포
-- (특정 매체에서만 동의값 미채움/거부가 몰리는지 확인)
WITH completed_devices AS (
  SELECT DISTINCT p.ifa AS device_ifa
  FROM "prod-ptbwa-dw".addi_postback_log p
  WHERE p.year = '2026' AND p.month = '06' AND p.day BETWEEN '01' AND '07'
    AND CAST(p.cmp_no AS VARCHAR) IN ('10115')  -- << 여기 교체
    AND p.log_type = 'v_complete'
    AND p.ifa IS NOT NULL AND trim(CAST(p.ifa AS VARCHAR)) <> ''
),
bid_rows AS (
  SELECT
    b.media_id,
    b.app_bundle,
    b.device_ifa,
    CAST(b.req_ext_allow_user_data_collection AS VARCHAR) AS consent_flag
  FROM "prod-ptbwa-dw".addi_bid_log_flatten b
  JOIN completed_devices c ON b.device_ifa = c.device_ifa
  WHERE b.year = '2026' AND b.month = '06' AND b.day BETWEEN '01' AND '07'
    AND CAST(b.cmp_no AS VARCHAR) IN ('10115')  -- << 여기도 동일하게 교체
)
SELECT
  media_id,
  app_bundle,
  count(DISTINCT device_ifa) AS completed_devices_seen,
  count(DISTINCT CASE WHEN consent_flag = '1' THEN device_ifa END) AS consented_devices,
  count(DISTINCT CASE WHEN consent_flag = '0' THEN device_ifa END) AS denied_devices,
  count(DISTINCT CASE WHEN consent_flag IS NULL THEN device_ifa END) AS unknown_devices
FROM bid_rows
GROUP BY media_id, app_bundle
ORDER BY completed_devices_seen DESC;
