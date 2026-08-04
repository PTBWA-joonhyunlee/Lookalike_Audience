/* ============================================================
   22_candidate_202606_segment_media_coverage.sql (eda, 2026-08-04)
   목적: "6월 신규 유저"(seed 제외 + 2026-06 활동 + region=KR + OS=Android — segment/03_
   create_candidate_table.sql / media/04_create_candidate_table_media.sql의 base 조건과
   동일) 중, skp segment가 있는 비율 / media(top500 30분dedup 5회 이상)가 있는 비율 /
   둘 다 있는 비율 / 둘 중 하나라도 있는 비율을 한 번에 구한다.

   배경: segment 매칭만으로는 커버되는 신규 유저가 소수뿐이라(2026-07-30 확인,
   segment/03 주석 참고) media 단독 추출을 추가 트랙으로 도입했다 — "segment로 부족한
   만큼 media로 얼마나 더 채울 수 있는지"를 이 표 하나로 정리하기 위한 쿼리.

   base/seg/media_ok 서브쿼리 로직은 각각 segment/03_create_candidate_table.sql,
   media/04_create_candidate_table_media.sql과 동일하게 맞췄다(같은 필터를 두 번
   따로 정의하지 않고 여기서 하나로 합쳐 계산). 전제: propfit_media_top500,
   seed_piellaven_ad_id가 이미 있어야 함(01_create_media_vocab_table.sql,
   01/02_create_seed*.sql).
   ============================================================ */

WITH base AS (
    SELECT DISTINCT b.device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten" b
    LEFT JOIN seed_piellaven_ad_id sd ON b.device_ifa = sd.device_ifa
    WHERE b.year = '2026' AND b.month = '06'
      AND b.device_ifa IS NOT NULL AND trim(CAST(b.device_ifa AS VARCHAR)) <> ''
      AND regexp_like(CAST(b.device_ifa AS VARCHAR), '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
      AND sd.device_ifa IS NULL
      AND CAST(b.device_geo_region AS VARCHAR) LIKE 'KR%'
      AND regexp_like(CAST(b.device_osv AS VARCHAR), '^[0-9]+$')
),
seg AS (
    SELECT ad_id AS device_ifa
    FROM (
        SELECT
            ad_id,
            ROW_NUMBER() OVER (
                PARTITION BY ad_id
                ORDER BY year DESC, month DESC, day DESC
            ) AS rn
        FROM "propfit"."skp"
        WHERE NOT (year = '2024' AND month = '12' AND day = '31')
          AND CAST(id_type AS VARCHAR) = '2'
          AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
    ) x
    WHERE rn = 1
),
raw_visit AS (
    SELECT
        v.req_id,
        v.req_user_id,
        v.device_ifa,
        COALESCE(
            NULLIF(CAST(v.app_bundle AS VARCHAR), ''),
            NULLIF(CAST(v.site_page AS VARCHAR), '')
        ) AS media,
        CAST(from_iso8601_timestamp(CAST(v.created_at AS VARCHAR)) AT TIME ZONE 'Asia/Seoul' AS timestamp) AS ts
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten" v
    JOIN base ON v.device_ifa = base.device_ifa
    JOIN propfit_media_top500 r
      ON COALESCE(NULLIF(CAST(v.app_bundle AS VARCHAR), ''), NULLIF(CAST(v.site_page AS VARCHAR), '')) = r.media
    WHERE v.year = '2026' AND v.month = '06'
      AND v.req_user_id IS NOT NULL AND trim(CAST(v.req_user_id AS VARCHAR)) <> ''
      AND CAST(v.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (v.device_lmt IS NULL OR CAST(v.device_lmt AS VARCHAR) <> '1')
),
flagged AS (
    SELECT
        device_ifa,
        media,
        ts,
        req_id,
        LAG(media) OVER (PARTITION BY req_user_id ORDER BY ts, req_id) AS prev_media,
        LAG(ts)    OVER (PARTITION BY req_user_id ORDER BY ts, req_id) AS prev_ts
    FROM raw_visit
),
media_ok AS (
    SELECT device_ifa
    FROM flagged
    WHERE prev_media IS NULL
       OR prev_media <> media
       OR date_diff('second', prev_ts, ts) >= 1800
    GROUP BY device_ifa
    HAVING COUNT(*) >= 5
)
SELECT
    COUNT(DISTINCT base.device_ifa) AS total_202606,
    COUNT(DISTINCT seg.device_ifa) AS with_segment,
    COUNT(DISTINCT media_ok.device_ifa) AS with_media,
    COUNT(DISTINCT CASE WHEN seg.device_ifa IS NOT NULL AND media_ok.device_ifa IS NOT NULL THEN base.device_ifa END) AS with_both,
    COUNT(DISTINCT CASE WHEN seg.device_ifa IS NOT NULL OR media_ok.device_ifa IS NOT NULL THEN base.device_ifa END) AS with_either
FROM base
LEFT JOIN seg ON base.device_ifa = seg.device_ifa
LEFT JOIN media_ok ON base.device_ifa = media_ok.device_ifa;
