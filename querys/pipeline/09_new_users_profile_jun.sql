-- ============================================================
-- 09_new_users_profile_jun.sql
-- 목적: 실제 후보 리스트 산출 — 2026-06에 처음 등장한(4~5월 bid log에 전혀 없던) 신규 유저의
--       프로필. 이 유저들을 기존에 학습된 모델(재학습 없음)로 임베딩→스코어링해서 "과거 전환
--       패턴과 비슷한, 아직 반응 안 한 신규 유저"를 실제로 찾아낸다(README §2-6).
-- 07_scoring_target_profile_jun.sql(6월 postback 유저 전체, 백테스트/검증용)과 다르다:
--       그쪽은 이미 반응(postback)한 유저라 4~5월 pool/시드와 겹칠 수 있어 백테스트 결과에
--       학습-검증 겹침(leakage) 위험이 있다. 이 쿼리는 4~5월에 아예 없던 유저만 뽑으므로
--       정의상 pool/시드와 겹치지 않는다 — 순수 실전 후보군.
-- 신규 유저 정의: 2026-04~05 addi_bid_log_flatten에 없다가 2026-06에 처음 나타난 req_user_id.
-- 샘플링 없음 — 실제 후보 리스트이므로 전수(파일럿이 아니라 실서비스 산출 단계).
-- ============================================================

WITH prior_users AS (
    SELECT DISTINCT req_user_id
    FROM "prod-ptbwa-dw"."addi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')
      AND req_user_id IS NOT NULL AND trim(CAST(req_user_id AS VARCHAR)) <> ''
),
latest_log AS (
    SELECT
        b.req_user_id,
        b.device_ifa,
        b.device_osv AS device_os_version,
        b.device_geo_region AS region,
        b.app_bundle,
        b.created_at,
        ROW_NUMBER() OVER (
            PARTITION BY b.req_user_id
            ORDER BY b.created_at DESC
        ) AS rn
    FROM "prod-ptbwa-dw"."addi_bid_log_flatten" b
    LEFT JOIN prior_users p ON b.req_user_id = p.req_user_id
    WHERE b.year = '2026' AND b.month = '06'
      AND b.req_user_id IS NOT NULL AND trim(CAST(b.req_user_id AS VARCHAR)) <> ''
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
      AND p.req_user_id IS NULL   -- ← 4~5월에 없었던 유저만 (신규 유저 필터)
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
