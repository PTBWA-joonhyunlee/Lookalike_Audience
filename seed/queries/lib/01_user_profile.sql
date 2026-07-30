-- ============================================================
-- 01_user_profile.sql (propfit)
-- 목적   : user_profile 피처를 뽑는다. bid log 네이티브 필드(device_os_version/region/
--          app_bundle/carrier)만 다룬다.
-- 스코프 : 이번 단계는 라벨/지도학습 없이 피처 설계만 검토(2026-07-23 확정) — seed/pool
--          구분·5% 샘플링은 전환 라벨 소스가 정해진 뒤 별도로 설계한다.
-- 소스 변경(2026-07-23): bid log를 propfit 자체 테이블(ab_bid_log_etl_new)에서
--          "prod-ptbwa-dw"."abi_bid_log_flatten"으로 교체했다 — addi_bid_log_flatten의
--          형제 테이블(웹+앱 인벤토리 둘 다 있음, CLAUDE.md에 이미 존재가 기록돼 있던
--          테이블)이라 req_ext_allow_user_data_collection 컴플라이언스 컬럼이 실제로
--          있다(propfit 쪽엔 없었음) — 그래서 addi와 동일하게 동의+LMT 두 필터를 온전히
--          쓸 수 있다.
-- ptbwa_tg 조인 제거(2026-07-24 확정, 커버리지 실측 근거): 원래는 여기서 ptbwa_skb를 거쳐
--          ptbwa_tg의 gender_code/age_range/app_category 등을 붙였는데, 실측 결과
--          (eda/docs/202607240935.md 참고) ptbwa_tg가 전체 테이블 기준으로도
--          ptbwa_skb와 424,718건만 매칭되는 작은 패널이라 bid log 72,254,582명 중
--          2,500명(0.003%)에게만 값이 붙었다. 이 424,718건 상한은 gender_code/age_range뿐
--          아니라 app_category/product_category 등 ptbwa_tg의 모든 컬럼에 똑같이 적용되는
--          한계라(같은 테이블, 같은 행), "일부만 보강"이 아니라 사실상 이 조인 전체가
--          무의미했다. 반면 같은 목적(gender/age/관심사)을 skp 세그먼트로 대체했을 때는
--          bid log 모집단의 21.8%(15,552,864명)가 세그먼트를 갖고, 그중 성별(모델링)
--          세그먼트만 따져도 bid 모집단의 12.3%(8,868,480명)에 신호가 붙어 ptbwa_tg 대비
--          ~3,500배 낫다. 그래서 gender/age/관심사는 이 쿼리가 아니라
--          03_user_segments.sql의 segments 컬럼(+ 로컬 세그먼트_카테고리.csv 매핑)에서
--          가져오는 것으로 설계를 바꿨다 — device_ifa 키로 01과 03을 나중에 합치면 된다.
-- device_ifa fill-rate 주의: abi_bid_log_flatten 샘플 10행 중 device_ifa가 채워진 행은
--          2건뿐(나머지는 iOS ATT 등으로 비어 있는 것으로 추정)이지만, 실측(72,254,582
--          distinct device_ifa)으로 보면 절대 규모 자체는 충분히 크다.
-- 기간   : bid log는 학습 기간 자리표시자(2026-04~05)를 쓴다 — 2026-07-23 확인: 이 기간으로
--          실제 71~72M행이 나와서(0행 아님) 데이터가 존재함은 확인됐다. 다만 이 기간이
--          "의도한" 학습 기간인지(addi와 맞추려는 목적)는 사용자 확인 필요.
-- ============================================================

WITH bidlog_latest AS (
    SELECT
        device_ifa,
        req_user_id,
        device_osv AS device_os_version,
        device_geo_region AS region,
        app_bundle,
        device_carrier AS carrier,
        ROW_NUMBER() OVER (
            PARTITION BY device_ifa
            ORDER BY created_at DESC
        ) AS rn
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')
      AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
)
SELECT
    req_user_id,
    device_ifa,
    device_os_version,
    region,
    app_bundle,
    carrier,
    current_date AS update_dt
FROM bidlog_latest
WHERE rn = 1;
