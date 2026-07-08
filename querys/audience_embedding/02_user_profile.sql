-- ============================================================
-- 02_user_profile.sql
-- 목적   : 유저별 인구통계/디바이스 프로필. 반드시 req_user_id 1행 보장.
--          원래 별도 저장소였던 user-to-ad-encoder 프로젝트(현재는 이 저장소에 합쳐짐,
--          README.md 참고)의 02_user_profile.sql을 addi_bid_log_flatten 소스에 맞게 이식.
--          컬럼 이름/그레인을 원본과 동일하게 유지해 embedding/user_profile 코드를 그대로
--          재사용 (수정 없음).
-- 소스   : addi_bid_log_flatten (최신 로그 1건 기준 device/지역/언어/네트워크)
-- 차이점 : 원본에는 없는 컴플라이언스 필터 추가(동의='1', LMT 옵트아웃 제외) — 01과 동일 정책.
-- 기간   : 2026-04-01~2026-05-31 (학습 데이터) — 01_top500_media_visit.sql과 동일 기간 유지.
-- 샘플링 : 01_top500_media_visit.sql과 반드시 동일한 유저 단위 5% 샘플링 조건을 쓴다 (근거는
--          01의 주석 참고) — 그래야 두 임베딩이 같은 유저 집합을 가리킨다.
-- 주의   : rn은 "최신 1건 선택"에만 쓰고 최종 SELECT에는 포함하지 않는다.
-- 참고   : content_genre / ad_type / connection_type은 여기(최신 1건 스냅샷)가 아니라
--          01_top500_media_visit.sql에 이벤트 단위로 남겨둔다 (원본과 동일한 이유:
--          최신 1건만 보면 실제 선호/사용 패턴이 아니라 마지막 값 하나만 남는 문제).
-- ============================================================

WITH latest_log AS (
    SELECT
        req_user_id,
        device_ifa,
        device_os,
        device_osv AS device_os_version,
        device_devicetype AS device_type,
        device_geo_region AS region,
        device_geo_country AS country,
        -- site_content_language 컬럼이 addi_bid_log_flatten에는 없음(순수 앱 인벤토리) → app_content_language만 사용
        NULLIF(CAST(app_content_language AS VARCHAR), '') AS language,
        device_carrier AS carrier,
        device_make,
        device_model,
        TRY_CAST(device_w AS INT) AS device_w,
        TRY_CAST(device_h AS INT) AS device_h,
        -- device_pxratio 컬럼 자체가 addi_bid_log_flatten에는 없어 전부 NULL로 출력
        -- (embedding 코드와의 컬럼 계약 유지 목적. numeric.py가 결측을 마스킹 처리해 사실상 정보 없는 상수 피처가 됨)
        CAST(NULL AS DOUBLE) AS device_pxratio,
        TRY_CAST(device_lmt AS INT) AS device_lmt,
        created_at,
        ROW_NUMBER() OVER (
            PARTITION BY req_user_id
            ORDER BY created_at DESC
        ) AS rn
    FROM "prod-ptbwa-dw"."addi_bid_log_flatten"
    WHERE year = '2026'
      AND month IN ('04', '05')   -- ← 2026-04~05 (전체 두 달). day 조건 불필요
      AND req_user_id IS NOT NULL
      AND trim(CAST(req_user_id AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
      AND mod(crc32(to_utf8(CAST(req_user_id AS VARCHAR))), 100) < 5   -- ← 유저 단위 5% 샘플링 (01과 동일 조건)
)
SELECT
    req_user_id,
    device_ifa,
    device_os,
    device_os_version,
    device_type,
    region,
    country,
    language,
    carrier,
    device_make,
    device_model,
    device_w,
    device_h,
    device_pxratio,
    device_lmt,
    current_date AS update_dt
FROM latest_log
WHERE rn = 1;
