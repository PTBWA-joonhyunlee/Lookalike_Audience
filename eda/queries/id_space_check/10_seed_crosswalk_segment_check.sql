/* ============================================================
   id_space_check/10_seed_crosswalk_segment_check.sql (eda, 구 eda/queries/17_seed_crosswalk_segment_check.sql —
   2026-08-26 id_space_check/ 폴더 이동 + 번호 재부여, 그 이전엔 02h_seed_crosswalk_segment_check.sql)
   배경: 02g와 같은 크로스워크(seed → skb.platform_ad_id → skb.ad_id)를 쓰되, 이번엔
   그 ad_id를 propfit.skp.ad_id(세그먼트)에 직접 붙인다 — 01_seed_coverage_check.sql의
   직접 조인(seed.device_ifa = skp.ad_id)이 1건만 나온 문제를 이 크로스워크로 우회할
   수 있는지 확인하는 쿼리. 이게 이번 seed_lookalike 트랙에서 segment_features를 살릴
   수 있는 마지막 경로다 — 여기서도 낮으면 segment_features는 이번 seed엔 포기한다.
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
segments AS (
    SELECT DISTINCT ad_id
    FROM "propfit"."skp"
    WHERE NOT (year = '2024' AND month = '12' AND day = '31')
      AND CAST(id_type AS VARCHAR) = '2'
      AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
)
SELECT
    (SELECT count(*) FROM seed)         AS seed_total,
    (SELECT count(*) FROM seed_ad_id)   AS seed_crosswalked_to_ad_id,
    count(s.ad_id)                      AS crosswalked_matches_segments
FROM seed_ad_id sa
LEFT JOIN segments s ON sa.ad_id = s.ad_id;
