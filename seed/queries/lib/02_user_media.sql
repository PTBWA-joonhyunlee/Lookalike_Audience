-- ============================================================
-- 02_user_media.sql (propfit)
-- 목적   : propfit 소스로 media_sequence(SASRec) 학습 입력을 뽑는다 — 유저×미디어×시각
--          이벤트 그레인, 30분 재방문 dedup 포함(01_pipeline/02_pool_media_apr_may.sql과
--          동일 로직).
-- 스코프 : 라벨/지도학습 없이 피처 설계만 검토(2026-07-23 확정) — top500 vocab 산출까지만
--          다루고, seed/pool 구분은 다루지 않는다.
-- genre 처리(2026-07-23 확정): app_content_genre/site_content_genre가 샘플에서 전부 비어
--          있어(addi와 반대 상황 — addi는 app_bundle이 통신사 앱 3종 고정이라 genre로
--          대체했는데, propfit은 거꾸로 genre가 비고 app_bundle이 다양함) media(시퀀스
--          아이템)는 app_bundle을 그대로 쓰고 genre 피처는 넣지 않는다. app_storeurl은
--          패키지 링크일 뿐 카테고리 정보를 주지 않으므로 genre 대체재가 못 된다 — 외부
--          앱카테고리 매핑 테이블이 생기면 그때 별도 피처로 추가.
-- 인벤토리 확장: addi(CTV 전용, app 인벤토리만)와 달리 propfit 스키마엔 site_page 등
--          웹 인벤토리 컬럼도 있다(샘플엔 app 행만 있어서 실측은 못 함). media는
--          COALESCE(app_bundle, site_page)로 두고 inventory_type(app/site)을 보조 피처로
--          같이 뽑아서, 실제 데이터에 site 인벤토리 행이 섞여 있어도 시퀀스가 끊기지
--          않게 했다 — site 행이 실제로 없다면 app_bundle만 쓰는 것과 동일하게 동작한다.
-- connection_type: addi_bid_log_flatten에는 없어서 NULL로 채웠던 컬럼인데, abi_bid_log_flatten
--          에는 device_connectiontype이 실제로 존재해서 그대로 쓴다(다만 샘플 10행 중
--          채워진 건 1건뿐 — fill-rate는 실데이터로 재확인).
-- 소스 변경(2026-07-23): bid log를 propfit 자체 테이블(ab_bid_log_etl_new)에서
--          "prod-ptbwa-dw"."abi_bid_log_flatten"으로 교체(01_user_profile.sql과 동일 사유
--          — addi_bid_log_flatten의 형제 테이블이라 req_ext_allow_user_data_collection이
--          실제로 있어 동의 필터를 온전히 쓸 수 있다). 이 쿼리는 propfit DMP 테이블
--          (ptbwa_tg/skp)과 조인하지 않으므로 01/03과 달리 ptbwa_skb 크로스워크는
--          필요 없다 — device_ifa/req_user_id 그대로 쓴다.
-- 컴플라이언스: addi와 동일하게 동의(req_ext_allow_user_data_collection='1') + LMT
--          옵트아웃 제외 둘 다 적용(abi_bid_log_flatten엔 동의 컬럼이 실제로 있음 —
--          01_user_profile.sql 참고).
-- ⚠ 키 공간 주의: 이 쿼리는 req_user_id 기준으로 partition/필터링하는데(device_ifa는
--          NULL일 수 있음, 필터도 안 함), 01/03은 device_ifa를 키로 쓴다. profile/segments가
--          device_ifa 공간이라 media와 바로 안 붙을 수 있다 — 나중에 세 피처를 합칠 때
--          공통 키를 다시 정할 것.
-- ⚠ 입력 계약 주의: 이 쿼리 결과는 (media, inventory_type, ad_type, connection_type)
--          컬럼을 갖는다(content_genre 없음) — propfit용 media_sequence 임베딩 모델을
--          새로 만들 때(seed/docs/model_architecture.md "다음 단계" 참고) 이 계약에 맞춰
--          설계해야 한다.
-- 조인/기간 관련 주의사항은 01_user_profile.sql 헤더 참고.
-- ============================================================

WITH raw_visit AS (
    SELECT
        req_id,
        req_user_id,
        device_ifa,
        COALESCE(
            NULLIF(CAST(app_bundle AS VARCHAR), ''),
            NULLIF(CAST(site_page AS VARCHAR), '')
        ) AS media,
        CASE
            WHEN NULLIF(CAST(app_bundle AS VARCHAR), '') IS NOT NULL THEN 'app'
            WHEN NULLIF(CAST(site_page AS VARCHAR), '') IS NOT NULL THEN 'site'
            ELSE NULL
        END AS inventory_type,
        NULLIF(CAST(imp_ad_type AS VARCHAR), '') AS ad_type,
        -- 기존 스키마(connection_type)는 INTEGER 계약이었지만 실제 device_connectiontype
        -- 값 형태(코드 정수인지 문자열인지)를 샘플로 확인 못했다 — VARCHAR로 우선 받고
        -- embedding 코드 쪽 계약과 맞춰 나중에 CAST 타입을 확정할 것.
        NULLIF(CAST(device_connectiontype AS VARCHAR), '') AS connection_type,
        CAST(from_iso8601_timestamp(CAST(created_at AS VARCHAR)) AT TIME ZONE 'Asia/Seoul' AS timestamp) AS ts,
        year
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')   -- 2026-07-23 확인: 01_user_profile.sql이 같은
                                                     -- 필터로 71,417,675행을 반환해 2026-04~05 데이터가
                                                     -- 실제 존재함은 확인됨(0행 아님). 의도한 학습 기간인지는
                                                     -- 여전히 확인 필요.
      AND req_user_id IS NOT NULL
      AND trim(CAST(req_user_id AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
),
media_rank AS (
    -- 방문 유저 수(req_id distinct) 기준 상위 500개 미디어만 채택 (기존 02_pool_media_apr_may.sql과 동일 정책)
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
        v.inventory_type,
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
    inventory_type,
    ad_type,
    connection_type,
    ts,
    year
FROM flagged
WHERE prev_media IS NULL                              -- 유저의 첫 이벤트
   OR prev_media <> media                              -- 직전과 다른 미디어로 전환
   OR date_diff('second', prev_ts, ts) >= 1800         -- 같은 미디어인데 30분 이상 공백
;
