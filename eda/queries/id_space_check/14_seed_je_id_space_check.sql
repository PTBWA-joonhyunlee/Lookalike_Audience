/* ============================================================
   id_space_check/14_seed_je_id_space_check.sql (eda, 구 eda/queries/28_seed_je_id_space_check.sql —
   2026-08-26 id_space_check/ 폴더 이동 + 번호 재부여. je 신규 seed —
   id_space_check/02_seed_coverage_check.sql + id_space_check/05_seed_skb_crosswalk_check.sql
   [피엘라벤]을 합친 버전)
   배경: je_sample_adid.csv(1,923개 device_ifa, seed/queries/01_create_seed_table_je.sql로
   등록)가 어떤 ID 공간에 있는지 아직 확인 안 됨. 피엘라벤 seed는 겉보기엔 UUID였지만
   실제로는 raw GAID(propfit.skp.ad_id/ptbwa_skb.ad_id) 공간이 아니라
   ptbwa_skb.platform_ad_id 공간이었다(직접 조인 0.0% vs 크로스워크 후 61%,
   ../../docs/id_space_crosswalk.md 참고) — 매칭 건수만으로 "같은 공간"이라 추론하지 말고
   이 seed도 동일하게 검증한다.

   판정 기준:
   - seed_matches_bidlog / seed_matches_skp_direct가 높으면(수십 % 이상) → 이미 raw GAID
     공간 → 크로스워크 불필요, 02_create_seed_ad_id_table_je.sql은 정규식 필터 + DISTINCT만
     하는 단순 버전으로 작성.
   - seed_matches_skp_direct는 낮은데 seed_matches_skb_platform_ad_id(또는 ad_id/uuid)가
     높으면 → 피엘라벤과 동일하게 skb를 경유한 크로스워크가 필요 →
     02_create_seed_ad_id_table_je.sql을 02_create_seed_ad_id_table.sql[피엘라벤] 패턴으로
     작성.
   - 전부 낮으면 → 이 seed의 device_ifa가 이 프로젝트 로그 체계와 무관한 값일 수 있음,
     값 샘플/포맷을 다시 확인.

   기간: bidlog 매칭은 pool/seed 학습 기본 기간(2026-04~05)로 본다 — 여기서 매칭률이
   비정상적으로 낮으면 기간을 넓혀(예: 최근 6개월) 재확인할 것(je seed 유저가 이 기간에
   활동이 없었을 수 있음, seed 자체의 최신성은 알 수 없으므로).
   ============================================================ */

WITH seed AS (
    SELECT DISTINCT device_ifa
    FROM seed_je
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
