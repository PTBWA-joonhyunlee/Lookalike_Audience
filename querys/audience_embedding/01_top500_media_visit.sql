-- ============================================================
-- 01_top500_media_visit.sql
-- 목적   : addi 오디언스 임베딩 파이프라인의 base 테이블이자 media_sequence(SASRec) 학습 입력.
--          C:\Users\data\workspace\user-to-ad-encoder 프로젝트의 01_top500_media_visit.sql을
--          addi_bid_log_flatten 소스에 맞게 이식한 버전. 컬럼 이름/그레인을 원본과 동일하게
--          유지해 embedding/media_sequence 코드를 그대로 재사용할 수 있게 한다 (수정 없음).
-- 소스   : prod-ptbwa-dw.addi_bid_log_flatten (원본은 abi_bid_log_flatten)
-- 차이점 : 원본에는 없는 컴플라이언스 필터 추가 — docs/audience_list_project.md에서 확정한
--          정책(동의 필터 req_ext_allow_user_data_collection='1', LMT 옵트아웃 제외)을 그대로 적용.
--          이 프로젝트(addi)에서는 임베딩 대상도 "명시적으로 데이터 활용에 동의한 유저"로 제한한다.
-- 범위   : 특정 캠페인(cmp_no)으로 한정하지 않음 — 신규 캠페인의 미노출/미전환 유저를 기존
--          "관심 사용자"(J2 결과)와 유사도 비교하려면, 임베딩 자체는 전체 모수 기준 범용으로
--          만들어야 함 (캠페인 특정 필터는 다운스트림 유사도 스코어링 단계에서 적용).
-- 필터링 규칙: 같은 유저가 같은 미디어를 30분(1800초) 이내에 재방문하면 재방문 쪽을 버리고
--          세션 내 최초 이벤트만 남긴다 (원본과 동일 로직).
-- 기간   : 2026-04-01~2026-05-31 (학습 데이터) — docs/audience_embedding_plan.md §7 단기 목표.
--          02_user_profile.sql과 반드시 동일 기간 유지. 6월 신규 유저 스코어링 입력은
--          04_new_users_top500_media_visit_jun.sql이 따로 담당(이 파일과 top500 vocab이
--          어긋나면 안 되므로 재사용하지 않고 별도 쿼리로 분리).
-- 샘플링 : 캠페인 무필터 2개월치라 데이터량이 너무 커서(7일 8,990만건 기준 2개월 환산 시
--          7~8억 건대) 유저 단위 5% 샘플링을 추가했다. req_user_id 해시값 기준이라 같은
--          유저는 항상 같은 샘플에 포함/제외되고(결정적), 기간을 다시 줄이는 대신 유저 수만
--          줄이므로 선택된 유저의 시퀀스 길이는 그대로 보존된다. 02_user_profile.sql과 반드시
--          동일한 샘플링 조건을 써야 두 임베딩이 같은 유저 집합을 가리킨다.
-- ============================================================

WITH raw_visit AS (
    SELECT
        req_id,
        req_user_id,
        device_ifa,
        -- addi_bid_log_flatten에는 site_page/site_content_genre/site_content_language/
        -- device_connectiontype/device_pxratio 컬럼이 아예 없음(COLUMN_NOT_FOUND 확인, 2026-07-07).
        -- abi_bid_log_flatten과 달리 순수 앱(CTV/Android TV) 인벤토리만 있고 웹 인벤토리가 없어서로 추정.
        -- media는 app_bundle만 사용 (site_page 폴백 없음).
        NULLIF(CAST(app_bundle AS VARCHAR), '') AS media,
        NULLIF(CAST(app_content_genre AS VARCHAR), '') AS content_genre,
        NULLIF(CAST(imp_ad_type AS VARCHAR), '')  AS ad_type,
        -- device_connectiontype 컬럼 자체가 없어 전부 NULL로 출력 (embedding 코드와의 컬럼 계약 유지 목적).
        -- <NA> 임베딩으로만 채워져 사실상 정보 없는 상수 피처가 됨 — docs/audience_embedding_plan.md 참고.
        CAST(NULL AS INTEGER) AS connection_type,
        CAST(from_iso8601_timestamp(CAST(created_at AS VARCHAR)) AT TIME ZONE 'Asia/Seoul' AS timestamp) AS ts,
        year
    FROM "prod-ptbwa-dw"."addi_bid_log_flatten"
    WHERE year = '2026'
      AND month IN ('04', '05')   -- ← 2026-04~05 (전체 두 달). day 조건 불필요
      AND req_user_id IS NOT NULL
      AND trim(CAST(req_user_id AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
      AND mod(crc32(to_utf8(CAST(req_user_id AS VARCHAR))), 100) < 5   -- ← 유저 단위 5% 샘플링 (crc32는 항상 0 이상이라 abs 불필요)
),
media_rank AS (
    -- 방문 유저 수(req_id distinct) 기준 상위 500개 미디어만 채택
    SELECT
        media,
        COUNT(DISTINCT req_id) AS req_cnt
    FROM raw_visit
    WHERE media IS NOT NULL
    GROUP BY media
    ORDER BY req_cnt DESC
    LIMIT 500
),
top500 AS (
    SELECT
        v.req_id,
        v.req_user_id,
        v.device_ifa,
        v.media,
        v.content_genre,
        v.ad_type,
        v.connection_type,
        v.ts,
        v.year
    FROM raw_visit v
    JOIN media_rank r ON v.media = r.media
),
flagged AS (
    -- 같은 유저 타임라인에서 직전 이벤트 대비 "새 세션"인지 판정
    SELECT
        t.*,
        LAG(media) OVER (PARTITION BY req_user_id ORDER BY ts, req_id) AS prev_media,
        LAG(ts)    OVER (PARTITION BY req_user_id ORDER BY ts, req_id) AS prev_ts
    FROM top500 t
)
SELECT
    req_id,
    req_user_id,
    device_ifa,
    media,
    content_genre,
    ad_type,
    connection_type,
    ts,
    year
FROM flagged
WHERE prev_media IS NULL                              -- 유저의 첫 이벤트
   OR prev_media <> media                              -- 직전과 다른 미디어로 전환
   OR date_diff('second', prev_ts, ts) >= 1800         -- 같은 미디어인데 30분 이상 공백
;
