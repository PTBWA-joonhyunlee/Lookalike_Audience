/* ============================================================
   id_space_check/11_seed_crosswalk_check_deduped.sql (eda, 구 eda/queries/18_seed_crosswalk_check_deduped.sql —
   2026-08-26 id_space_check/ 폴더 이동 + 번호 재부여, 그 이전엔 02i_seed_crosswalk_check_deduped.sql)
   배경: 02g/02h에서 seed_crosswalked_to_ad_id=2,519,634로 seed_total(1,518,101)보다
   컸다 — ptbwa_skb에서 platform_ad_id 하나가 여러 ad_id로 매핑되는 fan-out(1:N)이
   있다는 뜻. 02g/02h는 "distinct ad_id 몇 개가 맞았나"를 셌기 때문에 fan-out 때문에
   숫자가 부풀려져 있어 실제 seed 커버리지로 해석할 수 없다.

   이 쿼리는 seed_crosswalked를 (device_ifa, ad_id) 쌍으로 유지한 채, 최종 집계는
   반드시 "distinct seed.device_ifa" 기준으로 한다 — 한 seed 유저가 여러 ad_id로
   fan-out 되어도 bidlog/segments 중 하나라도 맞으면 그 유저 1명만 센다.
   ============================================================ */

WITH seed AS (
    SELECT DISTINCT device_ifa
    FROM seed_piellaven
    WHERE device_ifa IS NOT NULL
      AND regexp_like(device_ifa, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
),
skb AS (
    SELECT DISTINCT
        CAST(platform_ad_id AS VARCHAR) AS platform_ad_id,
        CAST(ad_id AS VARCHAR) AS ad_id
    FROM "propfit"."ptbwa_skb"
    WHERE platform_ad_id IS NOT NULL AND ad_id IS NOT NULL
),
bidlog AS (
    SELECT DISTINCT device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')
      AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
),
segments AS (
    SELECT DISTINCT ad_id
    FROM "propfit"."skp"
    WHERE NOT (year = '2024' AND month = '12' AND day = '31')
      AND CAST(id_type AS VARCHAR) = '2'
      AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
),
seed_crosswalked AS (
    SELECT DISTINCT sd.device_ifa, k.ad_id
    FROM seed sd
    JOIN skb k ON sd.device_ifa = k.platform_ad_id
)
SELECT
    (SELECT count(*) FROM seed)                                      AS seed_total,
    (SELECT count(DISTINCT device_ifa) FROM seed_crosswalked)         AS seed_with_any_crosswalk,
    (SELECT count(DISTINCT sc.device_ifa)
        FROM seed_crosswalked sc JOIN bidlog b ON sc.ad_id = b.device_ifa)   AS seed_matched_bidlog_via_crosswalk,
    (SELECT count(DISTINCT sc.device_ifa)
        FROM seed_crosswalked sc JOIN segments s ON sc.ad_id = s.ad_id)     AS seed_matched_segments_via_crosswalk;
