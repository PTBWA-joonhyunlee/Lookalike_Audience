/* ============================================================
   16_seed_crosswalk_bidlog_check.sql (eda, 구 02g_seed_crosswalk_bidlog_check.sql)
   배경: 02c 결과 — seed가 skb.ad_id와는 0건, skb.platform_ad_id와는 928,809건(61.2%)
   매칭됐다. 즉 seed의 device_ifa는 raw GAID(ad_id) 공간이 아니라 platform_ad_id
   공간에 있다(00_id_mapping_check.sql이 확인한 ptbwa_tg.uuid와 같은 공간).

   가설: seed → skb.platform_ad_id로 매칭되는 행의 skb.ad_id를 뽑으면, 그게 진짜
   GAID이므로 abi_bid_log_flatten.device_ifa(01_seed_coverage_check.sql에서 직접
   매칭했던 135,165명보다 훨씬 클 수 있음)와 skp.ad_id(세그먼트) 양쪽에 다 붙을 수 있다.
   이 쿼리는 그중 bidlog 쪽을 확인한다(세그먼트 쪽은 02h).
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
seed_ad_id AS (
    SELECT DISTINCT k.ad_id
    FROM seed sd
    JOIN skb k ON sd.device_ifa = k.platform_ad_id
),
bidlog AS (
    SELECT DISTINCT device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')
      AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
)
SELECT
    (SELECT count(*) FROM seed)         AS seed_total,
    (SELECT count(*) FROM seed_ad_id)   AS seed_crosswalked_to_ad_id,
    count(b.device_ifa)                 AS crosswalked_matches_bidlog
FROM seed_ad_id sa
LEFT JOIN bidlog b ON sa.ad_id = b.device_ifa;
