/* ============================================================
   29_seed_shoplinker_id_space_check.sql (eda, shoplinker 신규 seed —
   pipeline/generate_seed_queries.py가 28_seed_je_id_space_check.sql을 템플릿 삼아 자동 생성)
   목적: seed_shoplinker(seed/queries/01_create_seed_table_shoplinker.sql로 등록)의
   device_ifa가 어떤 ID 공간에 있는지 확인한다 — 매칭 건수만으로 "같은 공간"이라 추론하지
   않고 직접/크로스워크 후보를 모두 카운트해서 비교한다(피엘라벤 seed가 겉보기엔 UUID였지만
   실제로는 ptbwa_skb.platform_ad_id 공간이었던 전례 때문 — eda/docs/id_space_crosswalk.md).

   판정 기준(pipeline generate_seed_queries.py resolve 단계가 이 결과를 받아 자동 적용,
   임계값 10%):
   - seed_matches_skp_direct 또는 seed_matches_skb_ad_id 비율이 임계값 이상이면 → 이미 raw
     GAID 공간 → 크로스워크 불필요, 02_create_seed_ad_id_table_shoplinker.sql은 정규식
     필터 + DISTINCT만 하는 단순 버전.
   - 위는 낮은데 seed_matches_skb_platform_ad_id 또는 seed_matches_skb_uuid 비율이 임계값
     이상이면 → skb를 경유한 크로스워크 필요, 매칭률이 더 높은 컬럼을 사용.
   - 전부 낮거나 애매하면(direct/crosswalk 후보가 둘 다 임계값 미만 또는 둘 다 이상) →
     자동 판정을 멈춘다 — 이 seed의 device_ifa가 이 프로젝트 로그 체계와 무관한 값일 수
     있으니 값 샘플/포맷을 직접 확인할 것.

   기간: bidlog 매칭은 기본으로 pool/seed 학습 기간(2026년 04~05월)로
   본다 — 매칭률이 비정상적으로 낮으면 기간을 넓혀 재확인할 것(이 seed 유저가 이 기간에
   활동이 없었을 수 있음).
   ============================================================ */

WITH seed AS (
    SELECT DISTINCT device_ifa
    FROM seed_shoplinker
    WHERE device_ifa IS NOT NULL
      AND regexp_like(device_ifa, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
),
bidlog AS (
    SELECT DISTINCT device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')
      AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
),
skp_direct AS (
    SELECT DISTINCT ad_id AS device_ifa
    FROM "propfit"."skp"
    WHERE NOT (year = '2024' AND month = '12' AND day = '31')   /* 깨진 .tmp 파티션 제외 */
      AND CAST(id_type AS VARCHAR) = '2'
      AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
),
skb_ad_id AS (
    SELECT DISTINCT CAST(ad_id AS VARCHAR) AS v
    FROM "propfit"."ptbwa_skb"
    WHERE ad_id IS NOT NULL
),
skb_platform_ad_id AS (
    SELECT DISTINCT CAST(platform_ad_id AS VARCHAR) AS v
    FROM "propfit"."ptbwa_skb"
    WHERE platform_ad_id IS NOT NULL
),
skb_uuid AS (
    SELECT DISTINCT CAST(uuid AS VARCHAR) AS v
    FROM "propfit"."ptbwa_skb"
    WHERE uuid IS NOT NULL
)
SELECT
    (SELECT count(*) FROM seed) AS seed_total,
    (SELECT count(*) FROM seed sd JOIN bidlog b ON sd.device_ifa = b.device_ifa) AS seed_matches_bidlog,
    (SELECT count(*) FROM seed sd JOIN skp_direct s ON sd.device_ifa = s.device_ifa) AS seed_matches_skp_direct,
    (SELECT count(*) FROM seed sd JOIN skb_ad_id k ON sd.device_ifa = k.v) AS seed_matches_skb_ad_id,
    (SELECT count(*) FROM seed sd JOIN skb_platform_ad_id k ON sd.device_ifa = k.v) AS seed_matches_skb_platform_ad_id,
    (SELECT count(*) FROM seed sd JOIN skb_uuid k ON sd.device_ifa = k.v) AS seed_matches_skb_uuid;
