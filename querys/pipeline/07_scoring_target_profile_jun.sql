-- ============================================================
-- 07_scoring_target_profile_jun.sql
-- 목적: "전체 postback 유저 vs score 상위 10~100%" 백테스트를 하려면 2026-06 postback이 발생한
--       유저 전원을 스코어링해야 한다(06_backtest_labels_jun.sql의 라벨과 같은 모집단). 그
--       스코어링 입력(user_profile 추론용)을 여기서 뽑는다. 01_pool_profile_apr_may.sql과
--       컬럼 계약은 동일하지만 5% 샘플링 없음 — postback 유저 집합 자체가 이미 작아서(30만 명)
--       전수 조회해도 Athena 부담이 크지 않음.
-- 대상  : addi_postback_log(ifa) 2026-06 발생 유저를 addi_bid_log_flatten(device_ifa)에서
--       최신(06월 기준) 프로필 행으로 매칭. postback은 bid 노출을 전제로 하므로 06월 bid log에
--       존재해야 정상 — 없으면(비정상 케이스) 결과에서 자동 제외된다(임베딩 입력이 없으므로).
-- ============================================================

WITH postback_ifa AS (
    SELECT DISTINCT ifa AS device_ifa
    FROM "prod-ptbwa-dw"."addi_postback_log"
    WHERE year = '2026' AND month = '06'
      AND ifa IS NOT NULL AND trim(CAST(ifa AS VARCHAR)) <> ''
),
latest_log AS (
    SELECT
        b.device_ifa,
        b.req_user_id,
        b.device_osv AS device_os_version,
        b.device_geo_region AS region,
        b.app_bundle,
        ROW_NUMBER() OVER (
            PARTITION BY b.device_ifa
            ORDER BY b.created_at DESC
        ) AS rn
    FROM "prod-ptbwa-dw"."addi_bid_log_flatten" b
    JOIN postback_ifa p ON b.device_ifa = p.device_ifa
    WHERE b.year = '2026' AND b.month = '06'
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
      AND b.req_user_id IS NOT NULL AND trim(CAST(b.req_user_id AS VARCHAR)) <> ''
)
SELECT
    req_user_id,
    device_ifa,
    device_os_version,
    region,
    app_bundle,
    current_date AS update_dt
FROM latest_log
WHERE rn = 1;
