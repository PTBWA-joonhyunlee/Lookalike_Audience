-- ============================================================
-- 04_coverage_check.sql (propfit)
-- 목적: 01_user_profile.sql이 71,417,675행, 03_user_segments.sql이 53,341,243행 나왔는데,
--   두 숫자 다 "모집단 크기"일 뿐 "실제로 붙었는지"는 말해주지 않는다(01의 두 크로스워크가
--   전부 LEFT JOIN이라 gender_code가 전부 NULL이어도 행 수는 똑같이 나옴). 아래 두 쿼리로
--   실제 커버리지를 확인한다.
--
-- (A) 인구통계 도달 퍼널: bid log → skb 크로스워크 → ptbwa_tg. reached_crosswalk/
--   reached_demographics가 bid_devices 대비 너무 작으면(예: 한 자릿수 %) bullet 2
--   (gender/age 보강)의 실효성 자체를 재검토해야 한다 — id_space_check/01_id_mapping_check.sql에서
--   ptbwa_tg↔skb 매칭(424,718)이 skp↔skb 매칭(수십억)보다 훨씬 작게 나온 전례가 있어서
--   커버리지가 얇을 가능성을 미리 염두에 둘 것.
-- (B) 01↔03 device_ifa 오버랩: 세그먼트가 bid log 모집단을 얼마나 커버하는지 보여줄 뿐
--   아니라, abi_bid_log_flatten.device_ifa = ptbwa_skb.ad_id라는 전제(id_space_check/01_id_mapping_check.sql
--   이 검증 못한 부분, 사용자 제공 원본 쿼리 그대로 가정 중)가 맞는지도 간접 확인해준다 —
--   오버랩이 거의 0이면 이 전제 자체가 틀렸다는 신호.
-- ============================================================

-- (A) 인구통계 도달 퍼널
WITH bid AS (
    SELECT DISTINCT device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')
      AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
),
skb AS (
    SELECT DISTINCT CAST(ad_id AS VARCHAR) AS ad_id, CAST(platform_ad_id AS VARCHAR) AS platform_ad_id
    FROM "propfit"."ptbwa_skb"
    WHERE ad_id IS NOT NULL AND platform_ad_id IS NOT NULL
      AND trim(CAST(ad_id AS VARCHAR)) <> '' AND trim(CAST(platform_ad_id AS VARCHAR)) <> ''
),
tg AS (
    SELECT DISTINCT CAST(uuid AS VARCHAR) AS uuid
    FROM "propfit"."ptbwa_tg"
    WHERE CAST(id_type AS VARCHAR) = 'ADID'
)
SELECT
    count(*)                AS bid_devices,
    count(k.platform_ad_id) AS reached_crosswalk,
    count(t.uuid)           AS reached_demographics
FROM bid b
LEFT JOIN skb k ON b.device_ifa = k.ad_id
LEFT JOIN tg  t ON k.platform_ad_id = t.uuid;

-- (B) 01 결과(bid log 모집단)와 03 결과(세그먼트) device_ifa 오버랩
-- 실행 시 01/03을 CSV로 이미 뽑았다면 그 CSV 기준으로 세도 되고, 여기선 원본 테이블 재계산으로 확인.
WITH bid AS (
    SELECT DISTINCT device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')
      AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
),
seg AS (
    SELECT DISTINCT ad_id AS device_ifa
    FROM "propfit"."skp"
    WHERE NOT (year = '2024' AND month = '12' AND day = '31')
      AND CAST(id_type AS VARCHAR) = '2'
      AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
)
SELECT
    count(*) AS bid_devices,
    (SELECT count(*) FROM seg) AS segment_devices,
    count(s.device_ifa) AS overlap_devices
FROM bid b
LEFT JOIN seg s ON b.device_ifa = s.device_ifa;
